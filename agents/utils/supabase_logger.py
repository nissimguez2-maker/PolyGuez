from __future__ import annotations
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

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


def log_signal(snapshot: dict) -> None:
    """Fire-and-forget. Pass a flat dict of the signal state."""
    try:
        client = _client()
        if not client:
            return
        snapshot["ts"] = datetime.now(timezone.utc).isoformat()
        client.table("signal_log").insert(snapshot).execute()
    except Exception as e:
        logger.warning(f"Supabase signal log failed: {e}")


def log_trade(record: dict) -> None:
    """Fire-and-forget. Pass a flat dict of the trade record."""
    try:
        client = _client()
        if not client:
            return
        record["ts"] = datetime.now(timezone.utc).isoformat()
        client.table("trade_log").insert(record).execute()
    except Exception as e:
        logger.warning(f"Supabase trade log failed: {e}")
