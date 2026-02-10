from ..utils import check_pkg
from ...utils.api_keys import collect_api_keys, is_probable_quota_or_auth_error, mask_api_key


class ExaSearch:
    """
    Exa API Retriever
    """

    def __init__(self, query, query_domains=None):
        """
        Initializes the ExaSearch object.
        Args:
            query: The search query.
        """
        # This validation is necessary since exa_py is optional
        check_pkg("exa_py")
        from exa_py import Exa
        self.query = query
        self.api_keys = self._retrieve_api_keys()
        self.api_key = self.api_keys[0]
        self.client = Exa(api_key=self.api_key)
        self.query_domains = query_domains or None

    def _retrieve_api_keys(self):
        """
        Retrieves Exa API keys from environment variables.
        Returns:
            List of API keys in priority order.
        Raises:
            Exception: If the API key is not found.
        """
        api_keys = collect_api_keys(
            primary_env_var="EXA_API_KEY",
            fallback_env_var="EXA_API_KEY_FALLBACK",
            list_env_var="EXA_API_KEYS",
        )
        if not api_keys:
            raise Exception(
                "Exa API key not found. Please set the EXA_API_KEY environment variable. "
                "You can obtain your key from https://exa.ai/"
            )
        return api_keys

    def search(
        self, max_results=10, use_autoprompt=False, search_type="neural", **filters
    ):
        """
        Searches the query using the Exa API.
        Args:
            max_results: The maximum number of results to return.
            use_autoprompt: Whether to use autoprompting.
            search_type: The type of search (e.g., "neural", "keyword").
            **filters: Additional filters (e.g., date range, domains).
        Returns:
            A list of search results.
        """
        from exa_py import Exa

        last_error = None
        for index, api_key in enumerate(self.api_keys):
            client = self.client if api_key == self.api_key else Exa(api_key=api_key)
            try:
                results = client.search(
                    self.query,
                    type=search_type,
                    num_results=max_results,
                    include_domains=self.query_domains,
                    **filters
                )

                return [{"href": result.url, "body": result.text} for result in results.results]
            except Exception as e:
                last_error = e
                masked = mask_api_key(api_key)
                print(f"Exa key {masked} failed: {e}")
                can_retry_with_next_key = (
                    index < len(self.api_keys) - 1 and
                    is_probable_quota_or_auth_error(str(e))
                )
                if can_retry_with_next_key:
                    print(f"Trying next Exa key ({index + 2}/{len(self.api_keys)})...")
                    continue
                raise

        if last_error:
            raise last_error
        return []

    def find_similar(self, url, exclude_source_domain=False, **filters):
        """
        Finds similar documents to the provided URL using the Exa API.
        Args:
            url: The URL to find similar documents for.
            exclude_source_domain: Whether to exclude the source domain in the results.
            **filters: Additional filters.
        Returns:
            A list of similar documents.
        """
        results = self.client.find_similar(
            url, exclude_source_domain=exclude_source_domain, **filters
        )

        similar_response = [
            {"href": result.url, "body": result.text} for result in results.results
        ]
        return similar_response

    def get_contents(self, ids, **options):
        """
        Retrieves the contents of the specified IDs using the Exa API.
        Args:
            ids: The IDs of the documents to retrieve.
            **options: Additional options for content retrieval.
        Returns:
            A list of document contents.
        """
        results = self.client.get_contents(ids, **options)

        contents_response = [
            {"id": result.id, "content": result.text} for result in results.results
        ]
        return contents_response
