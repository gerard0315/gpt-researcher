from bs4 import BeautifulSoup
from ..utils import get_relevant_images, extract_title
from ...utils.api_keys import collect_api_keys, is_probable_quota_or_auth_error

class TavilyExtract:
    # Class-level counter to distribute usage across keys
    _round_robin_counter = 0

    def __init__(self, link, session=None):
        self.link = link
        self.session = session
        self.api_keys = self.get_api_keys()
        start_index = self.__class__._round_robin_counter % len(self.api_keys)
        self.__class__._round_robin_counter += 1
        self.api_keys = self.api_keys[start_index:] + self.api_keys[:start_index]

    def get_api_keys(self) -> list[str]:
        """
        Gets Tavily API keys (primary + optional fallback/list keys).
        Returns:
        API keys (list[str])
        """
        api_keys = collect_api_keys(
            primary_env_var="TAVILY_API_KEY",
            fallback_env_var="TAVILY_API_KEY_FALLBACK",
            list_env_var="TAVILY_API_KEYS",
        )
        if not api_keys:
            raise Exception(
                "Tavily API key not found. Please set the TAVILY_API_KEY environment variable.")
        return api_keys

    def scrape(self) -> tuple:
        """
        This function extracts content from a specified link using the Tavily Python SDK, the title and
        images from the link are extracted using the functions from `gpt_researcher/scraper/utils.py`.

        Returns:
          The `scrape` method returns a tuple containing the extracted content, a list of image URLs, and
        the title of the webpage specified by the `self.link` attribute. It uses the Tavily Python SDK to
        extract and clean content from the webpage. If any exception occurs during the process, an error
        message is printed and an empty result is returned.
        """
        from tavily import TavilyClient

        last_error = None
        for index, api_key in enumerate(self.api_keys):
            try:
                tavily_client = TavilyClient(api_key=api_key)
                response = tavily_client.extract(urls=self.link)
                if response['failed_results']:
                    return "", [], ""

                # Parse the HTML content of the response to create a BeautifulSoup object for the utility functions
                response_bs = self.session.get(self.link, timeout=4)
                soup = BeautifulSoup(
                    response_bs.content, "lxml", from_encoding=response_bs.encoding
                )

                # Since only a single link is provided to tavily_client, the results will contain only one entry.
                content = response['results'][0]['raw_content']

                # Get relevant images using the utility function
                image_urls = get_relevant_images(soup, self.link)

                # Extract the title using the utility function
                title = extract_title(soup)

                return content, image_urls, title
            except Exception as e:
                last_error = e
                can_retry_with_next_key = (
                    index < len(self.api_keys) - 1 and
                    is_probable_quota_or_auth_error(str(e))
                )
                if can_retry_with_next_key:
                    print("Tavily key appears exhausted/unauthorized. Trying fallback key...")
                    continue
                break

        print("Error! : " + str(last_error))
        return "", [], ""
