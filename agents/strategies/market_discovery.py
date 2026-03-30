"""Discover active 5-minute BTC binary markets on Polymarket."""

import re
from datetime import datetime, timezone

from agents.polymarket.gamma import GammaMarketClient
from agents.utils.logger import get_logger, log_event

logger = get_logger("polyguez.market_discovery")


class MarketDiscovery:
    """Wraps GammaMarketClient to find 5-min BTC binary markets."""

    def __init__(self, gamma=None):
        self._gamma = gamma or GammaMarketClient()

    def find_active_btc_5min_market(self, config):
        """Return the first active 5-min BTC market dict, or None.

        Uses config.market_slug_pattern and config.market_question_pattern
        to match markets from the Gamma API.
        """
        slug_pat = config.market_slug_pattern
        question_re = None
        if config.market_question_pattern:
            question_re = re.compile(config.market_question_pattern, re.IGNORECASE)

        try:
            markets = self._gamma.get_markets(
                querystring_params={
                    "active": True,
                    "closed": False,
                    "archived": False,
                    "limit": 50,
                }
            )
        except Exception as exc:
            log_event(logger, "market_discovery_error", f"Gamma API error: {exc}")
            return None

        for m in markets:
            slug = m.get("slug", "") or ""
            question = m.get("question", "") or ""
            event_slug = ""
            if m.get("events"):
                for ev in m["events"]:
                    event_slug = ev.get("slug", "") or ""
                    break

            match = False
            if slug_pat and slug_pat in slug:
                match = True
            if slug_pat and slug_pat in event_slug:
                match = True
            if question_re and question_re.search(question):
                match = True

            if match and m.get("enableOrderBook"):
                log_event(logger, "market_discovered", f"Found market: {question}", {
                    "market_id": m.get("id"),
                    "slug": slug,
                    "question": question,
                    "endDate": m.get("endDate"),
                })
                return m

        return None

    @staticmethod
    def get_market_expiry(market_dict):
        """Parse endDate from market dict into a datetime."""
        end = market_dict.get("endDate") or market_dict.get("endDateIso") or ""
        if not end:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                dt = datetime.strptime(end, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None

    @staticmethod
    def get_market_token_ids(market_dict):
        """Return (yes_token_id, no_token_id) from market dict.

        clobTokenIds can be a JSON string list or a Python list.
        Convention: index 0 = YES, index 1 = NO.
        """
        import json as _json
        raw = market_dict.get("clobTokenIds", [])
        if isinstance(raw, str):
            raw = _json.loads(raw)
        if isinstance(raw, list) and len(raw) >= 2:
            return (str(raw[0]), str(raw[1]))
        return (None, None)

    @staticmethod
    def is_market_settled(market_dict):
        """Check if the market is closed (settled)."""
        return bool(market_dict.get("closed"))

    def get_market_by_id(self, market_id):
        """Fetch a single market dict by ID (for settlement checks)."""
        try:
            return self._gamma.get_market(market_id)
        except Exception as exc:
            log_event(logger, "market_fetch_error", f"Failed to fetch market {market_id}: {exc}")
            return None
