from gpt_researcher.prompts import PromptFamily
from gpt_researcher.utils.enum import ReportSource


def test_generate_search_queries_prompt_includes_entity_disambiguation_constraints():
    prompt = PromptFamily.generate_search_queries_prompt(
        question="公司名称：Unconventional AI；官网：https://unconv.ai/",
        parent_query="",
        report_type="research_report",
        max_iterations=3,
        context=[],
    )

    lowered = prompt.lower()
    assert "entity disambiguation constraints" in lowered
    assert "unconv.ai" in lowered


def test_generate_report_prompt_includes_unknown_instead_of_guessing_and_disambiguation():
    prompt = PromptFamily.generate_report_prompt(
        question="Company name: Unconventional AI; official website: https://unconv.ai/",
        context="sample context",
        report_source=ReportSource.Web.value,
    )

    lowered = prompt.lower()
    assert "entity disambiguation constraints" in lowered
    assert "unknown / needs verification" in lowered
