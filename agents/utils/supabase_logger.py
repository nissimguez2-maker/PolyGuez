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
        from supabase import create_client
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            return None
        _supabase_client = create_client(url, key)
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
