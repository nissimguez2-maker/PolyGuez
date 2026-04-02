from __future__ import annotations
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def _client():
    from supabase import create_client
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return None
    return create_client(url, key)

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
