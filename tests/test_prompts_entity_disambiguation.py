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


# ---------------------------------------------------------------------------
# Stage A prompt
# ---------------------------------------------------------------------------

def test_generate_subject_concept_analysis_prompt_requests_concept_terms():
    prompt = PromptFamily.generate_subject_concept_analysis_prompt(
        query="Company name: Unconventional AI; website: https://unconv.ai/",
        parent_query="",
        report_type="research_report",
    )

    lowered = prompt.lower()
    assert "concept_terms" in lowered
    assert "intention" in lowered
    assert "recommended_lane_budget" in lowered


def test_generate_subject_concept_analysis_prompt_includes_report_type():
    prompt = PromptFamily.generate_subject_concept_analysis_prompt(
        query="Some query",
        parent_query="",
        report_type="due_diligence_report",
    )

    assert "due_diligence_report" in prompt


def test_generate_subject_concept_analysis_prompt_combines_parent_and_query():
    prompt = PromptFamily.generate_subject_concept_analysis_prompt(
        query="What is their moat?",
        parent_query="Unconventional AI research",
        report_type="research_report",
    )

    assert "Unconventional AI research" in prompt
    assert "What is their moat?" in prompt


# ---------------------------------------------------------------------------
# Stage B prompt
# ---------------------------------------------------------------------------

def test_generate_lane_search_queries_prompt_has_three_lane_keys():
    analysis = {
        "intention": "due_diligence",
        "subject_summary": "Unconventional AI",
        "concept_terms": {"industry": ["neuromorphic", "ai hardware"], "regulation": ["export controls"]},
        "recommended_lane_budget": {"subject": 40, "concept": 40, "intersection": 20},
    }
    lane_budget = {"subject": 2, "concept": 2, "intersection": 1}

    prompt = PromptFamily.generate_lane_search_queries_prompt(
        query="Company name: Unconventional AI; website: https://unconv.ai/",
        parent_query="",
        report_type="research_report",
        analysis=analysis,
        lane_budget=lane_budget,
        context=[],
    )

    lowered = prompt.lower()
    assert "subject_queries" in lowered
    assert "concept_queries" in lowered
    assert "intersection_queries" in lowered


def test_generate_lane_search_queries_prompt_concept_lane_not_entity_required():
    """Concept lane instructions must explicitly state entity name is NOT required."""
    analysis = {
        "intention": "due_diligence",
        "subject_summary": "Unconventional AI",
        "concept_terms": {"industry": ["neuromorphic"]},
        "recommended_lane_budget": {},
    }
    lane_budget = {"subject": 1, "concept": 1, "intersection": 1}

    prompt = PromptFamily.generate_lane_search_queries_prompt(
        query="Company name: Unconventional AI; website: https://unconv.ai/",
        parent_query="",
        report_type="research_report",
        analysis=analysis,
        lane_budget=lane_budget,
    )

    lowered = prompt.lower()
    # Concept lane must say entity is NOT required
    assert "do not require" in lowered or "not require" in lowered or "not about the specific entity" in lowered


def test_generate_lane_search_queries_prompt_subject_lane_requires_entity():
    """Subject lane instructions must state entity identifier is required."""
    analysis = {
        "intention": "general",
        "subject_summary": "Acme Robotics",
        "concept_terms": {},
        "recommended_lane_budget": {},
    }
    lane_budget = {"subject": 2, "concept": 1, "intersection": 0}

    prompt = PromptFamily.generate_lane_search_queries_prompt(
        query="Company name: Acme Robotics; website: https://acme.ai",
        parent_query="",
        report_type="research_report",
        analysis=analysis,
        lane_budget=lane_budget,
    )

    lowered = prompt.lower()
    assert "must include" in lowered or "include the entity" in lowered


def test_generate_lane_search_queries_prompt_includes_entity_disambiguation():
    """Stage B prompt must include entity disambiguation constraints for the subject entity."""
    analysis = {
        "intention": "due_diligence",
        "subject_summary": "Unconventional AI",
        "concept_terms": {},
        "recommended_lane_budget": {},
    }

    prompt = PromptFamily.generate_lane_search_queries_prompt(
        query="Company name: Unconventional AI; website: https://unconv.ai/",
        parent_query="",
        report_type="research_report",
        analysis=analysis,
        lane_budget={"subject": 1, "concept": 1, "intersection": 1},
    )

    lowered = prompt.lower()
    assert "entity disambiguation constraints" in lowered
    assert "unconv.ai" in lowered


def test_generate_lane_search_queries_prompt_concept_terms_appear_in_prompt():
    analysis = {
        "intention": "technology_research",
        "subject_summary": "Unconventional AI",
        "concept_terms": {"industry": ["neuromorphic", "ai hardware"], "regulation": ["export controls"]},
        "recommended_lane_budget": {},
    }

    prompt = PromptFamily.generate_lane_search_queries_prompt(
        query="Company name: Unconventional AI; website: https://unconv.ai/",
        parent_query="",
        report_type="research_report",
        analysis=analysis,
        lane_budget={"subject": 1, "concept": 2, "intersection": 1},
    )

    assert "neuromorphic" in prompt
    assert "ai hardware" in prompt
