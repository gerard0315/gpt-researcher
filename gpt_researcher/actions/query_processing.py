import json_repair
import re
from enum import Enum
from urllib.parse import urlparse
import os

from gpt_researcher.llm_provider.generic.base import ReasoningEfforts
from ..utils.llm import create_chat_completion
from ..prompts import PromptFamily
from typing import Any, List, Dict, Optional, TypedDict
from ..config import Config
import logging

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
_DOMAIN_PATTERN = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.IGNORECASE)
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_COMPANY_LABEL_PATTERNS = [
    r"company\s*name\s*[:：]\s*([^\n\r;；。]+)",
    r"subject\s*[:：]\s*([^\n\r;；。]+)",
    r"公司名称\s*[:：]\s*([^\n\r;；。]+)",
    r"项目名\s*[:：]\s*([^\n\r;；。]+)",
]
_TRANSLATED_QUERY_CACHE: dict[str, str] = {}
_STAGE_A_CACHE: dict[tuple, "SubjectConceptAnalysis"] = {}


class QueryLane(str, Enum):
    subject = "subject"
    concept = "concept"
    intersection = "intersection"


class PlannedQuery(TypedDict):
    query: str
    lane: str
    rationale: Optional[str]


class SubjectConceptAnalysis(TypedDict):
    intention: str
    subject_summary: str
    concept_terms: Dict[str, List[str]]
    recommended_lane_budget: Dict[str, int]


def contains_cjk(text: str) -> bool:
    """Return True when text contains CJK ideographs (e.g., Chinese)."""
    if not text:
        return False
    return bool(_CJK_PATTERN.search(text))


def _is_translation_enabled() -> bool:
    raw = os.getenv("AUTO_TRANSLATE_NON_ENGLISH_PROMPTS", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _strip_code_fences(text: str) -> str:
    if not text:
        return ""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned).strip()
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
    return cleaned


async def get_working_query_for_planning(
    query: str,
    cfg: Config,
    cost_callback: callable = None,
    **kwargs
) -> str:
    """
    Convert non-English (e.g., Chinese) prompts into an English working query
    for internal planning/search, while preserving original prompt elsewhere.
    """
    if not query:
        return query
    if not _is_translation_enabled() or not contains_cjk(query):
        return query

    cached = _TRANSLATED_QUERY_CACHE.get(query)
    if cached:
        return cached

    messages = [
        {
            "role": "system",
            "content": (
                "You translate research task prompts into English for internal planning.\n"
                "Rules:\n"
                "1) Preserve entity names, URLs/domains, numbers, dates, and legal identifiers exactly as written.\n"
                "2) Do not add, remove, or infer facts.\n"
                "3) Keep constraints and task structure intact.\n"
                "4) Output only the translated English text without commentary."
            ),
        },
        {"role": "user", "content": query},
    ]

    try:
        translated = await create_chat_completion(
            model=cfg.fast_llm_model,
            messages=messages,
            llm_provider=cfg.fast_llm_provider,
            temperature=0,
            max_tokens=cfg.fast_token_limit,
            llm_kwargs=cfg.llm_kwargs,
            reasoning_effort=ReasoningEfforts.Low.value,
            cost_callback=cost_callback,
            **kwargs,
        )
    except Exception as exc:
        logger.warning(
            f"Prompt translation failed, continuing with original query: {exc}"
        )
        _TRANSLATED_QUERY_CACHE[query] = query
        return query

    translated = _strip_code_fences(translated)
    if not translated:
        translated = query

    _TRANSLATED_QUERY_CACHE[query] = translated
    return translated


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    return list(dict.fromkeys(values))


def extract_query_anchors(query: str) -> Dict[str, List[str]]:
    """Extract entity anchors (domains and aliases) from the original query."""
    if not query:
        return {"domains": [], "aliases": []}

    domains: list[str] = []
    aliases: list[str] = []

    for raw_url in _URL_PATTERN.findall(query):
        parsed = urlparse(raw_url.strip())
        domain = (parsed.netloc or "").lower().strip(".")
        if domain.startswith("www."):
            domain = domain[4:]
        if domain:
            domains.append(domain)

    for domain_match in _DOMAIN_PATTERN.findall(query):
        domain = domain_match.lower().strip(".")
        if domain.startswith("www."):
            domain = domain[4:]
        if domain:
            domains.append(domain)

    for pattern in _COMPANY_LABEL_PATTERNS:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if not match:
            continue
        alias = re.sub(r"\s+", " ", match.group(1)).strip()
        if alias:
            aliases.append(alias)

    for quoted in re.findall(r"[\"“”']([^\"“”']{3,80})[\"“”']", query):
        alias = re.sub(r"\s+", " ", quoted).strip()
        # Only keep human-readable aliases (skip pure operators/noise)
        if alias and re.search(r"[a-zA-Z]", alias):
            aliases.append(alias)

    domains = _dedupe_preserve_order(domains)
    aliases = _dedupe_preserve_order(aliases)
    return {"domains": domains, "aliases": aliases}


def _contains_anchor(text: str, anchors: Dict[str, List[str]]) -> bool:
    lowered = text.lower()

    for domain in anchors.get("domains", []):
        root = domain.split(".")[0]
        if domain in lowered or f"site:{domain}" in lowered:
            return True
        if len(root) >= 4 and root in lowered:
            return True

    for alias in anchors.get("aliases", []):
        alias_lower = alias.lower()
        if alias_lower and alias_lower in lowered:
            return True

    return False


def _build_anchor_prefix(anchors: Dict[str, List[str]]) -> str:
    aliases = anchors.get("aliases") or []
    domains = anchors.get("domains") or []
    alias = aliases[0] if aliases else None
    domain = domains[0] if domains else None

    if alias and domain:
        return f'("{alias}" OR "{domain}")'
    if alias:
        return f'"{alias}"'
    if domain:
        return f'"{domain}"'
    return ""


def _build_identity_verification_query(anchors: Dict[str, List[str]], fallback_query: str) -> str:
    domains = anchors.get("domains") or []
    domain = domains[0] if domains else None
    anchor_prefix = _build_anchor_prefix(anchors)

    if domain:
        return (
            f'{anchor_prefix} site:{domain} '
            f'(official OR about OR company OR team OR product OR "press release" OR "contact")'
        ).strip()
    if anchor_prefix:
        return f'{anchor_prefix} ("official website" OR company profile OR about OR product OR team)'
    return fallback_query

def ground_generated_queries(
    sub_queries: List[str],
    original_query: str,
    max_queries: int | None = None,
) -> List[str]:
    """
    Ground generated sub-queries to the original subject to reduce entity drift.

    This function is best-effort: if grounding fails for any reason, it returns
    the original sub_queries (or [original_query]) so that the research pipeline
    continues uninterrupted.
    """
    fallback = sub_queries if sub_queries else [original_query]
    try:
        if not sub_queries:
            return [original_query]

        anchors = extract_query_anchors(original_query)
        has_anchors = bool(anchors["domains"] or anchors["aliases"])

        grounded: list[str] = []
        for query in sub_queries:
            if not isinstance(query, str):
                continue
            candidate = re.sub(r"\s+", " ", query).strip()
            if not candidate:
                continue

            if has_anchors and not _contains_anchor(candidate, anchors):
                anchor_prefix = _build_anchor_prefix(anchors)
                candidate = f"{anchor_prefix} {candidate}".strip() if anchor_prefix else candidate

            grounded.append(candidate)

        grounded = _dedupe_preserve_order(grounded)

        if has_anchors:
            primary_domain = anchors["domains"][0] if anchors["domains"] else None
            has_identity_query = any(
                (f"site:{primary_domain}" in q.lower()) if primary_domain else False
                for q in grounded
            )
            if not has_identity_query:
                identity_query = _build_identity_verification_query(anchors, original_query)
                if grounded:
                    grounded[0] = identity_query
                else:
                    grounded = [identity_query]

        if not grounded:
            grounded = [original_query]

        if max_queries is not None and max_queries > 0:
            grounded = grounded[:max_queries]

        return grounded
    except Exception as exc:
        logger.warning("Entity grounding failed (%s), using ungrounded queries.", exc)
        return fallback


def _normalize_sub_queries(sub_queries: Any, fallback_query: str) -> List[str]:
    """
    Coerce model output into a clean list of string queries.

    The strategic model can sometimes return mixed structures (e.g. reasoning
    blocks + actual query arrays). This helper extracts only valid query text.
    """
    collected_queries: list[str] = []

    def _collect(item: Any) -> None:
        if isinstance(item, str):
            query = item.strip()
            if query:
                collected_queries.append(query)
            return

        if isinstance(item, list):
            for value in item:
                _collect(value)
            return

        if isinstance(item, dict):
            # Common shapes from model outputs
            for key in ("query", "search_query", "sub_query", "text"):
                value = item.get(key)
                if isinstance(value, str):
                    query = value.strip()
                    if query:
                        collected_queries.append(query)

            for key in ("queries", "sub_queries", "subqueries", "items", "results", "content"):
                if key in item:
                    _collect(item.get(key))

    _collect(sub_queries)

    # Keep order, remove duplicates
    normalized = list(dict.fromkeys(collected_queries))
    if normalized:
        return normalized

    logger.warning("No valid string sub-queries found in model output. Using original query only.")
    return [fallback_query]

def _extract_query_str(item: Any) -> str:
    """Extract a clean query string from a string or dict item."""
    if isinstance(item, str):
        return re.sub(r"\s+", " ", item).strip()
    if isinstance(item, dict):
        for key in ("query", "search_query", "text", "q"):
            if isinstance(item.get(key), str):
                return re.sub(r"\s+", " ", item[key]).strip()
    return ""


def _heuristic_concept_analysis(query: str) -> SubjectConceptAnalysis:
    """Fallback Stage A when the LLM call fails: extract concept terms via simple regex."""
    industry_terms = re.findall(
        r"\b(?:market|industry|regulation|policy|supply\s*chain|technology|platform|saas|b2b|b2c)\b",
        query, re.IGNORECASE,
    )
    return SubjectConceptAnalysis(
        intention="general",
        subject_summary=query[:200],
        concept_terms={"industry": list(dict.fromkeys(t.lower() for t in industry_terms))},
        recommended_lane_budget={},
    )


def _allocate_lane_slots(
    budget: Dict[str, int],
    max_iterations: int,
    min_concept: int,
    min_intersection: int,
) -> Dict[str, int]:
    """Deterministic lane slot allocation: floor + highest-fractional-remainder, then apply mins."""
    lanes = ["subject", "concept", "intersection"]
    total_budget = sum(budget.get(lane, 0) for lane in lanes) or 100

    raw = {lane: budget.get(lane, 0) * max_iterations / total_budget for lane in lanes}
    floors: Dict[str, int] = {lane: int(raw[lane]) for lane in lanes}
    remainders = {lane: raw[lane] - floors[lane] for lane in lanes}

    # Distribute remaining slots by highest fractional remainder
    remaining_slots = max_iterations - sum(floors.values())
    for lane in sorted(lanes, key=lambda l: remainders[l], reverse=True)[:remaining_slots]:
        floors[lane] += 1

    # Apply concept minimum; absorb from subject first, then intersection
    if floors["concept"] < min_concept:
        shortage = min_concept - floors["concept"]
        floors["concept"] = min_concept
        for donor in sorted(["subject", "intersection"], key=lambda l: floors[l], reverse=True):
            take = min(shortage, max(0, floors[donor] - 1))
            floors[donor] -= take
            shortage -= take
            if shortage <= 0:
                break

    # Apply intersection minimum; absorb from concept first, then subject
    if floors["intersection"] < min_intersection:
        shortage = min_intersection - floors["intersection"]
        floors["intersection"] = min_intersection
        for donor in sorted(["concept", "subject"], key=lambda l: floors[l], reverse=True):
            take = min(shortage, max(0, floors[donor] - 1))
            floors[donor] -= take
            shortage -= take
            if shortage <= 0:
                break

    return floors


async def analyze_subject_and_concepts(
    query: str,
    parent_query: str,
    report_type: str,
    cfg: Config,
    cost_callback: callable = None,
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    **kwargs,
) -> SubjectConceptAnalysis:
    """Stage A: call the LLM to analyse the subject entity and its concept space."""
    cache_key = (query, parent_query or "", report_type)
    if cache_key in _STAGE_A_CACHE:
        return _STAGE_A_CACHE[cache_key]

    analysis_prompt = prompt_family.generate_subject_concept_analysis_prompt(
        query, parent_query, report_type
    )

    try:
        response = await create_chat_completion(
            model=cfg.fast_llm_model,
            messages=[{"role": "user", "content": analysis_prompt}],
            llm_provider=cfg.fast_llm_provider,
            temperature=0,
            max_tokens=cfg.fast_token_limit,
            llm_kwargs=cfg.llm_kwargs,
            reasoning_effort=ReasoningEfforts.Low.value,
            cost_callback=cost_callback,
            **kwargs,
        )
        parsed = json_repair.loads(_strip_code_fences(response or ""))
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected dict from Stage A, got {type(parsed)}")
        analysis = SubjectConceptAnalysis(
            intention=parsed.get("intention", "general"),
            subject_summary=parsed.get("subject_summary", ""),
            concept_terms=parsed.get("concept_terms", {}),
            recommended_lane_budget=parsed.get("recommended_lane_budget", {}),
        )
    except Exception as exc:
        logger.warning(f"Stage A analysis failed ({exc}), using heuristic fallback.")
        analysis = _heuristic_concept_analysis(query)

    _STAGE_A_CACHE[cache_key] = analysis
    logger.debug(
        "Stage A: intention=%s, concept_facets=%s",
        analysis["intention"],
        list(analysis["concept_terms"].keys()),
    )
    return analysis


async def generate_lane_queries(
    query: str,
    parent_query: str,
    report_type: str,
    analysis: SubjectConceptAnalysis,
    lane_budget: Dict[str, int],
    context: List[Dict[str, Any]],
    cfg: Config,
    cost_callback: callable = None,
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    **kwargs,
) -> Dict[str, List[str]]:
    """Stage B: call the LLM to generate lane-structured queries."""
    _LANE_ALIASES: Dict[str, str] = {
        "subject_queries": "subject",
        "company_queries": "subject",
        "concept_queries": "concept",
        "industry_queries": "concept",
        "intersection_queries": "intersection",
    }
    empty: Dict[str, List[str]] = {"subject": [], "concept": [], "intersection": []}

    lane_prompt = prompt_family.generate_lane_search_queries_prompt(
        query, parent_query, report_type, analysis, lane_budget, context
    )

    response = None
    try:
        response = await create_chat_completion(
            model=cfg.strategic_llm_model,
            messages=[{"role": "user", "content": lane_prompt}],
            llm_provider=cfg.strategic_llm_provider,
            max_tokens=None,
            llm_kwargs=cfg.llm_kwargs,
            reasoning_effort=ReasoningEfforts.Medium.value,
            cost_callback=cost_callback,
            **kwargs,
        )
    except Exception as exc:
        logger.warning(f"Stage B failed ({exc}), retrying with token limit.")
        try:
            response = await create_chat_completion(
                model=cfg.strategic_llm_model,
                messages=[{"role": "user", "content": lane_prompt}],
                llm_provider=cfg.strategic_llm_provider,
                max_tokens=cfg.strategic_token_limit,
                llm_kwargs=cfg.llm_kwargs,
                cost_callback=cost_callback,
                **kwargs,
            )
        except Exception as exc2:
            logger.warning(f"Stage B retry also failed ({exc2}). Returning empty lanes.")
            return empty

    if not response:
        return empty

    try:
        parsed = json_repair.loads(_strip_code_fences(response))
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected dict from Stage B, got {type(parsed)}")

        lanes: Dict[str, List[str]] = {"subject": [], "concept": [], "intersection": []}
        for key, value in parsed.items():
            lane = _LANE_ALIASES.get(key)
            if lane and isinstance(value, list):
                for item in value:
                    q = _extract_query_str(item)
                    if q:
                        lanes[lane].append(q)

        logger.debug(
            "Stage B raw counts: subject=%d, concept=%d, intersection=%d",
            len(lanes["subject"]), len(lanes["concept"]), len(lanes["intersection"]),
        )
        return lanes
    except Exception as exc:
        logger.warning(f"Failed to parse Stage B response ({exc}). Returning empty lanes.")
        return empty


def ground_lane_queries(
    lane_queries: Dict[str, List[str]],
    original_query: str,
) -> Dict[str, List[str]]:
    """Lane-aware grounding: anchor subject/intersection queries, leave concept free.

    Best-effort: returns lane_queries unchanged if grounding fails.
    """
    try:
        anchors = extract_query_anchors(original_query)
        has_anchors = bool(anchors["domains"] or anchors["aliases"])

        result: Dict[str, List[str]] = {}
        for lane, queries in lane_queries.items():
            grounded: List[str] = []
            for q in queries:
                if not isinstance(q, str):
                    continue
                candidate = re.sub(r"\s+", " ", q).strip()
                if not candidate:
                    continue
                if lane in ("subject", "intersection") and has_anchors and not _contains_anchor(candidate, anchors):
                    anchor_prefix = _build_anchor_prefix(anchors)
                    candidate = f"{anchor_prefix} {candidate}".strip() if anchor_prefix else candidate
                # concept lane: no forced anchor
                grounded.append(candidate)
            result[lane] = _dedupe_preserve_order(grounded)

        # Ensure subject lane always has an identity query
        if has_anchors and "subject" in result:
            primary_domain = anchors["domains"][0] if anchors["domains"] else None
            has_identity = any(
                (f"site:{primary_domain}" in q.lower()) if primary_domain else False
                for q in result["subject"]
            )
            if not has_identity:
                identity_q = _build_identity_verification_query(anchors, original_query)
                result["subject"].insert(0, identity_q)
                result["subject"] = _dedupe_preserve_order(result["subject"])
    except Exception as exc:
        logger.warning("Lane grounding failed (%s), using ungrounded lane queries.", exc)
        return lane_queries

    logger.debug(
        "After lane grounding: %s",
        ", ".join(f"{k}={len(v)}" for k, v in result.items()),
    )
    return result


def _merge_lane_queries(
    grounded_lanes: Dict[str, List[str]],
    slots: Dict[str, int],
) -> List[str]:
    """Merge lane queries into a flat list respecting slot allocation.

    Overflow reallocation priority: intersection → concept → subject.
    """
    merged: List[str] = []
    # Fill primary slots in subject → concept → intersection order
    for lane in ("subject", "concept", "intersection"):
        available = grounded_lanes.get(lane, [])
        quota = slots.get(lane, 0)
        merged.extend(available[:quota])

    # Fill any unfilled slots from lane excess in reallocation priority order
    total_slots = sum(slots.values())
    if len(merged) < total_slots:
        for lane in ("concept", "subject", "intersection"):
            available = grounded_lanes.get(lane, [])
            quota = slots.get(lane, 0)
            excess = available[quota:]
            for q in excess:
                if q not in merged:
                    merged.append(q)
                if len(merged) >= total_slots:
                    break
            if len(merged) >= total_slots:
                break

    return _dedupe_preserve_order(merged)


async def _generate_sub_queries_dual_lane(
    query: str,
    working_query: str,
    working_parent_query: str,
    report_type: str,
    context: List[Dict[str, Any]],
    cfg: Config,
    max_iterations: int,
    cost_callback: callable = None,
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    **kwargs,
) -> List[str]:
    """Dual-lane planning path: Stage A analysis + Stage B lane generation + merge."""
    analysis = await analyze_subject_and_concepts(
        query=working_query,
        parent_query=working_parent_query,
        report_type=report_type,
        cfg=cfg,
        cost_callback=cost_callback,
        prompt_family=prompt_family,
        **kwargs,
    )

    # Resolve lane budget
    use_llm_budget = getattr(cfg, "use_llm_recommended_lane_budget", False)
    config_budget: Dict[str, int] = getattr(
        cfg, "query_lane_budget", {"subject": 40, "concept": 40, "intersection": 20}
    )
    if use_llm_budget and analysis.get("recommended_lane_budget"):
        raw_budget = analysis["recommended_lane_budget"]
        total = sum(raw_budget.values()) or 1
        budget = {k: int(v * 100 / total) for k, v in raw_budget.items()}
    else:
        budget = config_budget

    min_concept = getattr(cfg, "min_concept_queries", 1) if max_iterations >= 2 else 0
    min_intersection = getattr(cfg, "min_intersection_queries", 0) if max_iterations >= 3 else 0

    slots = _allocate_lane_slots(budget, max_iterations, min_concept, min_intersection)
    logger.debug("Lane slots allocated: %s", slots)

    lane_queries = await generate_lane_queries(
        query=working_query,
        parent_query=working_parent_query,
        report_type=report_type,
        analysis=analysis,
        lane_budget=slots,
        context=context,
        cfg=cfg,
        cost_callback=cost_callback,
        prompt_family=prompt_family,
        **kwargs,
    )

    # Fall back to legacy path if Stage B returned nothing
    if not any(lane_queries.values()):
        logger.warning("Stage B returned no queries. Falling back to legacy planner.")
        return ground_generated_queries([working_query], query, max_queries=max_iterations)

    grounded_lanes = ground_lane_queries(lane_queries, query)
    merged = _merge_lane_queries(grounded_lanes, slots)

    logger.debug(
        "Final lane allocation: subject=%d, concept=%d, intersection=%d, total=%d",
        len([q for q in merged if _contains_anchor(q, extract_query_anchors(query))]),
        slots.get("concept", 0),
        slots.get("intersection", 0),
        len(merged),
    )

    if not merged:
        return ground_generated_queries([working_query], query, max_queries=max_iterations)

    return merged[:max_iterations]


async def get_search_results(query: str, retriever: Any, query_domains: List[str] = None, researcher=None) -> List[Dict[str, Any]]:
    """
    Get web search results for a given query.

    Args:
        query: The search query
        retriever: The retriever instance
        query_domains: Optional list of domains to search
        researcher: The researcher instance (needed for MCP retrievers)

    Returns:
        A list of search results
    """
    # Check if this is an MCP retriever and pass the researcher instance
    if "mcpretriever" in retriever.__name__.lower():
        search_retriever = retriever(
            query, 
            query_domains=query_domains,
            researcher=researcher  # Pass researcher instance for MCP retrievers
        )
    else:
        search_retriever = retriever(query, query_domains=query_domains)
    
    return search_retriever.search()

async def generate_sub_queries(
    query: str,
    parent_query: str,
    report_type: str,
    context: List[Dict[str, Any]],
    cfg: Config,
    cost_callback: callable = None,
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    **kwargs
) -> List[str]:
    """
    Generate sub-queries using the specified LLM model.

    Args:
        query: The original query
        parent_query: The parent query
        report_type: The type of report
        max_iterations: Maximum number of research iterations
        context: Search results context
        cfg: Configuration object
        cost_callback: Callback for cost calculation
        prompt_family: Family of prompts

    Returns:
        A list of sub-queries
    """
    max_iterations = cfg.max_iterations or 3

    working_query = await get_working_query_for_planning(
        query=query,
        cfg=cfg,
        cost_callback=cost_callback,
        **kwargs,
    )
    working_parent_query = (
        await get_working_query_for_planning(
            query=parent_query,
            cfg=cfg,
            cost_callback=cost_callback,
            **kwargs,
        )
        if parent_query
        else parent_query
    )

    if getattr(cfg, "dual_lane_query_planner", False):
        return await _generate_sub_queries_dual_lane(
            query=query,
            working_query=working_query,
            working_parent_query=working_parent_query,
            report_type=report_type,
            context=context,
            cfg=cfg,
            max_iterations=max_iterations,
            cost_callback=cost_callback,
            prompt_family=prompt_family,
            **kwargs,
        )

    gen_queries_prompt = prompt_family.generate_search_queries_prompt(
        working_query,
        working_parent_query,
        report_type,
        max_iterations=max_iterations,
        context=context,
    )

    try:
        response = await create_chat_completion(
            model=cfg.strategic_llm_model,
            messages=[{"role": "user", "content": gen_queries_prompt}],
            llm_provider=cfg.strategic_llm_provider,
            max_tokens=None,
            llm_kwargs=cfg.llm_kwargs,
            reasoning_effort=ReasoningEfforts.Medium.value,
            cost_callback=cost_callback,
            **kwargs
        )
    except Exception as e:
        logger.warning(f"Error with strategic LLM: {e}. Retrying with max_tokens={cfg.strategic_token_limit}.")
        logger.warning(f"See https://github.com/assafelovic/gpt-researcher/issues/1022")
        try:
            response = await create_chat_completion(
                model=cfg.strategic_llm_model,
                messages=[{"role": "user", "content": gen_queries_prompt}],
                max_tokens=cfg.strategic_token_limit,
                llm_provider=cfg.strategic_llm_provider,
                llm_kwargs=cfg.llm_kwargs,
                cost_callback=cost_callback,
                **kwargs
            )
            logger.warning(f"Retrying with max_tokens={cfg.strategic_token_limit} successful.")
        except Exception as e:
            logger.warning(f"Retrying with max_tokens={cfg.strategic_token_limit} failed.")
            logger.warning(f"Error with strategic LLM: {e}. Falling back to smart LLM.")
            response = await create_chat_completion(
                model=cfg.smart_llm_model,
                messages=[{"role": "user", "content": gen_queries_prompt}],
                temperature=cfg.temperature,
                max_tokens=cfg.smart_token_limit,
                llm_provider=cfg.smart_llm_provider,
                llm_kwargs=cfg.llm_kwargs,
                cost_callback=cost_callback,
                **kwargs
            )

    if not response:
        logger.warning("LLM returned empty response while generating sub-queries. Using the original query only.")
        return ground_generated_queries(
            [working_query],
            query,
            max_queries=max_iterations,
        )

    try:
        parsed_sub_queries = json_repair.loads(response)
        normalized = _normalize_sub_queries(parsed_sub_queries, query)
        return ground_generated_queries(
            normalized,
            query,
            max_queries=max_iterations,
        )
    except Exception as e:
        logger.warning(f"Failed to parse generated sub-queries: {e}. Using the original query only.")
        return ground_generated_queries(
            [working_query],
            query,
            max_queries=max_iterations,
        )

async def plan_research_outline(
    query: str,
    search_results: List[Dict[str, Any]],
    agent_role_prompt: str,
    cfg: Config,
    parent_query: str,
    report_type: str,
    cost_callback: callable = None,
    retriever_names: List[str] = None,
    **kwargs
) -> List[str]:
    """
    Plan the research outline by generating sub-queries.

    Args:
        query: Original query
        search_results: Initial search results
        agent_role_prompt: Agent role prompt
        cfg: Configuration object
        parent_query: Parent query
        report_type: Report type
        cost_callback: Callback for cost calculation
        retriever_names: Names of the retrievers being used

    Returns:
        A list of sub-queries
    """
    # Handle the case where retriever_names is not provided
    if retriever_names is None:
        retriever_names = []
    
    # For MCP retrievers, we may want to skip sub-query generation
    # Check if MCP is the only retriever or one of multiple retrievers
    if retriever_names and ("mcp" in retriever_names or "MCPRetriever" in retriever_names):
        mcp_only = (len(retriever_names) == 1 and 
                   ("mcp" in retriever_names or "MCPRetriever" in retriever_names))
        
        if mcp_only:
            # If MCP is the only retriever, skip sub-query generation
            logger.info("Using MCP retriever only - skipping sub-query generation")
            # Return the original query to prevent additional search iterations
            return [query]
        else:
            # If MCP is one of multiple retrievers, generate sub-queries for the others
            logger.info("Using MCP with other retrievers - generating sub-queries for non-MCP retrievers")

    # Generate sub-queries for research outline
    sub_queries = await generate_sub_queries(
        query,
        parent_query,
        report_type,
        search_results,
        cfg,
        cost_callback,
        **kwargs
    )

    return sub_queries
