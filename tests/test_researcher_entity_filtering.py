from types import SimpleNamespace

from gpt_researcher.skills.researcher import ResearchConductor


def _build_conductor(query: str) -> ResearchConductor:
    dummy_researcher = SimpleNamespace(query=query)
    return ResearchConductor(dummy_researcher)


def test_filter_results_keeps_subject_aligned_external_and_canonical_sources():
    query = "Company name: Unconventional AI; official website: https://unconv.ai/"
    conductor = _build_conductor(query)

    results = [
        {"href": "https://unconv.ai/introducing-unconventional-ai/", "body": "Official founders post"},
        {
            "href": "https://techfundingnews.com/former-databricks-ai-chiefs-unconventional-ai-raises-475m-at-4-5b-valuation-to-redesign-computing/",
            "body": "Unconventional AI raises $475M at $4.5B valuation",
        },
        {"href": "https://www.fim-moto.com/en/", "body": "Motorcycle federation homepage"},
        {"href": "https://www.3cat.cat/", "body": "Catalan streaming service"},
    ]

    filtered, metadata = conductor._filter_results_for_primary_subject(query, results)
    kept_urls = [item.get("href") for item in filtered]

    assert "https://unconv.ai/introducing-unconventional-ai/" in kept_urls
    assert any("techfundingnews.com" in (url or "") for url in kept_urls)
    assert all("fim-moto.com" not in (url or "") for url in kept_urls)
    assert all("3cat.cat" not in (url or "") for url in kept_urls)
    assert metadata["kept_count"] >= 2
    assert metadata["dropped_count"] >= 1


def test_filter_results_respects_site_domain_constraint():
    query = '("Unconventional AI" OR "unconv.ai") site:unconv.ai (official OR about OR team)'
    conductor = _build_conductor(query)

    results = [
        {"href": "https://unconv.ai/", "body": "Unconventional AI official site"},
        {
            "href": "https://techfundingnews.com/former-databricks-ai-chiefs-unconventional-ai-raises-475m-at-4-5b-valuation-to-redesign-computing/",
            "body": "External article mentioning Unconventional AI",
        },
    ]

    filtered, _ = conductor._filter_results_for_primary_subject(query, results)
    kept_urls = [item.get("href") for item in filtered]

    assert "https://unconv.ai/" in kept_urls
    assert all("techfundingnews.com" not in (url or "") for url in kept_urls)
