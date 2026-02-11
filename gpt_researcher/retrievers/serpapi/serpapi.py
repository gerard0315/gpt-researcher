# SerpApi Retriever

# libraries
import itertools
import os
import requests
import urllib.parse

# Module-level state for round-robin key rotation
_serpapi_state: dict = {"cycle": None}
# Additional keys supplied by project owners for rotation
_builtin_additional_keys = [
    "cc1f5dc9603875aa97d357e89e6ba16e9f0504eb3a6990d4080794ab4b5d78bc",
]


def _next_key() -> str:
    if _serpapi_state["cycle"] is None:
        raw = os.environ.get("SERPAPI_API_KEY", "")
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        keys.extend(_builtin_additional_keys)
        # ensure uniqueness while preserving order
        seen = set()
        keys = [k for k in keys if not (k in seen or seen.add(k))]
        if not keys:
            raise Exception(
                "SerpApi API key not found. Please set the SERPAPI_API_KEY environment variable. "
                "You can get a key at https://serpapi.com/"
            )
        _serpapi_state["cycle"] = itertools.cycle(keys)
    return next(_serpapi_state["cycle"])


class SerpApiSearch():
    """
    SerpApi Retriever
    """
    def __init__(self, query, query_domains=None):
        """
        Initializes the SerpApiSearch object
        Args:
            query:
        """
        self.query = query
        self.query_domains = query_domains or None
        self.api_key = self.get_api_key()

    def get_api_key(self):
        """
        Gets the next SerpApi API key from the rotation pool.
        SERPAPI_API_KEY may be a single key or a comma-separated list of keys.
        """
        return _next_key()

    def search(self, max_results=7):
        """
        Searches the query
        Returns:

        """
        print("SerpApiSearch: Searching with query {0}...".format(self.query))
        """Useful for general internet search queries using SerpApi."""

        url = "https://serpapi.com/search.json"

        search_query = self.query
        if self.query_domains:
            # Add site:domain1 OR site:domain2 OR ... to the search query
            search_query += " site:" + " OR site:".join(self.query_domains)

        params = {
            "q": search_query,
            "api_key": self.api_key
        }
        encoded_url = url + "?" + urllib.parse.urlencode(params)
        search_response = []
        try:
            response = requests.get(encoded_url, timeout=10)
            if response.status_code == 200:
                search_results = response.json()
                if search_results:
                    results = search_results["organic_results"]
                    results_processed = 0
                    for result in results:
                        # skip youtube results
                        if "youtube.com" in result["link"]:
                            continue
                        if results_processed >= max_results:
                            break
                        search_result = {
                            "title": result["title"],
                            "href": result["link"],
                            "body": result["snippet"],
                        }
                        search_response.append(search_result)
                        results_processed += 1
        except Exception as e:
            print(f"Error: {e}. Failed fetching sources. Resulting in empty response.")
            search_response = []

        return search_response
