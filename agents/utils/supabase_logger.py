from __future__ import annotations
import os
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Shared thread pool for non-blocking Supabase writes
_log_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="supa_log")

_supabase_client = None
_supabase_init_attempted = False


def _client():
    global _supabase_client, _supabase_init_attempted
    if _supabase_client is not None:
        return _supabase_client
    if _supabase_init_attempted:
        return None
    _supabase_init_attempted = True
    try:
        from supabase import create_client, Client
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            logger.warning(
                "Supabase disabled: SUPABASE_URL and/or SUPABASE_SERVICE_KEY not set — "
                "signal_log and trade_log will be skipped"
            )
            return None
        # supabase 2.x may pass proxy= to httpx internally depending on versions.
        # Patch httpx.Client/AsyncClient to ignore proxy kwarg if it causes TypeError.
        import httpx
        _orig_client_init = httpx.Client.__init__
        _orig_async_init = httpx.AsyncClient.__init__
        def _patched_client_init(self, *args, **kwargs):
            kwargs.pop("proxy", None)
            kwargs.pop("proxies", None)
            return _orig_client_init(self, *args, **kwargs)
        def _patched_async_init(self, *args, **kwargs):
            kwargs.pop("proxy", None)
            kwargs.pop("proxies", None)
            return _orig_async_init(self, *args, **kwargs)
        httpx.Client.__init__ = _patched_client_init
        httpx.AsyncClient.__init__ = _patched_async_init
        try:
            _supabase_client = create_client(url, key)
        finally:
            # Restore original inits
            httpx.Client.__init__ = _orig_client_init
            httpx.AsyncClient.__init__ = _orig_async_init
        return _supabase_client
    except Exception as e:
        logger.warning(f"Supabase client init failed: {e}")
        return None


def log_signal(snapshot: dict, session_tag: str = "v1.1") -> None:
    """Fire-and-forget in background thread — never blocks the main loop."""
    snapshot["ts"] = datetime.now(timezone.utc).isoformat()
    snapshot["session_tag"] = session_tag
    def _insert():
        try:
            client = _client()
            if not client:
                return
            client.table("signal_log").insert(snapshot).execute()
        except Exception as e:
            logger.warning(f"Supabase signal log failed: {e}")
    _log_executor.submit(_insert)


def log_trade(record: dict, session_tag: str = "v1.1") -> None:
    """Fire-and-forget in background thread — never blocks the main loop."""
    record["ts"] = datetime.now(timezone.utc).isoformat()
    record["session_tag"] = session_tag
    def _insert():
        try:
            client = _client()
            if not client:
                return
            client.table("trade_log").insert(record).execute()
        except Exception as e:
            logger.warning(f"Supabase trade log failed: {e}")
    _log_executor.submit(_insert)


def log_shadow_trade(record: dict, session_tag: str = "v2") -> None:
    """Fire-and-forget in background thread — never blocks the main loop."""
    record["ts"] = datetime.now(timezone.utc).isoformat()
    record["session_tag"] = session_tag
    def _insert():
        try:
            client = _client()
            if not client:
                return
            client.table("shadow_trade_log").insert(record).execute()
        except Exception as e:
            logger.warning(f"Supabase shadow trade log failed: {e}")
    _log_executor.submit(_insert)


def settle_shadow_trades(market_id: str, outcome_prices: list) -> None:
    """Settle all pending shadow trades for a given market."""
    try:
        client = _client()
        if not client:
            return
        resp = client.table("shadow_trade_log").select("*").eq(
            "market_id", market_id
        ).eq("settled", False).execute()
        if not resp.data:
            return
        for shadow in resp.data:
            direction = shadow.get("direction", "")
            entry_price = shadow.get("entry_price", 0)
            settled_price = 0.0
            if len(outcome_prices) >= 2:
                yes_settled = float(outcome_prices[0])
                no_settled = float(outcome_prices[1])
                settled_price = yes_settled if direction == "up" else no_settled
                if settled_price > 0.5:
                    pnl = round(5.0 * (1.0 / entry_price - 1.0), 4) if entry_price > 0 else 0
                    outcome = "win"
                else:
                    pnl = -5.0
                    outcome = "loss"
            else:
                pnl = 0.0
                outcome = "unknown"
            client.table("shadow_trade_log").update({
                "exit_price": settled_price,
                "pnl": pnl,
                "outcome": outcome,
                "settled": True,
            }).eq("id", shadow["id"]).execute()
        logger.info(f"[SHADOW] Settled {len(resp.data)} shadow trades for market {market_id}")
    except Exception as e:
        logger.warning(f"Supabase shadow settle failed: {e}")
