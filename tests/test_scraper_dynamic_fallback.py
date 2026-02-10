import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import types
import pytest

# Avoid importing gpt_researcher/__init__.py in tests, which pulls optional heavy deps.
if "gpt_researcher" not in sys.modules:
    pkg = types.ModuleType("gpt_researcher")
    pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "gpt_researcher")]
    sys.modules["gpt_researcher"] = pkg

if "langchain_community" not in sys.modules:
    langchain_community = types.ModuleType("langchain_community")
    retrievers = types.ModuleType("langchain_community.retrievers")
    document_loaders = types.ModuleType("langchain_community.document_loaders")

    class _DummyArxivRetriever:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, *args, **kwargs):
            return []

    class _DummyPyMuPDFLoader:
        def __init__(self, *args, **kwargs):
            pass

        def load(self):
            return []

    retrievers.ArxivRetriever = _DummyArxivRetriever
    document_loaders.PyMuPDFLoader = _DummyPyMuPDFLoader

    langchain_community.retrievers = retrievers
    langchain_community.document_loaders = document_loaders

    sys.modules["langchain_community"] = langchain_community
    sys.modules["langchain_community.retrievers"] = retrievers
    sys.modules["langchain_community.document_loaders"] = document_loaders

from gpt_researcher.scraper.scraper import Scraper


class DummyWorkerPool:
    executor = None

    @asynccontextmanager
    async def throttle(self):
        yield


class FakePrimaryScraper:
    def __init__(self, link, session):
        self.link = link
        self.session = session

    def scrape(self):
        return "", [], ""


def build_scraper(scraper_name: str = "bs") -> Scraper:
    return Scraper(
        urls=[],
        user_agent="test-agent",
        scraper=scraper_name,
        worker_pool=DummyWorkerPool(),
    )


def test_dynamic_fallback_replaces_blocked_static_content(monkeypatch):
    scraper = build_scraper("bs")
    static_content = "Just a moment... please verify you are human to continue."
    fallback_content = "Unconv builds AI-ready, schema-safe data extraction workflows. " * 8

    monkeypatch.setattr(scraper, "get_scraper", lambda _: FakePrimaryScraper)
    monkeypatch.setattr(
        FakePrimaryScraper,
        "scrape",
        lambda self: (static_content, [], "Just a moment"),
    )

    async def fake_dynamic_fallback(link, session):
        return fallback_content, [{"url": "https://example.com/img.png", "score": 1}], "Unconv"

    monkeypatch.setattr(scraper, "_run_dynamic_fallback", fake_dynamic_fallback)

    result = asyncio.run(
        scraper.extract_data_from_url("https://example.com", scraper.session)
    )

    assert result["raw_content"] == fallback_content
    assert result["title"] == "Unconv"
    assert result["image_urls"] == [{"url": "https://example.com/img.png", "score": 1}]


def test_dynamic_fallback_not_called_for_good_static_content(monkeypatch):
    scraper = build_scraper("bs")
    static_content = "Detailed static content. " * 40  # > 400 chars

    monkeypatch.setattr(scraper, "get_scraper", lambda _: FakePrimaryScraper)
    monkeypatch.setattr(
        FakePrimaryScraper,
        "scrape",
        lambda self: (static_content, [], "Good page"),
    )

    async def fail_if_called(link, session):
        raise AssertionError("Dynamic fallback should not run for high-quality static content")

    monkeypatch.setattr(scraper, "_run_dynamic_fallback", fail_if_called)

    result = asyncio.run(
        scraper.extract_data_from_url("https://example.com", scraper.session)
    )

    assert result["raw_content"] == static_content
    assert result["title"] == "Good page"


def test_dynamic_fallback_rejected_when_it_looks_like_error(monkeypatch):
    scraper = build_scraper("bs")
    static_content = "Static snapshot with limited details. " * 8
    fallback_error_text = (
        "The zendriver package is required to use NoDriverScraper. "
        "Please install it with: pip install zendriver"
    )

    monkeypatch.setattr(scraper, "get_scraper", lambda _: FakePrimaryScraper)
    monkeypatch.setattr(
        FakePrimaryScraper,
        "scrape",
        lambda self: (static_content, [], "Thin page"),
    )

    async def fake_dynamic_fallback(link, session):
        return fallback_error_text, [], ""

    monkeypatch.setattr(scraper, "_run_dynamic_fallback", fake_dynamic_fallback)

    result = asyncio.run(
        scraper.extract_data_from_url("https://example.com", scraper.session)
    )

    assert result["raw_content"] == static_content
    assert result["title"] == "Thin page"


@pytest.mark.parametrize(
    "url",
    [
        "https://unconv.ai/",
        "https://www.notion.so/",
        "https://www.framer.com/",
    ],
)
def test_dynamic_fallback_for_related_js_heavy_domains(monkeypatch, url):
    scraper = build_scraper("bs")
    static_content = "Enable JavaScript to continue."
    fallback_content = "Loaded rendered content with product details and documentation text. " * 10

    monkeypatch.setattr(scraper, "get_scraper", lambda _: FakePrimaryScraper)
    monkeypatch.setattr(
        FakePrimaryScraper,
        "scrape",
        lambda self: (static_content, [], "Access page"),
    )

    called = {"count": 0}

    async def fake_dynamic_fallback(link, session):
        called["count"] += 1
        return fallback_content, [], "Rendered page"

    monkeypatch.setattr(scraper, "_run_dynamic_fallback", fake_dynamic_fallback)

    result = asyncio.run(scraper.extract_data_from_url(url, scraper.session))

    assert called["count"] == 1
    assert result["raw_content"] == fallback_content
    assert result["title"] == "Rendered page"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/report.pdf",
        "https://arxiv.org/abs/2401.00001",
    ],
)
def test_dynamic_fallback_is_not_used_for_pdf_or_arxiv(monkeypatch, url):
    scraper = build_scraper("bs")
    static_content = "Static content from non-web-html source that is already long enough. " * 3

    monkeypatch.setattr(scraper, "get_scraper", lambda _: FakePrimaryScraper)
    monkeypatch.setattr(
        FakePrimaryScraper,
        "scrape",
        lambda self: (static_content, [], "Document"),
    )

    async def fail_if_called(link, session):
        raise AssertionError("Dynamic fallback must not run for PDF/arXiv links")

    monkeypatch.setattr(scraper, "_run_dynamic_fallback", fail_if_called)

    result = asyncio.run(scraper.extract_data_from_url(url, scraper.session))

    assert result["raw_content"] == static_content
    assert result["title"] == "Document"
