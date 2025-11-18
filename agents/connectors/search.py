import os
from abc import ABC, abstractmethod
from typing import Optional

from dotenv import load_dotenv
from tavily import TavilyClient

# Load environment variables
load_dotenv()

# API Keys
tavily_api_key = os.getenv("TAVILY_API_KEY")
exa_api_key = os.getenv("EXA_API_KEY")
kagi_api_key = os.getenv("KAGI_API_KEY")
perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")

# Provider selection
search_provider = os.getenv("SEARCH_PROVIDER", "tavily").lower()


class SearchProvider(ABC):
    """Abstract base class for search providers"""

    @abstractmethod
    def get_search_context(self, query: str) -> str:
        """Get search context for a query"""
        pass


class TavilySearch(SearchProvider):
    def __init__(self, api_key: str):
        self.client = TavilyClient(api_key=api_key)

    def get_search_context(self, query: str) -> str:
        return self.client.get_search_context(query=query)


class ExaSearch(SearchProvider):
    def __init__(self, api_key: str):
        try:
            import exa_py
            self.client = exa_py.Exa(api_key=api_key)
        except ImportError:
            raise ImportError("exa_py package not installed. Run: pip install exa_py")

    def get_search_context(self, query: str) -> str:
        # Exa search implementation
        results = self.client.search_and_contents(query, num_results=10)
        context = ""
        for result in results.results:
            context += f"Title: {result.title}\nURL: {result.url}\nContent: {result.text}\n\n"
        return context


class KagiSearch(SearchProvider):
    def __init__(self, api_key: str):
        try:
            import kagiapi
            self.api_key = api_key
        except ImportError:
            raise ImportError("kagiapi package not installed. Run: pip install kagiapi")

    def get_search_context(self, query: str) -> str:
        # Kagi search implementation - placeholder
        # This would need to be implemented based on Kagi's API
        raise NotImplementedError("Kagi search not yet implemented")


class PerplexitySearch(SearchProvider):
    def __init__(self, api_key: str):
        try:
            import perplexityai
            self.api_key = api_key
        except ImportError:
            raise ImportError("perplexityai package not installed. Run: pip install perplexityai")

    def get_search_context(self, query: str) -> str:
        # Perplexity search implementation - placeholder
        # This would need to be implemented based on Perplexity's API
        raise NotImplementedError("Perplexity search not yet implemented")


def get_search_client() -> SearchProvider:
    """Factory function to get the appropriate search client based on SEARCH_PROVIDER env var"""

    if search_provider == "tavily":
        if not tavily_api_key:
            raise ValueError("TAVILY_API_KEY environment variable is required for Tavily search")
        return TavilySearch(tavily_api_key)

    elif search_provider == "exa":
        if not exa_api_key:
            raise ValueError("EXA_API_KEY environment variable is required for Exa search")
        return ExaSearch(exa_api_key)

    elif search_provider == "kagi":
        if not kagi_api_key:
            raise ValueError("KAGI_API_KEY environment variable is required for Kagi search")
        return KagiSearch(kagi_api_key)

    elif search_provider == "perplexity":
        if not perplexity_api_key:
            raise ValueError("PERPLEXITY_API_KEY environment variable is required for Perplexity search")
        return PerplexitySearch(perplexity_api_key)

    else:
        raise ValueError(f"Unsupported SEARCH_PROVIDER: {search_provider}. Supported: tavily, exa, kagi, perplexity")


# Global search client instance
search_client = get_search_client()


def get_search_context(query: str) -> str:
    """Main function to get search context - maintains backward compatibility"""
    return search_client.get_search_context(query)


# Example usage (for testing)
if __name__ == "__main__":
    context = get_search_context("Will Biden drop out of the race?")
    print(context)
