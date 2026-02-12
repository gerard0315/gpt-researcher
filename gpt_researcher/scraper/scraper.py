import asyncio
from colorama import Fore, init

import requests
import subprocess
import sys
import importlib
import logging
import re
from collections.abc import Awaitable, Callable

from gpt_researcher.utils.api_keys import collect_api_keys
from gpt_researcher.utils.workers import WorkerPool

from . import (
    ArxivScraper,
    BeautifulSoupScraper,
    PyMuPDFScraper,
    WebBaseLoaderScraper,
    BrowserScraper,
    NoDriverScraper,
    TavilyExtract,
    FireCrawl,
    ScrapeDoScraper,
    FirecrawlScrapeDoRandom,
)


class Scraper:
    """
    Scraper class to extract the content from the links
    """
    _STATIC_SCRAPERS = {"bs", "web_base_loader"}
    _DYNAMIC_FALLBACK_MIN_CONTENT = 400
    _BLOCKED_CONTENT_MARKERS = (
        "enable javascript",
        "javascript is required",
        "javascript disabled",
        "please turn javascript on",
        "checking your browser",
        "just a moment",
        "verify you are human",
        "security check",
        "access denied",
        "captcha",
        "cloudflare",
    )
    _ERROR_CONTENT_MARKERS = (
        "traceback",
        "an error occurred",
        "please install",
        "no module named",
        "required to use nodriverscraper",
    )
    _NODRIVER_AVAILABLE = None
    _NODRIVER_MISSING_LOGGED = False
    _API_POOL_MISSING_LOGGED = False

    def __init__(
        self,
        urls,
        user_agent,
        scraper,
        worker_pool: WorkerPool,
        per_url_timeout: float | None = None,
        on_url_timeout: Callable[[str, float, str], Awaitable[None]] | None = None,
    ):
        """
        Initialize the Scraper class.
        Args:
            urls:
        """
        self.urls = urls
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.scraper = scraper
        if self.scraper in {"tavily_extract", "firecrawl", "nodriver"}:
            self._check_pkg(self.scraper)
        self.logger = logging.getLogger(__name__)
        self.worker_pool = worker_pool
        if per_url_timeout and per_url_timeout > 0:
            self.per_url_timeout = float(per_url_timeout)
        else:
            self.per_url_timeout = None
        self.on_url_timeout = on_url_timeout

    async def run(self):
        """
        Extracts the content from the links
        """
        contents = await asyncio.gather(
            *(self._extract_data_with_timeout(url, self.session) for url in self.urls)
        )

        res = [content for content in contents if content["raw_content"] is not None]
        return res

    async def _emit_timeout_event(self, link: str, timeout_seconds: float) -> None:
        if not self.on_url_timeout:
            return
        try:
            await self.on_url_timeout(link, timeout_seconds, self.scraper)
        except Exception as callback_error:
            self.logger.warning(
                f"Failed to emit scrape timeout callback for {link}: {callback_error}"
            )

    async def _extract_data_with_timeout(self, link, session):
        if not self.per_url_timeout:
            return await self.extract_data_from_url(link, session)

        try:
            return await asyncio.wait_for(
                self.extract_data_from_url(link, session),
                timeout=self.per_url_timeout,
            )
        except asyncio.TimeoutError:
            timeout_seconds = self.per_url_timeout
            self.logger.error(
                f"Scrape timeout after {timeout_seconds:.1f}s for {link} "
                f"(scraper={self.scraper})"
            )
            await self._emit_timeout_event(link, timeout_seconds)
            return {"url": link, "raw_content": None, "image_urls": [], "title": ""}

    def _check_pkg(self, scrapper_name: str) -> None:
        """
        Checks and ensures required Python packages are available for scrapers that need
        dependencies beyond requirements.txt. When adding a new scraper to the repo, update `pkg_map`
        with its required information and call check_pkg() during initialization.
        """
        pkg_map = {
            "tavily_extract": {
                "package_installation_name": "tavily-python",
                "import_name": "tavily",
            },
            "firecrawl": {
                "package_installation_name": "firecrawl-py",
                "import_name": "firecrawl",
            },
            "nodriver": {
                "package_installation_name": "zendriver",
                "import_name": "zendriver",
            },
        }
        pkg = pkg_map[scrapper_name]
        if not importlib.util.find_spec(pkg["import_name"]):
            pkg_inst_name = pkg["package_installation_name"]
            init(autoreset=True)
            print(Fore.YELLOW + f"{pkg_inst_name} not found. Attempting to install...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg_inst_name]
                )
                print(Fore.GREEN + f"{pkg_inst_name} installed successfully.")
            except subprocess.CalledProcessError:
                raise ImportError(
                    Fore.RED
                    + f"Unable to install {pkg_inst_name}. Please install manually with "
                    f"`pip install -U {pkg_inst_name}`"
                )

    @staticmethod
    def _normalize_text(value) -> str:
        if not value:
            return ""
        return re.sub(r"\s+", " ", str(value)).strip()

    def _looks_like_blocked_or_gate_page(self, content: str, title: str) -> bool:
        haystack = f"{self._normalize_text(title)} {self._normalize_text(content)}".lower()
        return any(marker in haystack for marker in self._BLOCKED_CONTENT_MARKERS)

    def _looks_like_error_content(self, content: str) -> bool:
        haystack = self._normalize_text(content).lower()
        return any(marker in haystack for marker in self._ERROR_CONTENT_MARKERS)

    def _should_try_dynamic_fallback(self, link: str, content: str, title: str) -> bool:
        if self.scraper not in self._STATIC_SCRAPERS:
            return False

        if link.endswith(".pdf") or "arxiv.org" in link:
            return False

        normalized = self._normalize_text(content)
        if not normalized:
            return True

        if self._looks_like_blocked_or_gate_page(normalized, title):
            return True

        return len(normalized) < self._DYNAMIC_FALLBACK_MIN_CONTENT

    def _is_fallback_content_better(
        self,
        primary_content: str,
        primary_title: str,
        fallback_content: str,
        fallback_title: str,
    ) -> bool:
        normalized_fallback = self._normalize_text(fallback_content)
        if not normalized_fallback:
            return False

        if self._looks_like_error_content(normalized_fallback):
            return False

        if self._looks_like_blocked_or_gate_page(normalized_fallback, fallback_title):
            return False

        normalized_primary = self._normalize_text(primary_content)
        if not normalized_primary:
            return len(normalized_fallback) >= 100

        if self._looks_like_blocked_or_gate_page(normalized_primary, primary_title):
            return len(normalized_fallback) >= 100

        return len(normalized_fallback) >= max(
            self._DYNAMIC_FALLBACK_MIN_CONTENT, int(len(normalized_primary) * 1.2)
        )

    async def _run_scraper(self, scraper):
        if hasattr(scraper, "scrape_async"):
            return await scraper.scrape_async()

        return await asyncio.get_running_loop().run_in_executor(
            self.worker_pool.executor, scraper.scrape
        )

    async def _run_dynamic_fallback(self, link: str, session):
        if Scraper._NODRIVER_AVAILABLE is None:
            Scraper._NODRIVER_AVAILABLE = (
                importlib.util.find_spec("zendriver") is not None
            )
        if not Scraper._NODRIVER_AVAILABLE:
            if not Scraper._NODRIVER_MISSING_LOGGED:
                self.logger.warning(
                    "NoDriver fallback is unavailable because zendriver is not installed. "
                    "Install it with `pip install zendriver` or set SCRAPER=nodriver."
                )
                Scraper._NODRIVER_MISSING_LOGGED = True
            return "", [], ""

        self.logger.info(f"Attempting NoDriver fallback for {link}")
        fallback_scraper = NoDriverScraper(link, session)
        return await self._run_scraper(fallback_scraper)

    async def _run_api_pool_fallback(self, link: str, session):
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
        firecrawl_available = importlib.util.find_spec("firecrawl") is not None
        has_firecrawl_slot = firecrawl_available and bool(firecrawl_keys)
        has_scrape_do_slot = bool(scrape_do_keys)

        if not (has_firecrawl_slot or has_scrape_do_slot):
            if not Scraper._API_POOL_MISSING_LOGGED:
                if firecrawl_keys and not firecrawl_available and not scrape_do_keys:
                    self.logger.info(
                        "Firecrawl fallback keys found but firecrawl-py is not installed, "
                        "and no ScrapeDo keys are configured."
                    )
                else:
                    self.logger.info(
                        "Pooled API fallback is unavailable because neither Firecrawl nor "
                        "ScrapeDo credentials are configured."
                    )
                Scraper._API_POOL_MISSING_LOGGED = True
            return "", [], ""

        self.logger.info(
            f"Attempting pooled API fallback (random Firecrawl/ScrapeDo) for {link}"
        )
        fallback_scraper = FirecrawlScrapeDoRandom(link, session)
        return await self._run_scraper(fallback_scraper)

    async def _run_fallback_chain(
        self,
        link: str,
        session,
        content: str,
        image_urls: list,
        title: str,
    ) -> tuple[str, list, str]:
        current_content = content
        current_image_urls = image_urls
        current_title = title

        fallback_attempts = [
            ("NoDriver", self._run_dynamic_fallback),
            ("ApiPool", self._run_api_pool_fallback),
        ]

        for fallback_name, fallback_runner in fallback_attempts:
            try:
                (
                    fallback_content,
                    fallback_image_urls,
                    fallback_title,
                ) = await fallback_runner(link, session)
            except Exception as fallback_error:
                self.logger.warning(
                    f"{fallback_name} fallback failed for {link}: {fallback_error}"
                )
                continue

            if self._is_fallback_content_better(
                current_content, current_title, fallback_content, fallback_title
            ):
                self.logger.info(f"Using {fallback_name} fallback content for {link}")
                current_content = fallback_content
                current_image_urls = fallback_image_urls
                current_title = fallback_title

            # Stop once we have robust, non-blocked content.
            if not self._should_try_dynamic_fallback(
                link, current_content, current_title
            ):
                break

        return current_content, current_image_urls, current_title

    async def extract_data_from_url(self, link, session):
        """
        Extracts the data from the link with logging
        """
        async with self.worker_pool.throttle():
            try:
                Scraper = self.get_scraper(link)
                scraper = Scraper(link, session)

                # Get scraper name
                scraper_name = scraper.__class__.__name__
                self.logger.info(f"\n=== Using {scraper_name} ===")

                # Get content
                content, image_urls, title = await self._run_scraper(scraper)

                if self._should_try_dynamic_fallback(link, content, title):
                    content, image_urls, title = await self._run_fallback_chain(
                        link, session, content, image_urls, title
                    )

                # Log results
                self.logger.info(f"\nTitle: {title}")
                self.logger.info(
                    f"Content length: {len(content) if content else 0} characters"
                )
                self.logger.info(f"Number of images: {len(image_urls)}")
                self.logger.info(f"URL: {link}")
                self.logger.info("=" * 50)

                if not content or len(content) < 100:
                    self.logger.warning(f"Content too short or empty for {link}")
                    return {
                        "url": link,
                        "raw_content": None,
                        "image_urls": [],
                        "title": title,
                    }

                return {
                    "url": link,
                    "raw_content": content,
                    "image_urls": image_urls,
                    "title": title,
                }

            except Exception as e:
                self.logger.error(f"Error processing {link}: {str(e)}")
                return {"url": link, "raw_content": None, "image_urls": [], "title": ""}

    def get_scraper(self, link):
        """
        The function `get_scraper` determines the appropriate scraper class based on the provided link
        or a default scraper if none matches.

        Args:
          link: The `get_scraper` method takes a `link` parameter which is a URL link to a webpage or a
        PDF file. Based on the type of content the link points to, the method determines the appropriate
        scraper class to use for extracting data from that content.

        Returns:
          The `get_scraper` method returns the scraper class based on the provided link. The method
        checks the link to determine the appropriate scraper class to use based on predefined mappings
        in the `SCRAPER_CLASSES` dictionary. If the link ends with ".pdf", it selects the
        `PyMuPDFScraper` class. If the link contains "arxiv.org", it selects the `ArxivScraper
        """

        SCRAPER_CLASSES = {
            "pdf": PyMuPDFScraper,
            "arxiv": ArxivScraper,
            "bs": BeautifulSoupScraper,
            "web_base_loader": WebBaseLoaderScraper,
            "browser": BrowserScraper,
            "nodriver": NoDriverScraper,
            "tavily_extract": TavilyExtract,
            "firecrawl": FireCrawl,
            "scrape_do": ScrapeDoScraper,
            "firecrawl_scrape_do_random": FirecrawlScrapeDoRandom,
        }

        scraper_key = None

        if link.endswith(".pdf"):
            scraper_key = "pdf"
        elif "arxiv.org" in link:
            scraper_key = "arxiv"
        else:
            scraper_key = self.scraper

        scraper_class = SCRAPER_CLASSES.get(scraper_key)
        if scraper_class is None:
            raise Exception("Scraper not found.")

        return scraper_class
