import json_repair
import re
from urllib.parse import urlparse
import os

from gpt_researcher.llm_provider.generic.base import ReasoningEfforts
from ..utils.llm import create_chat_completion
from ..prompts import PromptFamily
from typing import Any, List, Dict
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
    alias = anchors.get("aliases", [None])[0]
    domain = anchors.get("domains", [None])[0]

    if alias and domain:
        return f'("{alias}" OR "{domain}")'
    if alias:
        return f'"{alias}"'
    if domain:
        return f'"{domain}"'
    return ""


def _build_identity_verification_query(anchors: Dict[str, List[str]], fallback_query: str) -> str:
    domain = anchors.get("domains", [None])[0]
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
    """
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

    gen_queries_prompt = prompt_family.generate_search_queries_prompt(
        working_query,
        working_parent_query,
        report_type,
        max_iterations=cfg.max_iterations or 3,
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
            max_queries=cfg.max_iterations or 3,
        )

    try:
        parsed_sub_queries = json_repair.loads(response)
        normalized = _normalize_sub_queries(parsed_sub_queries, query)
        return ground_generated_queries(
            normalized,
            query,
            max_queries=cfg.max_iterations or 3,
        )
    except Exception as e:
        logger.warning(f"Failed to parse generated sub-queries: {e}. Using the original query only.")
        return ground_generated_queries(
            [working_query],
            query,
            max_queries=cfg.max_iterations or 3,
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
