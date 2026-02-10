from bs4 import BeautifulSoup
import itertools
import os
from ..utils import get_relevant_images
from ...utils.api_keys import collect_api_keys

# Module-level state for round-robin key rotation
_firecrawl_state: dict = {"cycle": None, "keys": ()}


def _get_firecrawl_keys() -> list[str]:
    keys = collect_api_keys(
        primary_env_var="FIRECRAWL_API_KEY",
        fallback_env_var="FIRECRAWL_API_KEY_FALLBACK",
        list_env_var="FIRECRAWL_API_KEYS",
    )
    if not keys:
        raise Exception(
            "FireCrawl API key not found. Please set FIRECRAWL_API_KEY (or FIRECRAWL_API_KEYS)."
        )
    return keys


def _next_firecrawl_key() -> str:
    keys = _get_firecrawl_keys()
    keys_tuple = tuple(keys)
    if _firecrawl_state["cycle"] is None or _firecrawl_state["keys"] != keys_tuple:
        _firecrawl_state["cycle"] = itertools.cycle(keys)
        _firecrawl_state["keys"] = keys_tuple
    return next(_firecrawl_state["cycle"])


class FireCrawl:

    def __init__(self, link, session=None, api_key: str | None = None):
        self.link = link
        self.session = session
        self._api_key_override = (api_key or "").strip()
        from firecrawl import FirecrawlApp
        self.firecrawl = FirecrawlApp(api_key=self.get_api_key(), api_url=self.get_server_url())

    def get_api_key(self) -> str:
        """
        Gets the next FireCrawl API key from the rotation pool.
        FIRECRAWL_API_KEY may be a single key or a comma-separated list of keys.
        """
        if self._api_key_override:
            return self._api_key_override
        return _next_firecrawl_key()

    def get_server_url(self) -> str:
        """
        Gets the FireCrawl server URL.
        Default to official FireCrawl server ('https://api.firecrawl.dev').
        Returns:
        server url (str)
        """
        try:
            server_url = os.environ["FIRECRAWL_SERVER_URL"]
        except KeyError:
            server_url = 'https://api.firecrawl.dev'
        return server_url

    def scrape(self) -> tuple:
        """
        This function extracts content and title from a specified link using the FireCrawl Python SDK,
        images from the link are extracted using the functions from `gpt_researcher/scraper/utils.py`.

        Returns:
          The `scrape` method returns a tuple containing the extracted content, a list of image URLs, and
        the title of the webpage specified by the `self.link` attribute. It uses the FireCrawl Python SDK to
        extract and clean content from the webpage. If any exception occurs during the process, an error
        message is printed and an empty result is returned.
        """

        try:
            # Fixed: Changed from scrape_url() to scrape() to match FireCrawl SDK v4.6.0+
            response = self.firecrawl.scrape(url=self.link, formats=["markdown"])

            # Check if the page has been scraped successfully
            # Fixed: Access metadata attributes directly (not as dict keys)
            if response.metadata and response.metadata.error:
                print("Scrape failed! : " + str(response.metadata.error))
                return "", [], ""
            elif response.metadata and response.metadata.status_code and response.metadata.status_code != 200:
                print(f"Scrape failed! Status code: {response.metadata.status_code}")
                return "", [], ""

            # Extract the content (markdown) and title from FireCrawl response
            # Fixed: Access attributes directly (not as dict keys)
            content = response.markdown if response.markdown else ""
            title = response.metadata.title if response.metadata and response.metadata.title else ""

            # Parse the HTML content of the response to create a BeautifulSoup object for the utility functions
            response_bs = self.session.get(self.link, timeout=4)
            soup = BeautifulSoup(
                response_bs.content, "lxml", from_encoding=response_bs.encoding
            )

            # Get relevant images using the utility function
            image_urls = get_relevant_images(soup, self.link)

            return content, image_urls, title

        except Exception as e:
            print("Error! : " + str(e))
            return "", [], ""
