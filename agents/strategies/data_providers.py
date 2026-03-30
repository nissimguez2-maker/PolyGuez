"""Pluggable data provider interface for LLM context enrichment."""

import asyncio
import os
from abc import ABC, abstractmethod

from agents.utils.logger import get_logger, log_event

logger = get_logger("polyguez.data_providers")


class DataProvider(ABC):
    """Base class for context data providers."""

    name = "base"

    @abstractmethod
    async def fetch(self, market_context):
        """Fetch context data for the LLM.

        Args:
            market_context: dict with keys like 'direction', 'velocity',
                'market_question', 'elapsed_seconds', etc.

        Returns:
            dict with provider-specific data, e.g. {"headlines": [...]}
        """
        raise NotImplementedError


class NewsProvider(DataProvider):
    """Wraps the existing agents.connectors.news.News connector."""

    name = "news"

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            from agents.connectors.news import News
            self._client = News()
        return self._client

    async def fetch(self, market_context):
        loop = asyncio.get_event_loop()
        try:
            client = self._get_client()
            keywords = "Bitcoin,BTC,crypto"
            articles = await loop.run_in_executor(
                None, client.get_articles_for_cli_keywords, keywords,
            )
            headlines = []
            for a in articles[:5]:
                if a.title:
                    headlines.append(a.title)
            return {"source": "newsapi", "headlines": headlines}
        except Exception as exc:
            log_event(logger, "data_provider_error", f"NewsProvider failed: {exc}")
            return {"source": "newsapi", "headlines": [], "error": str(exc)}


class TavilyProvider(DataProvider):
    """Web search via Tavily for real-time BTC context."""

    name = "tavily"

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            api_key = os.getenv("TAVILY_API_KEY", "")
            if not api_key:
                return None
            from tavily import TavilyClient
            self._client = TavilyClient(api_key=api_key)
        return self._client

    async def fetch(self, market_context):
        loop = asyncio.get_event_loop()
        try:
            client = self._get_client()
            if client is None:
                return {"source": "tavily", "results": [], "error": "no API key"}
            direction = market_context.get("direction", "")
            query = f"Bitcoin BTC price {direction} latest news"
            response = await loop.run_in_executor(
                None, client.get_search_context, query,
            )
            return {"source": "tavily", "context": response[:1000] if response else ""}
        except Exception as exc:
            log_event(logger, "data_provider_error", f"TavilyProvider failed: {exc}")
            return {"source": "tavily", "context": "", "error": str(exc)}


# -- Registry ----------------------------------------------------------------

_PROVIDER_REGISTRY = {
    "news": NewsProvider,
    "tavily": TavilyProvider,
}


def get_provider(name):
    """Get a DataProvider instance by name."""
    cls = _PROVIDER_REGISTRY.get(name)
    if cls is None:
        return None
    return cls()


async def fetch_all_providers(enabled_names, market_context, timeout=3.0):
    """Fetch from all enabled providers concurrently with per-provider timeout.

    Returns a merged dict of all provider results.
    """
    providers = []
    for name in enabled_names:
        p = get_provider(name)
        if p:
            providers.append(p)

    if not providers:
        return {}

    async def _safe_fetch(provider):
        try:
            return await asyncio.wait_for(
                provider.fetch(market_context), timeout=timeout,
            )
        except asyncio.TimeoutError:
            log_event(logger, "data_provider_timeout", f"{provider.name} timed out")
            return {"source": provider.name, "error": "timeout"}
        except Exception as exc:
            log_event(logger, "data_provider_error", f"{provider.name} error: {exc}")
            return {"source": provider.name, "error": str(exc)}

    results = await asyncio.gather(*[_safe_fetch(p) for p in providers])

    merged = {}
    for r in results:
        source = r.get("source", "unknown")
        merged[source] = r
    return merged
