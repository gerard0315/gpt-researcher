import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import requests

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

from gpt_researcher.scraper.scrape_do.scrape_do import ScrapeDoScraper
from gpt_researcher.scraper.firecrawl_scrape_do_random.firecrawl_scrape_do_random import (
    FirecrawlScrapeDoRandom,
)
import gpt_researcher.scraper.firecrawl_scrape_do_random.firecrawl_scrape_do_random as pool_module
from gpt_researcher.scraper.scraper import Scraper


class DummyWorkerPool:
    executor = None

    @asynccontextmanager
    async def throttle(self):
        yield


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "params": dict(params or {}),
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


def test_scrape_do_scrape_parses_markdown(monkeypatch):
    monkeypatch.setenv("SCRAPE_DO_API_KEY", "key-primary")
    monkeypatch.delenv("SCRAPE_DO_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("SCRAPE_DO_API_KEYS", raising=False)
    monkeypatch.setenv("SCRAPE_DO_OUTPUT", "markdown")

    session = FakeSession(
        [
            FakeResponse(
                200,
                "# Example Title\n\nBody text.\n\n![diagram](https://example.com/image.png)\n",
            )
        ]
    )

    scraper = ScrapeDoScraper("https://example.com/article", session=session)
    content, image_urls, title = scraper.scrape()

    assert "Body text." in content
    assert title == "Example Title"
    assert image_urls == [{"url": "https://example.com/image.png", "score": 1}]

    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == "https://api.scrape.do/"
    assert call["params"]["token"] == "key-primary"
    assert call["params"]["url"] == "https://example.com/article"
    assert call["params"]["output"] == "markdown"


def test_scrape_do_retries_with_fallback_key_on_429(monkeypatch):
    monkeypatch.setenv("SCRAPE_DO_API_KEY", "key-primary")
    monkeypatch.setenv("SCRAPE_DO_API_KEY_FALLBACK", "key-fallback")
    monkeypatch.delenv("SCRAPE_DO_API_KEYS", raising=False)

    session = FakeSession(
        [
            FakeResponse(429, "rate limited"),
            FakeResponse(200, "# Title\nfinal content"),
        ]
    )

    scraper = ScrapeDoScraper("https://example.com/article", session=session)
    content, _, title = scraper.scrape()

    assert title == "Title"
    assert "final content" in content
    assert len(session.calls) == 2
    assert session.calls[0]["params"]["token"] == "key-primary"
    assert session.calls[1]["params"]["token"] == "key-fallback"


def test_scraper_factory_routes_scrape_do():
    scraper = Scraper(
        urls=[],
        user_agent="test-agent",
        scraper="scrape_do",
        worker_pool=DummyWorkerPool(),
    )
    scraper_class = scraper.get_scraper("https://example.com")
    assert scraper_class is ScrapeDoScraper


def test_firecrawl_scrape_do_random_builds_provider_slots(monkeypatch):
    monkeypatch.setattr(
        pool_module.importlib.util,
        "find_spec",
        lambda name: object() if name == "firecrawl" else None,
    )
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key-1,fc-key-2")
    monkeypatch.delenv("FIRECRAWL_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEYS", raising=False)
    monkeypatch.setenv("SCRAPE_DO_API_KEY", "sd-key-1")
    monkeypatch.delenv("SCRAPE_DO_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("SCRAPE_DO_API_KEYS", raising=False)

    scraper = FirecrawlScrapeDoRandom("https://example.com")
    assert sorted(scraper._pool) == [
        ("firecrawl", "fc-key-1"),
        ("firecrawl", "fc-key-2"),
        ("scrape_do", "sd-key-1"),
    ]


def test_firecrawl_scrape_do_random_tries_next_slot_when_empty(monkeypatch):
    monkeypatch.setattr(
        pool_module.importlib.util,
        "find_spec",
        lambda name: object() if name == "firecrawl" else None,
    )
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key-1")
    monkeypatch.delenv("FIRECRAWL_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEYS", raising=False)
    monkeypatch.setenv("SCRAPE_DO_API_KEY", "sd-key-1")
    monkeypatch.delenv("SCRAPE_DO_API_KEY_FALLBACK", raising=False)
    monkeypatch.delenv("SCRAPE_DO_API_KEYS", raising=False)

    calls = []

    class FakeFirecrawl:
        def __init__(self, link, session=None, api_key=None):
            calls.append(("firecrawl_init", api_key))

        def scrape(self):
            calls.append(("firecrawl_scrape", None))
            return "", [], ""

    class FakeScrapeDo:
        def __init__(self, link, session=None, api_keys=None):
            calls.append(("scrape_do_init", api_keys[0]))

        def scrape(self):
            calls.append(("scrape_do_scrape", None))
            return "pooled content", [], "Pooled Title"

    monkeypatch.setattr(pool_module, "FireCrawl", FakeFirecrawl)
    monkeypatch.setattr(pool_module, "ScrapeDoScraper", FakeScrapeDo)
    monkeypatch.setattr(pool_module.random, "shuffle", lambda items: None)

    scraper = FirecrawlScrapeDoRandom("https://example.com")
    content, _, title = scraper.scrape()
    assert content == "pooled content"
    assert title == "Pooled Title"
    assert calls == [
        ("firecrawl_init", "fc-key-1"),
        ("firecrawl_scrape", None),
        ("scrape_do_init", "sd-key-1"),
        ("scrape_do_scrape", None),
    ]


def test_scraper_factory_routes_firecrawl_scrape_do_random():
    scraper = Scraper(
        urls=[],
        user_agent="test-agent",
        scraper="firecrawl_scrape_do_random",
        worker_pool=DummyWorkerPool(),
    )
    scraper_class = scraper.get_scraper("https://example.com")
    assert scraper_class is FirecrawlScrapeDoRandom
