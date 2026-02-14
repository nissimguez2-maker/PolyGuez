from __future__ import annotations
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import httpx
import logging

logger = logging.getLogger(__name__)


class NoCurrentMarket(Exception):
    pass


def _slug_for_window(timeframe_minutes: int, now_ts: float) -> str:
    window_seconds = timeframe_minutes * 60
    window_start = int(now_ts) // window_seconds * window_seconds
    return f"btc-updown-{timeframe_minutes}m-{window_start}"


def derive_btc_updown_slug_from_signal_id(signal_id: str, timeframe_minutes: int) -> Optional[str]:
    """
    Extract a 13-digit epoch-ms from signal_id and derive slug like:
    btc-updown-{tf}m-{window_start_s}
    Returns None if no timestamp found.
    """
    import re
    m = re.search(r"-(\d{13})-", signal_id or "")
    if not m:
        m = re.search(r"(\d{13})", signal_id or "")
        if not m:
            return None
    signal_ms = int(m.group(1))
    tf_ms = timeframe_minutes * 60_000
    window_start_ms = (signal_ms // tf_ms) * tf_ms
    window_start_s = window_start_ms // 1000
    return f"btc-updown-{timeframe_minutes}m-{window_start_s}"


def find_current_btc_updown_market(timeframe_minutes: int, now_ts: float, http_client: Optional[httpx.Client] = None, signal_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Return market info for current btc-updown window or raise NoCurrentMarket.
    """
    client = http_client or httpx.Client(timeout=10)
    # If signal_id provided, try derive slug exactly matching the signal window first
    if signal_id:
        try:
            derived = derive_btc_updown_slug_from_signal_id(signal_id, timeframe_minutes)
            if derived:
                slug = derived
            else:
                slug = _slug_for_window(timeframe_minutes, now_ts)
        except Exception:
            slug = _slug_for_window(timeframe_minutes, now_ts)
    else:
        slug = _slug_for_window(timeframe_minutes, now_ts)
    base = "https://gamma-api.polymarket.com"
    # Primary: direct slug lookup
    try:
        r = client.get(f"{base}/markets/slug/{slug}")
        if r.status_code == 200:
            m = r.json()
            # Ensure market has clobTokenIds (orderbook)
            clob = m.get("clobTokenIds")
            return {"source": "slug", "market": m, "clobTokenIds": clob}
    except Exception as e:
        logger.debug("slug lookup failed: %s", e)

    # Fallback: events with recurrence
    try:
        r = client.get(f"{base}/events", params={"active": "true", "closed": "false", "recurrence": f"{timeframe_minutes}m", "limit": 100})
        if r.status_code != 200:
            raise NoCurrentMarket(f"events query failed status={r.status_code}")
        events = r.json() or []
        now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
        for ev in events:
            ev_slug = (ev.get("slug") or "").lower()
            if not ev_slug.startswith(f"btc-updown-{timeframe_minutes}m-"):
                continue
            # check time window if available
            start = ev.get("startDate") or ev.get("start")
            end = ev.get("endDate") or ev.get("end")
            # best effort: parse ISO strings
            try:
                from dateutil import parser as _p  # optional
                start_dt = _p.parse(start) if start else None
                end_dt = _p.parse(end) if end else None
            except Exception:
                start_dt = None
                end_dt = None
            if start_dt and end_dt:
                if not (start_dt <= now_dt < end_dt):
                    logger.debug("event window mismatch for %s", ev_slug)
                    continue
            # get market info via slug
            try:
                m_r = client.get(f"{base}/markets/slug/{ev_slug}")
                if m_r.status_code == 200:
                    m = m_r.json()
                    return {"source": "events", "market": m, "clobTokenIds": m.get("clobTokenIds")}
            except Exception:
                continue
        raise NoCurrentMarket("no matching event market found")
    except NoCurrentMarket:
        raise
    except Exception as e:
        logger.exception("fallback events lookup failed: %s", e)
        raise NoCurrentMarket("events lookup exception") from e

