from types import SimpleNamespace

import pytest

from gpt_researcher.actions import query_processing


def _dummy_cfg():
    return SimpleNamespace(
        max_iterations=3,
        fast_llm_model="test-fast-model",
        fast_llm_provider="openai",
        fast_token_limit=1024,
        strategic_llm_model="test-strategic-model",
        strategic_llm_provider="openai",
        llm_kwargs={},
        strategic_token_limit=2048,
        smart_llm_model="test-smart-model",
        smart_llm_provider="openai",
        smart_token_limit=2048,
        temperature=0.2,
        dual_lane_query_planner=False,
        query_lane_budget={"subject": 40, "concept": 40, "intersection": 20},
        min_concept_queries=1,
        min_intersection_queries=0,
        use_llm_recommended_lane_budget=False,
    )


def _dummy_cfg_lane(max_iterations=3):
    """Config with dual-lane planner enabled."""
    cfg = _dummy_cfg()
    cfg.dual_lane_query_planner = True
    cfg.max_iterations = max_iterations
    return cfg


# ---------------------------------------------------------------------------
# Existing tests (unchanged)
# ---------------------------------------------------------------------------

def test_normalize_sub_queries_filters_reasoning_blocks():
    raw_sub_queries = [
        {"id": "rs_123", "summary": [], "type": "reasoning"},
        [
            "query one",
            "query two",
            {"query": "query three"},
            {"queries": ["query four"]},
        ],
    ]

    normalized = query_processing._normalize_sub_queries(raw_sub_queries, "fallback query")

    assert normalized == ["query one", "query two", "query three", "query four"]


def test_normalize_sub_queries_returns_fallback_when_empty():
    raw_sub_queries = [{"id": "rs_123", "summary": [], "type": "reasoning"}]

    normalized = query_processing._normalize_sub_queries(raw_sub_queries, "fallback query")

    assert normalized == ["fallback query"]


@pytest.mark.asyncio
async def test_generate_sub_queries_handles_reasoning_prefixed_payload(monkeypatch):
    async def fake_create_chat_completion(**kwargs):
        return (
            "{'id': 'rs_abc', 'summary': [], 'type': 'reasoning'}\n"
            "['market sizing ai accelerator', 'groq tenstorrent benchmark 2025']"
        )

    monkeypatch.setattr(query_processing, "create_chat_completion", fake_create_chat_completion)

    sub_queries = await query_processing.generate_sub_queries(
        query="ai hardware market",
        parent_query="ai hardware",
        report_type="research_report",
        context=[],
        cfg=_dummy_cfg(),
    )

    assert sub_queries == [
        "market sizing ai accelerator",
        "groq tenstorrent benchmark 2025",
    ]


def test_extract_query_anchors_reads_company_and_domain():
    query = "公司名称：Unconventional AI；官网：https://unconv.ai/"

    anchors = query_processing.extract_query_anchors(query)

    assert "unconv.ai" in anchors["domains"]
    assert any("Unconventional AI" in alias for alias in anchors["aliases"])


def test_ground_generated_queries_adds_identity_and_keeps_anchored_numeric_claims():
    original_query = "公司名称：Unconventional AI；官网：https://unconv.ai/"
    generated = [
        '("Unconventional AI" OR "unconv.ai") site:unconv.ai (official OR about OR product)',
        '("Unconventional AI" OR unconv.ai) ("$475 million" OR "4.5B") (a16z OR Lightspeed)',
        '("Unconventional AI" OR unconv.ai) (analog OR neuromorphic)',
    ]

    grounded = query_processing.ground_generated_queries(generated, original_query, max_queries=3)
    combined = " ".join(grounded).lower()

    assert grounded
    assert "site:unconv.ai" in grounded[0].lower()
    assert "$475" in combined
    assert "4.5b" in combined


def test_ground_generated_queries_prefixes_missing_anchor():
    original_query = "Company name: Acme Robotics; website: https://acme.ai"
    generated = ["industrial robotics market size 2026"]

    grounded = query_processing.ground_generated_queries(generated, original_query, max_queries=3)

    assert grounded
    assert "acme" in grounded[0].lower()


def test_contains_cjk_detects_chinese():
    assert query_processing.contains_cjk("公司名称：Unconventional AI")
    assert not query_processing.contains_cjk("Company name: Unconventional AI")


@pytest.mark.asyncio
async def test_get_working_query_for_planning_translates_and_caches(monkeypatch):
    call_counter = {"count": 0}

    async def fake_create_chat_completion(**kwargs):
        call_counter["count"] += 1
        return "Company name: Unconventional AI - official website: https://unconv.ai/"

    monkeypatch.setattr(query_processing, "create_chat_completion", fake_create_chat_completion)
    monkeypatch.setenv("AUTO_TRANSLATE_NON_ENGLISH_PROMPTS", "true")
    query_processing._TRANSLATED_QUERY_CACHE.clear()

    original_query = "公司名称：Unconventional AI；官网：https://unconv.ai/"
    cfg = _dummy_cfg()

    first = await query_processing.get_working_query_for_planning(original_query, cfg)
    second = await query_processing.get_working_query_for_planning(original_query, cfg)

    assert "Company name: Unconventional AI" in first
    assert second == first
    assert call_counter["count"] == 1


@pytest.mark.asyncio
async def test_get_working_query_for_planning_keeps_english_unchanged(monkeypatch):
    async def fake_create_chat_completion(**kwargs):
        raise AssertionError("Translation API should not be called for English-only prompts")

    monkeypatch.setattr(query_processing, "create_chat_completion", fake_create_chat_completion)
    query_processing._TRANSLATED_QUERY_CACHE.clear()

    original_query = "Company name: Unconventional AI; website: https://unconv.ai/"
    cfg = _dummy_cfg()

    working = await query_processing.get_working_query_for_planning(original_query, cfg)
    assert working == original_query


# ---------------------------------------------------------------------------
# Lane budget rounding
# ---------------------------------------------------------------------------

def test_allocate_lane_slots_sums_to_max_iterations():
    for n in (2, 3, 4, 5, 8):
        slots = query_processing._allocate_lane_slots(
            budget={"subject": 40, "concept": 40, "intersection": 20},
            max_iterations=n,
            min_concept=1,
            min_intersection=0,
        )
        assert sum(slots.values()) == n, f"slots {slots} don't sum to {n}"


def test_allocate_lane_slots_min_concept_enforced_at_2():
    slots = query_processing._allocate_lane_slots(
        budget={"subject": 80, "concept": 10, "intersection": 10},
        max_iterations=2,
        min_concept=1,
        min_intersection=0,
    )
    assert slots["concept"] >= 1


def test_allocate_lane_slots_min_intersection_enforced_at_3():
    slots = query_processing._allocate_lane_slots(
        budget={"subject": 80, "concept": 15, "intersection": 5},
        max_iterations=3,
        min_concept=1,
        min_intersection=1,
    )
    assert slots["intersection"] >= 1
    assert slots["concept"] >= 1
    assert sum(slots.values()) == 3


def test_allocate_lane_slots_balanced_budget_3():
    slots = query_processing._allocate_lane_slots(
        budget={"subject": 40, "concept": 40, "intersection": 20},
        max_iterations=3,
        min_concept=1,
        min_intersection=0,
    )
    assert slots["concept"] >= 1
    assert sum(slots.values()) == 3


def test_allocate_lane_slots_balanced_budget_5():
    slots = query_processing._allocate_lane_slots(
        budget={"subject": 40, "concept": 40, "intersection": 20},
        max_iterations=5,
        min_concept=1,
        min_intersection=0,
    )
    # 40% of 5 = 2.0 each for subject/concept, 1.0 for intersection
    assert slots["subject"] == 2
    assert slots["concept"] == 2
    assert slots["intersection"] == 1


# ---------------------------------------------------------------------------
# Lane-aware grounding
# ---------------------------------------------------------------------------

def test_ground_lane_queries_concept_lane_stays_unanchored():
    original_query = "Company name: Unconventional AI; website: https://unconv.ai/"
    lane_queries = {
        "subject": ['("Unconventional AI" OR "unconv.ai") funding valuation'],
        "concept": ["neuromorphic computing market size tam sam som 2026"],
        "intersection": [],
    }

    grounded = query_processing.ground_lane_queries(lane_queries, original_query)

    concept_queries = grounded["concept"]
    assert concept_queries
    assert all(
        "unconv.ai" not in q.lower() and "unconventional ai" not in q.lower()
        for q in concept_queries
    )


def test_ground_lane_queries_subject_gets_anchor_when_missing():
    original_query = "Company name: Acme Robotics; website: https://acme.ai"
    lane_queries = {
        "subject": ["latest product release teardown"],
        "concept": [],
        "intersection": [],
    }

    grounded = query_processing.ground_lane_queries(lane_queries, original_query)

    assert grounded["subject"]
    assert "acme" in grounded["subject"][0].lower()


def test_ground_lane_queries_subject_gets_identity_query_inserted():
    original_query = "Company name: Unconventional AI; website: https://unconv.ai/"
    lane_queries = {
        "subject": ['("Unconventional AI" OR "unconv.ai") funding rounds 2025'],
        "concept": [],
        "intersection": [],
    }

    grounded = query_processing.ground_lane_queries(lane_queries, original_query)

    # Identity query with site: should be injected at position 0
    assert "site:unconv.ai" in grounded["subject"][0].lower()


def test_ground_lane_queries_intersection_gets_anchor():
    original_query = "Company name: Unconventional AI; website: https://unconv.ai/"
    lane_queries = {
        "subject": [],
        "concept": [],
        "intersection": ["analog chip adoption risk in ai inference workloads"],
    }

    grounded = query_processing.ground_lane_queries(lane_queries, original_query)

    assert grounded["intersection"]
    assert "unconventional ai" in grounded["intersection"][0].lower() or \
        "unconv.ai" in grounded["intersection"][0].lower()


# ---------------------------------------------------------------------------
# Merge policy
# ---------------------------------------------------------------------------

def test_merge_lane_queries_respects_slot_allocation():
    grounded = {
        "subject": ["s1", "s2", "s3"],
        "concept": ["c1", "c2", "c3"],
        "intersection": ["i1"],
    }
    slots = {"subject": 2, "concept": 2, "intersection": 1}

    merged = query_processing._merge_lane_queries(grounded, slots)

    assert merged == ["s1", "s2", "c1", "c2", "i1"]


def test_merge_lane_queries_reallocates_from_empty_lane():
    """If intersection is empty, its slot should be filled from concept overflow."""
    grounded = {
        "subject": ["s1"],
        "concept": ["c1", "c2", "c3"],
        "intersection": [],
    }
    slots = {"subject": 1, "concept": 1, "intersection": 1}

    merged = query_processing._merge_lane_queries(grounded, slots)

    assert len(merged) == 3
    assert "c2" in merged or "c3" in merged  # overflow from concept fills the gap


def test_merge_lane_queries_deduplicates():
    grounded = {
        "subject": ["s1", "c1"],  # c1 appears in both
        "concept": ["c1", "c2"],
        "intersection": [],
    }
    slots = {"subject": 2, "concept": 2, "intersection": 0}

    merged = query_processing._merge_lane_queries(grounded, slots)

    assert merged.count("c1") == 1


# ---------------------------------------------------------------------------
# Stage A cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_subject_and_concepts_caches_result(monkeypatch):
    call_counter = {"count": 0}

    async def fake_create_chat_completion(**kwargs):
        call_counter["count"] += 1
        return (
            '{"intention":"due_diligence","subject_summary":"Unconventional AI",'
            '"concept_terms":{"industry":["neuromorphic","ai hardware"]},'
            '"recommended_lane_budget":{"subject":40,"concept":40,"intersection":20}}'
        )

    monkeypatch.setattr(query_processing, "create_chat_completion", fake_create_chat_completion)
    query_processing._STAGE_A_CACHE.clear()

    cfg = _dummy_cfg()
    query = "Company name: Unconventional AI; website: https://unconv.ai/"

    first = await query_processing.analyze_subject_and_concepts(query, "", "research_report", cfg)
    second = await query_processing.analyze_subject_and_concepts(query, "", "research_report", cfg)

    assert first["intention"] == "due_diligence"
    assert second == first
    assert call_counter["count"] == 1


@pytest.mark.asyncio
async def test_analyze_subject_and_concepts_falls_back_on_parse_failure(monkeypatch):
    async def fake_create_chat_completion(**kwargs):
        return "not valid json at all !!!"

    monkeypatch.setattr(query_processing, "create_chat_completion", fake_create_chat_completion)
    query_processing._STAGE_A_CACHE.clear()

    cfg = _dummy_cfg()
    result = await query_processing.analyze_subject_and_concepts(
        "Company name: Acme; website: https://acme.ai", "", "research_report", cfg
    )

    # Heuristic fallback must return a valid SubjectConceptAnalysis
    assert "intention" in result
    assert "concept_terms" in result


# ---------------------------------------------------------------------------
# Stage B: generate_lane_queries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_lane_queries_parses_standard_keys(monkeypatch):
    async def fake_create_chat_completion(**kwargs):
        return (
            '{"subject_queries":["Unconventional AI funding 2025"],'
            '"concept_queries":["neuromorphic computing market size 2026"],'
            '"intersection_queries":["Unconventional AI neuromorphic chip adoption risk"]}'
        )

    monkeypatch.setattr(query_processing, "create_chat_completion", fake_create_chat_completion)

    cfg = _dummy_cfg()
    analysis = query_processing._heuristic_concept_analysis("Unconventional AI")
    lanes = await query_processing.generate_lane_queries(
        query="Company name: Unconventional AI; website: https://unconv.ai/",
        parent_query="",
        report_type="research_report",
        analysis=analysis,
        lane_budget={"subject": 1, "concept": 1, "intersection": 1},
        context=[],
        cfg=cfg,
    )

    assert lanes["subject"] == ["Unconventional AI funding 2025"]
    assert lanes["concept"] == ["neuromorphic computing market size 2026"]
    assert lanes["intersection"] == ["Unconventional AI neuromorphic chip adoption risk"]


@pytest.mark.asyncio
async def test_generate_lane_queries_handles_alias_keys(monkeypatch):
    """company_queries → subject, industry_queries → concept."""
    async def fake_create_chat_completion(**kwargs):
        return (
            '{"company_queries":["Unconventional AI official site"],'
            '"industry_queries":["ai chip competitive landscape 2026"],'
            '"intersection_queries":[]}'
        )

    monkeypatch.setattr(query_processing, "create_chat_completion", fake_create_chat_completion)

    cfg = _dummy_cfg()
    analysis = query_processing._heuristic_concept_analysis("Unconventional AI")
    lanes = await query_processing.generate_lane_queries(
        query="Company name: Unconventional AI; website: https://unconv.ai/",
        parent_query="",
        report_type="research_report",
        analysis=analysis,
        lane_budget={"subject": 1, "concept": 1, "intersection": 0},
        context=[],
        cfg=cfg,
    )

    assert lanes["subject"] == ["Unconventional AI official site"]
    assert lanes["concept"] == ["ai chip competitive landscape 2026"]


@pytest.mark.asyncio
async def test_generate_lane_queries_returns_empty_on_bad_json(monkeypatch):
    async def fake_create_chat_completion(**kwargs):
        return "totally unparseable garbage {{{"

    monkeypatch.setattr(query_processing, "create_chat_completion", fake_create_chat_completion)

    cfg = _dummy_cfg()
    analysis = query_processing._heuristic_concept_analysis("Acme")
    lanes = await query_processing.generate_lane_queries(
        query="Company name: Acme; website: https://acme.ai",
        parent_query="",
        report_type="research_report",
        analysis=analysis,
        lane_budget={"subject": 1, "concept": 1, "intersection": 1},
        context=[],
        cfg=cfg,
    )

    # All lanes empty — caller falls back to legacy path
    assert lanes == {"subject": [], "concept": [], "intersection": []}


# ---------------------------------------------------------------------------
# End-to-end dual-lane integration (mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_sub_queries_dual_lane_includes_concept_query(monkeypatch):
    """Full dual-lane path must produce at least one concept-only query."""
    call_log = []

    async def fake_create_chat_completion(**kwargs):
        content = kwargs.get("messages", [{}])[-1].get("content", "")
        # Stage B prompt requests subject_queries / concept_queries in its output schema
        if "subject_queries" in content and "concept_queries" in content:
            # Stage B response
            call_log.append("stage_b")
            return (
                '{"subject_queries":["Unconventional AI site:unconv.ai official about"],'
                '"concept_queries":["neuromorphic computing market size tam 2026",'
                '"ai inference chip competitive landscape"],'
                '"intersection_queries":["Unconventional AI neuromorphic moat timing risk"]}'
            )
        else:
            # Stage A response
            call_log.append("stage_a")
            return (
                '{"intention":"due_diligence",'
                '"subject_summary":"Unconventional AI",'
                '"concept_terms":{"industry":["neuromorphic","ai hardware"],'
                '"regulation":["export controls"]},'
                '"recommended_lane_budget":{"subject":40,"concept":40,"intersection":20}}'
            )

    monkeypatch.setattr(query_processing, "create_chat_completion", fake_create_chat_completion)
    query_processing._STAGE_A_CACHE.clear()
    query_processing._TRANSLATED_QUERY_CACHE.clear()

    cfg = _dummy_cfg_lane(max_iterations=4)
    original_query = "Company name: Unconventional AI; website: https://unconv.ai/"

    sub_queries = await query_processing.generate_sub_queries(
        query=original_query,
        parent_query="",
        report_type="research_report",
        context=[],
        cfg=cfg,
    )

    assert sub_queries
    assert len(sub_queries) <= 4
    # At least one concept-only query (no entity anchor)
    anchors = query_processing.extract_query_anchors(original_query)
    concept_only = [
        q for q in sub_queries
        if not query_processing._contains_anchor(q, anchors)
    ]
    assert concept_only, f"No concept-only query found in: {sub_queries}"
    assert "stage_a" in call_log
    assert "stage_b" in call_log


@pytest.mark.asyncio
async def test_generate_sub_queries_dual_lane_falls_back_when_stage_b_empty(monkeypatch):
    """If Stage B returns empty lanes, fall back to legacy single-call path."""
    calls = []

    async def fake_create_chat_completion(**kwargs):
        content = kwargs.get("messages", [{}])[-1].get("content", "")
        if "concept space" in content.lower():
            calls.append("stage_a")
            return '{"intention":"general","subject_summary":"Acme","concept_terms":{},"recommended_lane_budget":{}}'
        else:
            calls.append("stage_b_or_legacy")
            # Return a flat list (legacy-style) so fallback also works
            return '["Acme Robotics site:acme.ai official", "Acme Robotics competitors"]'

    monkeypatch.setattr(query_processing, "create_chat_completion", fake_create_chat_completion)
    query_processing._STAGE_A_CACHE.clear()

    cfg = _dummy_cfg_lane(max_iterations=3)
    sub_queries = await query_processing.generate_sub_queries(
        query="Company name: Acme Robotics; website: https://acme.ai",
        parent_query="",
        report_type="research_report",
        context=[],
        cfg=cfg,
    )

    assert sub_queries


@pytest.mark.asyncio
async def test_generate_sub_queries_legacy_path_unchanged(monkeypatch):
    """With dual_lane_query_planner=False the legacy path runs, Stage A is never called."""
    calls = []

    async def fake_create_chat_completion(**kwargs):
        calls.append("llm")
        return '["acme robotics funding", "acme robotics competitors"]'

    monkeypatch.setattr(query_processing, "create_chat_completion", fake_create_chat_completion)
    query_processing._TRANSLATED_QUERY_CACHE.clear()

    cfg = _dummy_cfg()  # dual_lane_query_planner=False
    sub_queries = await query_processing.generate_sub_queries(
        query="Company name: Acme; website: https://acme.ai",
        parent_query="",
        report_type="research_report",
        context=[],
        cfg=cfg,
    )

    assert sub_queries
    # Only one LLM call (the legacy planning call) — no Stage A
    assert calls == ["llm"]
