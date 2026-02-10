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
    )


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
