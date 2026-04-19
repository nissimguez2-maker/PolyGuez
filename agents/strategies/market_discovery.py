"""Discover active 5-minute BTC binary markets on Polymarket.

Uses deterministic slug construction: btc-updown-5m-{window_ts}
where window_ts = now - (now % 300).  Queries the Gamma events endpoint
directly instead of scanning all markets.
"""

import asyncio
import json
import re
import time
from datetime import datetime, timezone

from agents.polymarket.gamma import GammaMarketClient
from agents.utils.logger import get_logger, log_event

logger = get_logger("polyguez.market_discovery")

_WINDOW_SECONDS = 300  # 5-minute windows

# Tiered P2B regexes (most specific first)
_P2B_PRIMARY = re.compile(r"price\s+to\s+beat.{0,30}\$([0-9,]+\.\d{2})", re.IGNORECASE)
_P2B_SECONDARY = re.compile(r"opening.{0,30}\$([0-9,]+\.\d{2})", re.IGNORECASE)
_P2B_TERTIARY = re.compile(r"\$([0-9,]+\.\d{2})")  # first $ amount with 2 decimals

_P2B_SANITY_MIN = 10000.0
_P2B_SANITY_MAX = 500000.0


class MarketDiscovery:
    """Wraps GammaMarketClient to find 5-min BTC binary markets."""

    def __init__(self, gamma=None):
        self._gamma = gamma or GammaMarketClient()

    # -- Primary discovery: deterministic slug via /events -------------------

    # LATENCY-TASK-1: Skew allowances for the window-alignment predicate.
    # `MAX_START_SKEW` = how many seconds after `now` we still treat the
    # market as "already started" (covers clock drift between us and
    # Polymarket's event clock). `MAX_END_SKEW` = how many seconds past
    # `endDate` we still treat the market as in-progress (cushion for
    # `endDate` fields that land slightly before the true expiry).
    MAX_START_SKEW = 5.0
    MAX_END_SKEW = 10.0

    @staticmethod
    def _is_window_aligned(event_start, end, now, max_start_skew=MAX_START_SKEW, max_end_skew=MAX_END_SKEW):
        """Return True if `now` falls inside the market's live entry window.

        We allow a small cushion on both ends:
          * `event_start <= now + max_start_skew` → we haven't jumped into the
            next pre-listed window.
          * `now <= end + max_end_skew` → we haven't drifted past expiry.

        Missing `event_start` or `end` returns False so callers fall back to
        the broad search path rather than trading an unverified market.
        """
        if event_start is None or end is None or now is None:
            return False
        try:
            start_ts = event_start.timestamp() if hasattr(event_start, "timestamp") else float(event_start)
            end_ts = end.timestamp() if hasattr(end, "timestamp") else float(end)
            now_ts = now.timestamp() if hasattr(now, "timestamp") else float(now)
        except (TypeError, ValueError):
            return False
        return (start_ts <= now_ts + max_start_skew) and (now_ts <= end_ts + max_end_skew)

    def find_active_btc_5min_market(self, config):
        """Return the first active 5-min BTC market dict whose live entry
        window actually contains `now`, or None.

        LATENCY-TASK-1: Candidate preference is previous → current → next.
        Previous covers the ~10 s tail when Polymarket's endDate lags
        the true expiry; current is the normal hit; next is only selected
        when Polymarket has advanced its event clock ahead of ours. Every
        selected market is checked against `_is_window_aligned` so we
        never trade the next window thinking it's the current one.
        """
        now_ts = int(time.time())
        current_window = now_ts - (now_ts % _WINDOW_SECONDS)

        candidates = [
            current_window - _WINDOW_SECONDS,  # previous (fading tail)
            current_window,                    # current (the happy path)
            current_window + _WINDOW_SECONDS,  # next (only if pre-listed and now live)
        ]

        now_dt = datetime.now(timezone.utc)
        for window_ts in candidates:
            slug = f"btc-updown-5m-{window_ts}"
            market = self._query_event_by_slug(slug)
            if not market or market.get("closed"):
                continue

            event_start_dt = MarketDiscovery.get_event_start_time(market)
            end_dt = MarketDiscovery.get_market_expiry(market)
            aligned = MarketDiscovery._is_window_aligned(event_start_dt, end_dt, now_dt)
            market["_alignment_ok"] = aligned
            market["_alignment_now_ts"] = now_dt.isoformat()
            market["_alignment_event_start"] = event_start_dt.isoformat() if event_start_dt else None
            market["_alignment_end_date"] = end_dt.isoformat() if end_dt else None

            if not aligned:
                log_event(logger, "market_alignment_failed",
                    f"Skipping misaligned market (window={window_ts}): {market.get('question','')}",
                    {
                        "now": market["_alignment_now_ts"],
                        "event_start": market["_alignment_event_start"],
                        "end_date": market["_alignment_end_date"],
                        "slug": slug,
                    },
                    level=30)
                continue

            log_event(logger, "market_aligned",
                f"Selected aligned market: {market.get('question','')}",
                {
                    "now": market["_alignment_now_ts"],
                    "event_start": market["_alignment_event_start"],
                    "end_date": market["_alignment_end_date"],
                    "window_ts": window_ts,
                })
            return market

        # Fallback: broad search for any active btc-updown-5m market
        return self._fallback_search(config)

    async def find_active_btc_5min_market_async(self, config):
        """Async variant of find_active_btc_5min_market.

        Fires all three slug queries in parallel via asyncio.gather so the
        discovery hop takes max(one query latency) instead of sum(three).
        Results are still evaluated in priority order: previous → current → next.
        """
        now_ts = int(time.time())
        current_window = now_ts - (now_ts % _WINDOW_SECONDS)
        candidates = [
            current_window - _WINDOW_SECONDS,
            current_window,
            current_window + _WINDOW_SECONDS,
        ]
        slugs = [f"btc-updown-5m-{w}" for w in candidates]

        loop = asyncio.get_event_loop()
        results = await asyncio.gather(
            *[loop.run_in_executor(None, self._query_event_by_slug, slug) for slug in slugs],
            return_exceptions=True,
        )

        now_dt = datetime.now(timezone.utc)
        for i, market in enumerate(results):
            if isinstance(market, BaseException) or not market or market.get("closed"):
                continue
            slug = slugs[i]
            window_ts = candidates[i]
            event_start_dt = MarketDiscovery.get_event_start_time(market)
            end_dt = MarketDiscovery.get_market_expiry(market)
            aligned = MarketDiscovery._is_window_aligned(event_start_dt, end_dt, now_dt)
            market["_alignment_ok"] = aligned
            market["_alignment_now_ts"] = now_dt.isoformat()
            market["_alignment_event_start"] = event_start_dt.isoformat() if event_start_dt else None
            market["_alignment_end_date"] = end_dt.isoformat() if end_dt else None

            if not aligned:
                log_event(logger, "market_alignment_failed",
                    f"Skipping misaligned market (window={window_ts}): {market.get('question', '')}",
                    {
                        "now": market["_alignment_now_ts"],
                        "event_start": market["_alignment_event_start"],
                        "end_date": market["_alignment_end_date"],
                        "slug": slug,
                    },
                    level=30)
                continue

            log_event(logger, "market_aligned",
                f"Selected aligned market: {market.get('question', '')}",
                {
                    "now": market["_alignment_now_ts"],
                    "event_start": market["_alignment_event_start"],
                    "end_date": market["_alignment_end_date"],
                    "window_ts": window_ts,
                })
            return market

        loop2 = asyncio.get_event_loop()
        return await loop2.run_in_executor(None, self._fallback_search, config)

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

            # Integrity check: market question should match expected template
            q = (m.get("question", "") or "").lower()
            if "bitcoin" not in q or ("up" not in q and "down" not in q):
                log_event(logger, "market_template_mismatch",
                    f"Market question does not match BTC Up/Down template: {m.get('question', '')}", level=40)

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
        """Broad search: GET /markets with active filters, match by slug prefix.

        LATENCY-TASK-1: Every candidate from the broad search is still
        filtered through `_is_window_aligned` — we never return a
        fallback market whose live window doesn't actually contain now.
        """
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

        now_dt = datetime.now(timezone.utc)
        for m in markets:
            slug = m.get("slug", "") or ""
            event_slug = ""
            if m.get("events"):
                for ev in m["events"]:
                    event_slug = ev.get("slug", "") or ""
                    break

            # Match btc-updown-5m prefix in slug or event slug
            if "btc-updown-5m" in slug or "btc-updown-5m" in event_slug:
                if not (m.get("enableOrderBook") or m.get("acceptingOrders")):
                    continue
                event_start_dt = MarketDiscovery.get_event_start_time(m)
                end_dt = MarketDiscovery.get_market_expiry(m)
                aligned = MarketDiscovery._is_window_aligned(event_start_dt, end_dt, now_dt)
                m["_alignment_ok"] = aligned
                m["_alignment_now_ts"] = now_dt.isoformat()
                m["_alignment_event_start"] = event_start_dt.isoformat() if event_start_dt else None
                m["_alignment_end_date"] = end_dt.isoformat() if end_dt else None
                if not aligned:
                    log_event(logger, "market_alignment_failed_fallback",
                        f"Fallback match misaligned — skipping: {m.get('question','')}",
                        {"slug": slug, "event_slug": event_slug}, level=30)
                    continue
                log_event(logger, "market_discovered_fallback",
                    f"Fallback found: {m.get('question', '')}",
                    {"market_id": m.get("id"), "slug": slug})
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
    def get_event_start_time(market_dict):
        """Parse eventStartTime (or startDate) from market dict into a datetime."""
        start = market_dict.get("eventStartTime") or market_dict.get("startDate") or ""
        if not start:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                dt = datetime.strptime(start, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        try:
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
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
    def extract_price_to_beat(market_dict, sanity_min=_P2B_SANITY_MIN, sanity_max=_P2B_SANITY_MAX, chainlink_price=None):
        """Extract the 'Price to Beat' dollar amount from the description.

        Uses a 3-tier regex strategy:
          1. Match "price to beat" followed by a $X,XXX.XX amount
          2. Match "opening" followed by a $X,XXX.XX amount
          3. Broad match: first $X,XXX.XX amount in description
          4. Fallback: use chainlink_price if provided and within sanity range
             (markets no longer embed a dollar P2B in their description)

        Returns Optional[float]: parsed value, or None on failure.
        All tiers require the value to pass a sanity check (default 10k–500k).
        """
        desc = market_dict.get("description", "") or ""

        if desc:
            for pattern in (_P2B_PRIMARY, _P2B_SECONDARY, _P2B_TERTIARY):
                match = pattern.search(desc)
                if match:
                    try:
                        value = float(match.group(1).replace(",", ""))
                        if sanity_min <= value <= sanity_max:
                            return value
                    except (ValueError, TypeError):
                        continue

        # Tier 4: fallback to Chainlink price at market open
        if chainlink_price is not None and sanity_min <= chainlink_price <= sanity_max:
            log_event(logger, "p2b_chainlink_fallback",
                f"P2B not in description — using Chainlink price at market open as P2B: ${chainlink_price:.2f}",
                level=30)
            return chainlink_price

        return None

    @staticmethod
    def cross_check_price_to_beat(description_p2b, chainlink_price, discovery_lag_seconds=0.0, btc_price=0.0):
        """Cross-check P2B against Chainlink price to detect stale/wrong values.

        Returns (passes: bool, divergence: float).
        Tolerance = max(30.0, btc_price * 0.0005) + (discovery_lag_seconds * 3.0)
        """
        if description_p2b is None or chainlink_price is None or chainlink_price <= 0:
            return (False, float('inf'))

        ref_price = btc_price if btc_price > 0 else chainlink_price
        tolerance = max(30.0, ref_price * 0.0005) + (min(discovery_lag_seconds, 10.0) * 3.0)
        divergence = abs(description_p2b - chainlink_price)
        return (divergence <= tolerance, divergence)

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
