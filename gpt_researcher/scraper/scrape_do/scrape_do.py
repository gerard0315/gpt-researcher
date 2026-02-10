import os
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests

from ...utils.api_keys import (
    collect_api_keys,
    is_probable_quota_or_auth_error,
    mask_api_key,
)
from ..utils import extract_title, get_relevant_images


class ScrapeDoScraper:
    """
    Scrape.do API scraper.

    Docs: https://scrape.do/documentation/
    Endpoint pattern: https://api.scrape.do/?token=...&url=...
    """

    def __init__(self, link, session=None, api_keys: list[str] | None = None):
        self.link = link
        self.session = session or requests.Session()
        self.api_keys = self.get_api_keys(api_keys)
        self.api_url = os.getenv("SCRAPE_DO_API_URL", "https://api.scrape.do/").strip()
        self.output = os.getenv("SCRAPE_DO_OUTPUT", "markdown").strip() or "markdown"
        self.timeout = self._read_timeout()
        self.render = self._read_bool("SCRAPE_DO_RENDER", default=False)
        self.super_mode = self._read_bool("SCRAPE_DO_SUPER", default=False)
        self.geo_code = os.getenv("SCRAPE_DO_GEO_CODE", "").strip()

    @staticmethod
    def _read_bool(env_name: str, default: bool = False) -> bool:
        raw = os.getenv(env_name, str(default)).strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _read_timeout() -> int:
        raw = os.getenv("SCRAPE_DO_TIMEOUT", "40").strip()
        try:
            timeout = int(raw)
            return timeout if timeout > 0 else 40
        except ValueError:
            return 40

    def get_api_keys(self, explicit_keys: list[str] | None = None) -> list[str]:
        api_keys = collect_api_keys(
            primary_env_var="SCRAPE_DO_API_KEY",
            fallback_env_var="SCRAPE_DO_API_KEY_FALLBACK",
            list_env_var="SCRAPE_DO_API_KEYS",
            explicit_keys=explicit_keys,
        )
        if not api_keys:
            raise Exception(
                "Scrape.do API key not found. Please set the SCRAPE_DO_API_KEY environment variable."
            )
        return api_keys

    def _build_params(self, api_key: str) -> dict:
        params = {
            "token": api_key,
            "url": self.link,
            "output": self.output,
        }
        if self.render:
            params["render"] = "true"
        if self.super_mode:
            params["super"] = "true"
        if self.geo_code:
            params["geoCode"] = self.geo_code
        return params

    def _extract_title_and_images(self, content: str) -> tuple[str, list[dict]]:
        if not content:
            return "", []

        stripped = content.lstrip()
        if stripped.startswith("<"):
            soup = BeautifulSoup(content, "lxml")
            title = extract_title(soup)
            images = get_relevant_images(soup, self.link)
            return title, images

        title = ""
        for line in content.splitlines():
            normalized = line.strip()
            if normalized.startswith("#"):
                title = normalized.lstrip("#").strip()
                if title:
                    break

        image_urls: list[dict] = []
        for image_url in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", content):
            absolute_url = urljoin(self.link, image_url.strip())
            if absolute_url.startswith(("http://", "https://")):
                image_urls.append({"url": absolute_url, "score": 1})

        if not title:
            for line in content.splitlines():
                normalized = line.strip()
                if normalized:
                    title = normalized[:120]
                    break

        return title, image_urls[:10]

    def scrape(self) -> tuple:
        last_error = None
        for index, api_key in enumerate(self.api_keys):
            try:
                response = self.session.get(
                    self.api_url,
                    params=self._build_params(api_key),
                    timeout=self.timeout,
                )
                response.raise_for_status()

                content = (response.text or "").strip()
                if not content:
                    return "", [], ""

                title, image_urls = self._extract_title_and_images(content)
                return content, image_urls, title
            except requests.HTTPError as exc:
                last_error = exc
                status_code = exc.response.status_code if exc.response is not None else None
                masked = mask_api_key(api_key)
                print(f"Scrape.do key {masked} failed (HTTP {status_code}): {exc}")
                can_retry_with_next_key = (
                    index < len(self.api_keys) - 1
                    and (
                        status_code in {401, 403, 429}
                        or is_probable_quota_or_auth_error(str(exc))
                    )
                )
                if can_retry_with_next_key:
                    print(
                        f"Trying next Scrape.do key ({index + 2}/{len(self.api_keys)})..."
                    )
                    continue
                break
            except Exception as exc:
                last_error = exc
                masked = mask_api_key(api_key)
                print(f"Scrape.do key {masked} failed: {exc}")
                can_retry_with_next_key = (
                    index < len(self.api_keys) - 1
                    and is_probable_quota_or_auth_error(str(exc))
                )
                if can_retry_with_next_key:
                    print(
                        f"Trying next Scrape.do key ({index + 2}/{len(self.api_keys)})..."
                    )
                    continue
                break

        print(f"Error! : {last_error}")
        return "", [], ""
