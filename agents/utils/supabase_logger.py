from __future__ import annotations
import os
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Shared thread pool for non-blocking Supabase writes.
# ThreadPoolExecutor's internal queue is unbounded by default — under a
# Supabase outage the 2.5s signal cadence can balloon pending submissions
# until memory is exhausted. `_submit_log()` below checks the queue size
# and drops (with a periodic warning) once it crosses `_MAX_QUEUE_SIZE`.
_log_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="supa_log")
_MAX_QUEUE_SIZE = 500
_log_drops = 0

_supabase_client = None
_supabase_init_attempted = False
# Protects the _client() init path so two threads hitting log_signal /
# log_trade simultaneously on a cold import don't race to monkey-patch
# httpx. The double-checked pattern inside _client() uses this lock.
_supabase_init_lock = threading.Lock()


def _submit_log(fn):
    """Submit a background log task, dropping instead of queuing when full."""
    global _log_drops
    try:
        if _log_executor._work_queue.qsize() >= _MAX_QUEUE_SIZE:
            _log_drops += 1
            # Rate-limit the log noise so an outage doesn't spam warnings.
            if _log_drops == 1 or _log_drops % 100 == 0:
                logger.warning(
                    f"Supabase log queue full (size>={_MAX_QUEUE_SIZE}), "
                    f"dropping writes (total drops: {_log_drops})"
                )
            return
        _log_executor.submit(fn)
    except Exception as e:
        # Don't let logger bookkeeping take down the caller.
        logger.warning(f"Supabase log submit failed: {e}")


def _client():
    global _supabase_client, _supabase_init_attempted
    # Fast path: no lock needed once init has succeeded or failed once.
    if _supabase_client is not None:
        return _supabase_client
    if _supabase_init_attempted:
        return None
    with _supabase_init_lock:
        # Re-check inside the lock (double-checked locking): another thread
        # may have completed the init while we were blocked on acquisition.
        if _supabase_client is not None:
            return _supabase_client
        if _supabase_init_attempted:
            return None
        _supabase_init_attempted = True
        return _init_client_locked()


def _init_client_locked():
    """Must be called with _supabase_init_lock held. Sets _supabase_client on success."""
    global _supabase_client
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
        # HACK: supabase 2.x may pass proxy= to httpx internally.
        # We temporarily patch httpx to ignore proxy/proxies kwargs.
        # This is a global side-effect that lasts ~1ms during init.
        # See: https://github.com/supabase/supabase-py/issues/
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


def log_signal(snapshot: dict, session_tag: str = "V5") -> None:
    """Fire-and-forget in background thread — never blocks the main loop."""
    snapshot["ts"] = datetime.now(timezone.utc).isoformat()
    snapshot["session_tag"] = session_tag
    # Permanent era boundary: V5+ = clean data. Always override caller to
    # prevent pre-V5 rows from being written with a mismatched era.
    snapshot["era"] = session_tag
    def _insert():
        try:
            client = _client()
            if not client:
                return
            client.table("signal_log").insert(snapshot).execute()
        except Exception as e:
            logger.warning(f"Supabase signal log failed: {e}")
    _submit_log(_insert)


def log_trade(record: dict, session_tag: str = "V5") -> None:
    """Fire-and-forget in background thread — never blocks the main loop."""
    record["ts"] = datetime.now(timezone.utc).isoformat()
    record["session_tag"] = session_tag
    # era column added by migration 2026-04-15 — every trade_log row must carry it.
    record["era"] = session_tag
    def _insert():
        try:
            client = _client()
            if not client:
                return
            client.table("trade_log").insert(record).execute()
        except Exception as e:
            logger.warning(f"Supabase trade log failed: {e}")
    _submit_log(_insert)


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
    _submit_log(_insert)


def settle_shadow_trades(
    market_id: str,
    outcome_prices: list | None = None,
    *,
    btc_close_price: float | None = None,
    strike: float | None = None,
) -> None:
    """Settle all pending shadow trades for a given market.

    Two modes (BTC-feed is preferred — independent of Polymarket resolution timing):

    1. BTC-feed mode (authoritative for BTC up/down markets):
       Pass `btc_close_price` + `strike`. "up" wins if close > strike,
       "down" wins if close < strike. Uses the same BTC feed the bot trades on.

    2. Polymarket-resolution mode (legacy fallback):
       Pass `outcome_prices` = [yes_settled, no_settled] from Gamma. "up" wins
       if yes_settled > 0.5. Only works once the market has actually resolved.
    """
    use_btc_mode = (
        btc_close_price is not None and strike is not None and strike > 0
    )
    use_polymarket_mode = (
        not use_btc_mode
        and outcome_prices is not None
        and len(outcome_prices) >= 2
    )
    if not use_btc_mode and not use_polymarket_mode:
        return

    try:
        client = _client()
        if not client:
            return
        resp = client.table("shadow_trade_log").select("*").eq(
            "market_id", market_id
        ).eq("settled", False).execute()
        if not resp.data:
            return

        up_wins = (btc_close_price > strike) if use_btc_mode else None
        yes_settled = float(outcome_prices[0]) if use_polymarket_mode else None
        no_settled = float(outcome_prices[1]) if use_polymarket_mode else None

        for shadow in resp.data:
            direction = shadow.get("direction", "")
            entry_price = shadow.get("entry_price", 0) or 0
            size = float(shadow.get("size_usdc", 0) or 5.0)

            if use_btc_mode:
                won = (direction == "up" and up_wins) or (direction == "down" and not up_wins)
                settled_price = 1.0 if won else 0.0
                if won:
                    pnl = round(size * (1.0 / entry_price - 1.0), 4) if entry_price > 0 else 0.0
                    outcome = "win"
                else:
                    pnl = -size
                    outcome = "loss"
            else:
                settled_price = yes_settled if direction == "up" else no_settled
                # BUG-2 fix: use actual size_usdc instead of hardcoded $5
                if settled_price > 0.5:
                    pnl = round(size * (1.0 / entry_price - 1.0), 4) if entry_price > 0 else 0.0
                    outcome = "win"
                else:
                    pnl = -size
                    outcome = "loss"

            client.table("shadow_trade_log").update({
                "exit_price": settled_price,
                "pnl": pnl,
                "outcome": outcome,
                "settled": True,
            }).eq("id", shadow["id"]).execute()

        mode_label = "btc_feed" if use_btc_mode else "polymarket"
        detail = (
            f"close=${btc_close_price:.2f} strike=${strike:.2f}"
            if use_btc_mode
            else f"yes={yes_settled:.3f} no={no_settled:.3f}"
        )
        logger.info(
            f"[SHADOW] Settled {len(resp.data)} shadow trades for market {market_id} "
            f"via {mode_label} ({detail})"
        )
    except Exception as e:
        logger.warning(f"Supabase shadow settle failed: {e}")
