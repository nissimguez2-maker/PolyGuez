"""Discover active 5-minute BTC binary markets on Polymarket.

Uses deterministic slug construction: btc-updown-5m-{window_ts}
where window_ts = now - (now % 300).  Queries the Gamma events endpoint
directly instead of scanning all markets.
"""

import json
import re
import time
from datetime import datetime, timezone

from agents.polymarket.gamma import GammaMarketClient
from agents.utils.logger import get_logger, log_event

logger = get_logger("polyguez.market_discovery")

_WINDOW_SECONDS = 300  # 5-minute windows
_PRICE_TO_BEAT_RE = re.compile(r"\$([0-9,]+\.?\d*)")


class MarketDiscovery:
    """Wraps GammaMarketClient to find 5-min BTC binary markets."""

    def __init__(self, gamma=None):
        self._gamma = gamma or GammaMarketClient()

    # -- Primary discovery: deterministic slug via /events -------------------

    def find_active_btc_5min_market(self, config):
        """Return the first active 5-min BTC market dict, or None.

        Constructs the deterministic slug btc-updown-5m-{window_ts} and
        queries the Gamma /events endpoint directly.  Tries current window,
        then ±1 window as fallback for timing skew.
        """
        now_ts = int(time.time())
        current_window = now_ts - (now_ts % _WINDOW_SECONDS)

        # Try current window, then next window (may already be created),
        # then previous window (may still be open)
        candidates = [
            current_window,
            current_window + _WINDOW_SECONDS,
            current_window - _WINDOW_SECONDS,
        ]

        for window_ts in candidates:
            slug = f"btc-updown-5m-{window_ts}"
            market = self._query_event_by_slug(slug)
            if market and not market.get("closed"):
                return market

        # Fallback: broad search for any active btc-updown-5m market
        return self._fallback_search(config)

    def _query_event_by_slug(self, slug):
        """Query GET /events?slug=... and extract the first market."""
        try:
            log_event(logger, "market_query", f"Querying Gamma: GET /events?slug={slug}")
            events = self._gamma.get_events(
                querystring_params={"slug": slug}
            )
        except Exception as exc:
            log_event(logger, "market_discovery_error",
                f"Gamma events API error for slug={slug}: {type(exc).__name__}: {exc}",
                level=40)
            return None

        if not events:
            return None

        event = events[0] if isinstance(events, list) else events
        markets = event.get("markets", [])
        if not markets:
            log_event(logger, "market_no_markets", f"Event {slug} has no markets array")
            return None

        # Pick the first market that has order book enabled, is not closed,
        # and hasn't passed its endDate
        for m in markets:
            if m.get("closed"):
                continue
            # Skip markets whose endDate has already passed
            expiry = MarketDiscovery.get_market_expiry(m)
            if expiry and expiry <= datetime.now(timezone.utc):
                log_event(logger, "market_expired_skip", f"Skipping expired market: {m.get('question', '')}", {
                    "endDate": m.get("endDate"),
                })
                continue
            # Enrich the market dict with the event slug for reference
            m["_event_slug"] = event.get("slug", slug)
            m["_event_id"] = event.get("id", "")

            log_event(logger, "market_discovered", f"Found market: {m.get('question', '')}", {
                "market_id": m.get("id"),
                "slug": m.get("slug", ""),
                "event_slug": slug,
                "question": m.get("question", ""),
                "endDate": m.get("endDate"),
                "outcomes": m.get("outcomes"),
            })
            return m

        return None

    def _fallback_search(self, config):
        """Broad search: GET /markets with active filters, match by slug prefix."""
        try:
            markets = self._gamma.get_markets(
                querystring_params={
                    "active": True,
                    "closed": False,
                    "limit": 100,
                }
            )
        except Exception as exc:
            log_event(logger, "market_discovery_error", f"Gamma API fallback error: {exc}")
            return None

        for m in markets:
            slug = m.get("slug", "") or ""
            event_slug = ""
            if m.get("events"):
                for ev in m["events"]:
                    event_slug = ev.get("slug", "") or ""
                    break

            # Match btc-updown-5m prefix in slug or event slug
            if "btc-updown-5m" in slug or "btc-updown-5m" in event_slug:
                if m.get("enableOrderBook") or m.get("acceptingOrders"):
                    log_event(logger, "market_discovered_fallback", f"Fallback found: {m.get('question', '')}", {
                        "market_id": m.get("id"),
                        "slug": slug,
                    })
                    return m

        return None

    # -- Static helpers ------------------------------------------------------

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
        # Try ISO format parsing as final fallback
        try:
            dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            return dt
        except (ValueError, TypeError):
            pass
        return None

    @staticmethod
    def get_market_token_ids(market_dict):
        """Return (up_token_id, down_token_id) from market dict.

        clobTokenIds and outcomes can be JSON string lists or Python lists.
        Maps outcome names to token positions: index 0 and index 1.
        Convention: returns (Up/Yes token, Down/No token).
        """
        raw_tokens = market_dict.get("clobTokenIds", [])
        if isinstance(raw_tokens, str):
            raw_tokens = json.loads(raw_tokens)

        raw_outcomes = market_dict.get("outcomes", [])
        if isinstance(raw_outcomes, str):
            raw_outcomes = json.loads(raw_outcomes)

        if isinstance(raw_tokens, list) and len(raw_tokens) >= 2:
            # If outcomes are labeled, map by name
            if isinstance(raw_outcomes, list) and len(raw_outcomes) >= 2:
                outcome_map = {}
                for i, name in enumerate(raw_outcomes):
                    outcome_map[name.lower()] = str(raw_tokens[i])
                up_token = outcome_map.get("up") or outcome_map.get("yes") or str(raw_tokens[0])
                down_token = outcome_map.get("down") or outcome_map.get("no") or str(raw_tokens[1])
                return (up_token, down_token)
            return (str(raw_tokens[0]), str(raw_tokens[1]))
        return (None, None)

    @staticmethod
    def extract_price_to_beat(market_dict):
        """Extract the 'Price to Beat' dollar amount from the description.

        The Gamma API embeds it in the description like:
        "...the opening 'Price to Beat' of $66,477.42..."
        Returns the float value, or 0.0 if not found.
        """
        desc = market_dict.get("description", "") or ""
        match = _PRICE_TO_BEAT_RE.search(desc)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except (ValueError, TypeError):
                pass
        return 0.0

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

    @staticmethod
    def get_current_window_slug():
        """Return the deterministic slug for the current 5-min window."""
        now_ts = int(time.time())
        window_ts = now_ts - (now_ts % _WINDOW_SECONDS)
        return f"btc-updown-5m-{window_ts}"
