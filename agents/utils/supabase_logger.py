from __future__ import annotations
import json
import os
import logging
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Write-failure counter + Telegram alert (audit 1.5 / Phase 1.5).
#
# Every log_* function routes through `_submit_log`. When the underlying
# insert succeeds we call `_on_write_success()`; on exception we call
# `_on_write_failure()`, which increments a consecutive-failure counter and
# — once the counter crosses `SUPABASE_FAILURE_ALERT_THRESHOLD` (default 3)
# — emits a Telegram message. Alerts are rate-limited to one per 10 minutes
# so a sustained outage doesn't fan out into a notification storm.
#
# Telegram delivery is best-effort: if TELEGRAM_BOT_TOKEN or
# TELEGRAM_ALERT_CHAT_ID are unset the alert is downgraded to a log line
# and trading continues unaffected — the logger is not on the critical path.
# ---------------------------------------------------------------------------
_consecutive_write_failures = 0
_last_alert_ts = 0.0
_ALERT_COOLDOWN_SECONDS = 600
_alert_state_lock = threading.Lock()


def _on_write_success() -> None:
    """COR-07: zeroing the counter was previously unguarded. Under the
    bounded-but-parallel worker pool, a concurrent `_on_write_failure`
    could read/increment an intermediate value and misfire the alert.
    Holding the same lock as `_on_write_failure` makes this visibly safe.
    """
    global _consecutive_write_failures
    with _alert_state_lock:
        _consecutive_write_failures = 0


def _on_write_failure(exc: Exception, source: str) -> None:
    global _consecutive_write_failures, _last_alert_ts
    with _alert_state_lock:
        _consecutive_write_failures += 1
        try:
            threshold = int(os.environ.get("SUPABASE_FAILURE_ALERT_THRESHOLD", "3"))
        except ValueError:
            threshold = 3
        if _consecutive_write_failures < threshold:
            return
        now = time.time()
        if now - _last_alert_ts < _ALERT_COOLDOWN_SECONDS:
            return
        _last_alert_ts = now
        count = _consecutive_write_failures
    # Release lock before the (potentially slow) Telegram send.
    # `str(exc)` instead of `exc!r`: the repr can include SDK internals that
    # embed API keys or tokens from request URLs / headers; str() sticks to
    # the human-readable message and the type name is added explicitly.
    _send_telegram_alert(
        f"[PolyGuez] Supabase writes failing ({count} consecutive). "
        f"Last: {source}: {type(exc).__name__}: {str(exc)[:500]}"
    )


def _send_telegram_alert(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_ALERT_CHAT_ID", "")
    if not token or not chat_id:
        # Alert would have fired but no delivery channel configured. Log it
        # at WARNING so a human scanning Railway logs still sees it.
        logger.warning(f"[ALERT-LOG] {message}")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status >= 400:
                logger.warning(f"Telegram alert non-2xx: {resp.status}")
    except Exception as e:
        # Never let the alerter take down the logger worker.
        logger.warning(f"Telegram alert delivery failed: {e}")

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
_supabase_init_failed_at = 0.0   # monotonic; 0 = never failed
_SUPABASE_REINIT_INTERVAL = 120.0  # retry a failed init after 2 minutes
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
    global _supabase_client, _supabase_init_attempted, _supabase_init_failed_at
    # Fast path: init succeeded — return the live client.
    if _supabase_client is not None:
        return _supabase_client
    # Fast path: init failed recently — don't hammer create_client().
    # After _SUPABASE_REINIT_INTERVAL we'll try again (handles container
    # startup races where env vars aren't injected yet on the first call).
    if _supabase_init_attempted:
        if time.time() - _supabase_init_failed_at < _SUPABASE_REINIT_INTERVAL:
            return None
        # Cooldown elapsed — reset and retry.
        _supabase_init_attempted = False
    with _supabase_init_lock:
        if _supabase_client is not None:
            return _supabase_client
        if _supabase_init_attempted:
            if time.time() - _supabase_init_failed_at < _SUPABASE_REINIT_INTERVAL:
                return None
            _supabase_init_attempted = False
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
        global _supabase_init_failed_at
        _supabase_init_failed_at = time.time()
        msg = (
            f"[PolyGuez] Supabase client init FAILED: {type(e).__name__}: {str(e)[:500]}. "
            "All writes are dead. Will retry in 2 min. "
            "Check Railway logs for root cause."
        )
        logger.error(msg)
        _send_telegram_alert(msg)
        return None


def supabase_startup_check() -> bool:
    """Synchronous Supabase connectivity test — call once at bot startup.

    Unlike the write-failure alerter (which needs 3 consecutive failures +
    10-minute cooldown), this fires a Telegram alert immediately so a bad
    SUPABASE_SERVICE_KEY on Railway surfaces within seconds of the first
    deploy that has the problem.

    Test sequence:
      1. Env vars present?
      2. Client initialises?
      3. service_role key works? (upsert + delete a probe row on rolling_stats;
         anon key has no INSERT policy → PostgREST 403, definitive failure)

    Returns True if everything is healthy, False otherwise.
    """
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    missing = [n for n, v in [("SUPABASE_URL", url), ("SUPABASE_SERVICE_KEY", key)] if not v]
    if missing:
        msg = (
            f"[PolyGuez STARTUP] Supabase disabled — {', '.join(missing)} not set on Railway. "
            "Writes will be silent. Fix: Railway Variables → add the missing key(s)."
        )
        logger.error(msg)
        _send_telegram_alert(msg)
        return False

    client = _client()
    if not client:
        msg = (
            "[PolyGuez STARTUP] Supabase client init failed. "
            "Check SUPABASE_URL and SUPABASE_SERVICE_KEY on Railway."
        )
        logger.error(msg)
        _send_telegram_alert(msg)
        return False

    try:
        # Write a probe row then immediately delete it. rolling_stats has
        # no anon INSERT policy — a wrong/anon key raises PostgREST 403 here,
        # making this a definitive service_role verification without querying
        # user data.
        client.table("rolling_stats").upsert(
            {"id": "_startup_probe", "data": {"probe": True}},
            on_conflict="id",
        ).execute()
        client.table("rolling_stats").delete().eq("id", "_startup_probe").execute()
        logger.info("[STARTUP] Supabase OK — service_role key verified (write+delete probe passed)")
        return True
    except Exception as exc:
        msg = (
            f"[PolyGuez STARTUP] Supabase write probe FAILED: "
            f"{type(exc).__name__}: {str(exc)[:500]}. "
            "SUPABASE_SERVICE_KEY is likely wrong (anon key?) or rotated. "
            "Fix: Supabase Dashboard > Settings > API > service_role key → "
            "paste into Railway Variables as SUPABASE_SERVICE_KEY, then redeploy."
        )
        logger.error(msg)
        _send_telegram_alert(msg)
        return False


def log_signal(snapshot: dict, session_tag: str = "V6") -> None:
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
                # CRIT-01: previously this path returned silently, never
                # reaching _on_write_failure — so the audit-1.5 Telegram
                # alerter was blind to env-misconfig outages (exactly the
                # class that took the bot dark for 48h on 2026-04-16).
                # Now we count it as a failure so the alerter fires.
                _on_write_failure(
                    RuntimeError("supabase client unavailable (check SUPABASE_URL/SUPABASE_SERVICE_KEY)"),
                    "signal_log:no_client",
                )
                return
            client.table("signal_log").insert(snapshot).execute()
            _on_write_success()
        except Exception as e:
            logger.warning(f"Supabase signal log failed: {e}")
            _on_write_failure(e, "signal_log")
    _submit_log(_insert)


def log_trade(record: dict, session_tag: str = "V6") -> None:
    """Fire-and-forget trade_log insert. COR-01 idempotency: if a row with this
    `signal_id` already exists in trade_log (e.g. because a crash-restart re-
    settled the same trade, or _recover_pending_position double-called
    `_settle`), the insert is skipped rather than creating a duplicate row.

    The check is skipped when `signal_id` is empty/None — pre-signal_id rows
    and legacy emergency-exit records keep the old write-through behaviour
    rather than silently dropping.
    """
    record["ts"] = datetime.now(timezone.utc).isoformat()
    record["session_tag"] = session_tag
    # era column added by migration 2026-04-15 — every trade_log row must carry it.
    record["era"] = session_tag
    signal_id = record.get("signal_id")
    def _insert():
        try:
            client = _client()
            if not client:
                # CRIT-01: see log_signal for rationale. Trade-log writes
                # are the highest-leverage failure to surface — a silent
                # trade_log outage corrupts every calibration downstream.
                _on_write_failure(
                    RuntimeError("supabase client unavailable (check SUPABASE_URL/SUPABASE_SERVICE_KEY)"),
                    "trade_log:no_client",
                )
                return
            if signal_id:
                existing = (
                    client.table("trade_log")
                    .select("id")
                    .eq("signal_id", signal_id)
                    .limit(1)
                    .execute()
                )
                if getattr(existing, "data", None):
                    logger.warning(
                        "Supabase trade_log: signal_id=%s already exists "
                        "(id=%s); skipping duplicate insert.",
                        signal_id,
                        existing.data[0].get("id"),
                    )
                    _on_write_success()
                    return
            client.table("trade_log").insert(record).execute()
            _on_write_success()
        except Exception as e:
            logger.warning(f"Supabase trade log failed: {e}")
            _on_write_failure(e, "trade_log")
    _submit_log(_insert)


def log_shadow_trade(record: dict, session_tag: str = "v2") -> None:
    """Fire-and-forget in background thread — never blocks the main loop."""
    record["ts"] = datetime.now(timezone.utc).isoformat()
    record["session_tag"] = session_tag
    def _insert():
        try:
            client = _client()
            if not client:
                # CRIT-01: shadow writes are high-volume; surface the
                # outage via the same cooldown-gated alerter path.
                _on_write_failure(
                    RuntimeError("supabase client unavailable (check SUPABASE_URL/SUPABASE_SERVICE_KEY)"),
                    "shadow_trade_log:no_client",
                )
                return
            client.table("shadow_trade_log").insert(record).execute()
            _on_write_success()
        except Exception as e:
            logger.warning(f"Supabase shadow trade log failed: {e}")
            _on_write_failure(e, "shadow_trade_log")
    _submit_log(_insert)


def settle_shadow_trades(
    market_id: str,
    outcome_prices: list | None = None,
    *,
    btc_close_price: float | None = None,
    strike: float | None = None,
    cl_close_offset_seconds: float | None = None,
) -> None:
    """Settle all pending shadow trades for a given market.

    Two modes (BTC-feed is preferred — independent of Polymarket resolution timing):

    1. BTC-feed mode (authoritative for BTC up/down markets):
       Pass `btc_close_price` + `strike`. "up" wins if close > strike,
       "down" wins if close < strike. Uses the same BTC feed the bot trades on.

    2. Polymarket-resolution mode (legacy fallback):
       Pass `outcome_prices` = [yes_settled, no_settled] from Gamma. "up" wins
       if yes_settled > 0.5. Only works once the market has actually resolved.

    LATENCY-TASK-7: `cl_close_offset_seconds` — how far the Chainlink
    settlement tick was from the market's expiry timestamp. Stored on each
    settled shadow row so analysts can exclude "bad resolution windows"
    (large offsets) from win-rate comparisons. Only applied in BTC-feed mode.
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

            _update = {
                "exit_price": settled_price,
                "pnl": pnl,
                "outcome": outcome,
                "settled": True,
            }
            # LATENCY-TASK-7: record how far the Chainlink settlement
            # tick sat from expiry so we can bucket out "bad resolution
            # windows" in analysis. Only meaningful in BTC-feed mode.
            if use_btc_mode and cl_close_offset_seconds is not None:
                _update["cl_close_offset_seconds"] = round(
                    float(cl_close_offset_seconds), 2
                )
            client.table("shadow_trade_log").update(_update).eq(
                "id", shadow["id"]
            ).execute()

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
