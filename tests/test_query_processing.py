from types import SimpleNamespace

import pytest

from gpt_researcher.actions import query_processing


def _dummy_cfg():
    return SimpleNamespace(
        max_iterations=3,
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
