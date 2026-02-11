# Tavily API Retriever

# libraries
from typing import Literal, Sequence
import requests
import json
from ...utils.api_keys import collect_api_keys, is_probable_quota_or_auth_error, mask_api_key


class TavilySearch:
    """
    Tavily API Retriever
    """
    # Class-level counter to round-robin starting key across instances
    _round_robin_counter = 0

    def __init__(self, query, headers=None, topic="general", query_domains=None):
        """
        Initializes the TavilySearch object.

        Args:
            query (str): The search query string.
            headers (dict, optional): Additional headers to include in the request. Defaults to None.
            topic (str, optional): The topic for the search. Defaults to "general".
            query_domains (list, optional): List of domains to include in the search. Defaults to None.
        """
        self.query = query
        self.headers = headers or {}
        self.topic = topic
        self.base_url = "https://api.tavily.com/search"
        self.api_keys = self.get_api_keys()
        if self.api_keys:
            start_index = self.__class__._round_robin_counter % len(self.api_keys)
            self.__class__._round_robin_counter += 1
            self.api_keys = self.api_keys[start_index:] + self.api_keys[:start_index]
            self.api_key = self.api_keys[0]
        else:
            self.api_key = ""
        self.headers = {
            "Content-Type": "application/json",
        }
        self.query_domains = query_domains or None

    def get_api_keys(self):
        """
        Gets Tavily API keys (primary + optional fallback/list keys).
        Returns:

        """
        header_key = self.headers.get("tavily_api_key", "").strip()
        api_keys = collect_api_keys(
            primary_env_var="TAVILY_API_KEY",
            fallback_env_var="TAVILY_API_KEY_FALLBACK",
            list_env_var="TAVILY_API_KEYS",
            explicit_keys=[header_key] if header_key else None,
        )
        if not api_keys:
            print(
                "Tavily API key not found, set to blank. If you need a retriver, please set the TAVILY_API_KEY environment variable."
            )
        return api_keys


    def _search(
        self,
        query: str,
        search_depth: Literal["basic", "advanced"] = "basic",
        topic: str = "general",
        days: int = 2,
        max_results: int = 10,
        include_domains: Sequence[str] = None,
        exclude_domains: Sequence[str] = None,
        include_answer: bool = False,
        include_raw_content: bool = False,
        include_images: bool = False,
        use_cache: bool = True,
        api_key: str = "",
    ) -> dict:
        """
        Internal search method to send the request to the API.
        """

        data = {
            "query": query,
            "search_depth": search_depth,
            "topic": topic,
            "days": days,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
            "max_results": max_results,
            "include_domains": include_domains,
            "exclude_domains": exclude_domains,
            "include_images": include_images,
            "api_key": api_key or self.api_key,
            "use_cache": use_cache,
        }

        response = requests.post(
            self.base_url, data=json.dumps(data), headers=self.headers, timeout=100
        )

        if response.status_code == 200:
            return response.json()
        else:
            # Raises a HTTPError if the HTTP request returned an unsuccessful status code
            response.raise_for_status()

    def search(self, max_results=10):
        """
        Searches the query
        Returns:

        """
        if not self.api_keys:
            return []

        last_error = None
        for index, api_key in enumerate(self.api_keys):
            try:
                results = self._search(
                    self.query,
                    search_depth="basic",
                    max_results=max_results,
                    topic=self.topic,
                    include_domains=self.query_domains,
                    api_key=api_key,
                )
                sources = results.get("results", [])
                if not sources:
                    raise Exception("No results found with Tavily API search.")
                return [{"href": obj["url"], "body": obj["content"]} for obj in sources]
            except requests.HTTPError as e:
                last_error = e
                masked = mask_api_key(api_key)
                status_code = e.response.status_code if e.response is not None else None
                print(f"Tavily key {masked} failed (HTTP {status_code}): {e}")
                can_retry_with_next_key = (
                    index < len(self.api_keys) - 1 and
                    (
                        status_code in {401, 403, 429} or
                        is_probable_quota_or_auth_error(str(e))
                    )
                )
                if can_retry_with_next_key:
                    print(f"Trying next Tavily key ({index + 2}/{len(self.api_keys)})...")
                    continue
                break
            except Exception as e:
                last_error = e
                masked = mask_api_key(api_key)
                print(f"Tavily key {masked} failed: {e}")
                can_retry_with_next_key = (
                    index < len(self.api_keys) - 1 and
                    is_probable_quota_or_auth_error(str(e))
                )
                if can_retry_with_next_key:
                    print(f"Trying next Tavily key ({index + 2}/{len(self.api_keys)})...")
                    continue
                break

        print(f"Error: All {len(self.api_keys)} Tavily key(s) failed. Last error: {last_error}")
        return []
