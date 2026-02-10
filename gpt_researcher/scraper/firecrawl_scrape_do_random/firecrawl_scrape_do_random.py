import importlib.util
import random

from ...utils.api_keys import collect_api_keys, mask_api_key
from ..firecrawl.firecrawl import FireCrawl
from ..scrape_do.scrape_do import ScrapeDoScraper


class FirecrawlScrapeDoRandom:
    """
    Scraper pool that randomly distributes each request across:
    - Firecrawl key slots (each key is one slot)
    - Scrape.do key slots (each key is one slot)

    Example:
    - 2 Firecrawl keys + 1 Scrape.do key => 3 random slots per request.
    """

    def __init__(self, link, session=None):
        self.link = link
        self.session = session
        self._pool = self._build_provider_pool()

    @staticmethod
    def _build_provider_pool() -> list[tuple[str, str]]:
        firecrawl_keys = collect_api_keys(
            primary_env_var="FIRECRAWL_API_KEY",
            fallback_env_var="FIRECRAWL_API_KEY_FALLBACK",
            list_env_var="FIRECRAWL_API_KEYS",
        )
        scrape_do_keys = collect_api_keys(
            primary_env_var="SCRAPE_DO_API_KEY",
            fallback_env_var="SCRAPE_DO_API_KEY_FALLBACK",
            list_env_var="SCRAPE_DO_API_KEYS",
        )

        provider_pool: list[tuple[str, str]] = []
        firecrawl_available = importlib.util.find_spec("firecrawl") is not None
        if firecrawl_available:
            provider_pool.extend([("firecrawl", key) for key in firecrawl_keys])
        elif firecrawl_keys:
            print(
                "firecrawl-py is not installed; skipping Firecrawl keys in "
                "firecrawl_scrape_do_random pool."
            )
        provider_pool.extend([("scrape_do", key) for key in scrape_do_keys])

        if not provider_pool:
            raise Exception(
                "No API keys found for pooled scraper. Set FIRECRAWL_API_KEY/FIRECRAWL_API_KEYS "
                "and/or SCRAPE_DO_API_KEY/SCRAPE_DO_API_KEYS."
            )
        return provider_pool

    def _build_scraper(self, provider: str, api_key: str):
        if provider == "firecrawl":
            return FireCrawl(self.link, self.session, api_key=api_key)
        if provider == "scrape_do":
            return ScrapeDoScraper(self.link, self.session, api_keys=[api_key])
        raise ValueError(f"Unsupported provider in pool: {provider}")

    def scrape(self) -> tuple:
        attempts = list(self._pool)
        random.shuffle(attempts)
        last_error = None

        for provider, api_key in attempts:
            try:
                scraper = self._build_scraper(provider, api_key)
                content, image_urls, title = scraper.scrape()
                if content:
                    return content, image_urls, title
                print(
                    f"{provider} slot {mask_api_key(api_key)} returned empty content, trying next slot..."
                )
            except Exception as exc:
                last_error = exc
                print(
                    f"{provider} slot {mask_api_key(api_key)} failed: {exc}. Trying next slot..."
                )

        if last_error is not None:
            print(f"Error! : {last_error}")
        return "", [], ""
