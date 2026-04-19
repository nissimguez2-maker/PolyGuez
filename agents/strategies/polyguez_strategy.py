"""PolyGuez Momentum — strategy brain."""

import asyncio
import json
import os
import threading
import time
from datetime import datetime, timezone

from agents.application.prompts import Prompter
from agents.strategies.data_providers import fetch_all_providers
from agents.strategies.llm_adapters import get_llm_adapter
from agents.utils.logger import get_logger, log_event
from agents.utils.objects import (
    PolyGuezConfig,
    PositionState,
    RollingStats,
    SignalState,
    TradeRecord,
)
from agents.strategies.strategy_core import (  # noqa: F401
    _linear_edge_for_remaining,
    evaluate_entry_signal,
    calculate_position_size,
    calculate_max_capital_at_risk,
    check_daily_loss_limit,
    get_daily_loss_size_multiplier,
    compute_cooldown,
    check_emergency_exit,
    compute_clob_depth,
)

logger = get_logger("polyguez.strategy")
_prompter = Prompter()


async def get_llm_confirmation(signal_state, rolling_stats, config, price_to_beat=0.0, gap_direction="unknown", clob_depth_summary="", provider_context=""):
    if not config.llm_enabled:
        return ("GO", "llm-disabled", "", 0.0)

    start = asyncio.get_running_loop().time()

    # Provider context is now supplied from PolyGuezRunner's background cache
    # instead of fetching inline on the critical path.
    context_data = provider_context

    prompt = _prompter.momentum_confirmation(
        velocity=signal_state.btc_velocity, direction=signal_state.direction,
        yes_price=signal_state.yes_price, no_price=signal_state.no_price,
        spread=signal_state.spread, elapsed_seconds=signal_state.elapsed_seconds,
        win_rate=rolling_stats.win_rate, recent_trades_summary="",
        context_data=context_data, chainlink_price=signal_state.chainlink_price,
        binance_chainlink_gap=signal_state.binance_chainlink_gap,
        gap_direction=gap_direction, price_to_beat=price_to_beat,
        clob_depth_summary=clob_depth_summary,
        strike_delta=signal_state.strike_delta,
        terminal_probability=signal_state.terminal_probability,
        terminal_edge=signal_state.terminal_edge,
        binance_price=signal_state.btc_price,
    )

    adapter = get_llm_adapter(config)
    try:
        verdict, reason = await asyncio.wait_for(
            adapter.confirm_trade(prompt, timeout=config.llm_timeout),
            timeout=config.llm_timeout,
        )
    except asyncio.TimeoutError:
        fallback = getattr(config, 'llm_timeout_fallback', 'no-go')
        if fallback == "go":
            log_event(logger, "llm_timeout_fallback", f"LLM timed out after {config.llm_timeout}s — fallback=GO", level=30)
            return ("GO", "timeout-fallback", adapter.name, config.llm_timeout)
        log_event(logger, "llm_timeout", f"LLM confirmation timed out after {config.llm_timeout}s — skipping trade", level=30)
        return ("NO-GO", "timeout-skipped", adapter.name, config.llm_timeout)

    elapsed = asyncio.get_running_loop().time() - start

    logger.debug(f"LLM raw reason: {reason}")
    if reason == "parse-fallback":
        logger.warning(f"LLM parse-fallback fired — raw response could not be parsed, defaulting to NO-GO")

    log_event(logger, "llm_verdict", f"LLM ({adapter.name}): {verdict}", {
        "verdict": verdict, "reason": reason,
        "provider": adapter.name, "response_time": round(elapsed, 2),
    })
    return (verdict, reason, adapter.name, round(elapsed, 2))


def _extract_clob_fee(resp) -> float:
    """Best-effort parse of the fee returned by the CLOB order response.

    The py-clob-client response shape is not strictly documented and has
    changed between versions; we look for the most common keys and fall
    back to 0.0 if none is present. Called on both maker and FOK fill paths.
    """
    if not isinstance(resp, dict):
        return 0.0
    for k in ("fee", "feeAmount", "fee_amount", "makerFee", "takerFee"):
        v = resp.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


async def execute_entry(polymarket_client, token_id, size_usdc, mode, config=None, seconds_remaining=300.0, net_edge=0.0):
    if mode == "live":
        loop = asyncio.get_event_loop()
        # Maker limit order path — avoid taker fees
        if config and getattr(config, 'use_maker_orders', False):
            try:
                from py_clob_client.clob_types import OrderArgs, OrderType
                from py_clob_client.constants import BUY
                book = polymarket_client.client.get_order_book(token_id)
                if book and book.asks:
                    best_ask = float(book.asks[0].price)
                    limit_price = max(0.01, round(best_ask - config.maker_price_offset, 4))
                    expiration = int(time.time()) + 60 + int(seconds_remaining)
                    order_args = OrderArgs(token_id=token_id, price=limit_price, size=size_usdc, side=BUY, expiration=expiration)
                    signed = await loop.run_in_executor(None, polymarket_client.client.create_order, order_args)
                    resp = await loop.run_in_executor(None, lambda: polymarket_client.client.post_order(signed, orderType=OrderType.GTD, post_only=True))
                    log_event(logger, "maker_order_posted", f"[MAKER/GTD] Limit order at {limit_price:.4f}, expires in {60 + int(seconds_remaining)}s")
                    # Dynamic timeout + poll interval based on seconds_remaining.
                    # Late in the window we can't afford 2s of blind waiting.
                    max_wait = min(30.0, max(5.0, seconds_remaining * 0.4))
                    poll_interval = min(2.0, max(0.3, seconds_remaining / 20.0))
                    polls = max(1, int(max_wait / poll_interval))
                    # Poll for fill confirmation
                    order_id = None
                    if isinstance(resp, dict):
                        order_id = resp.get("orderID") or resp.get("id")
                    elif hasattr(resp, 'orderID'):
                        order_id = resp.orderID
                    if order_id:
                        for _poll in range(polls):
                            await asyncio.sleep(poll_interval)
                            try:
                                status = await loop.run_in_executor(None, polymarket_client.client.get_order, order_id)
                                if isinstance(status, dict) and status.get("status", "").upper() in ("MATCHED", "FILLED"):
                                    filled_price = float(status.get("price", limit_price))
                                    log_event(logger, "maker_order_confirmed_filled", f"[MAKER] Order {order_id} filled at {filled_price:.4f}")
                                    return {
                                        "status": "filled",
                                        "price": filled_price,
                                        "response": status,
                                        # MODEL-02: fee + fill type per commit.
                                        # Maker fills on Polymarket can earn a
                                        # rebate (negative fee).
                                        "fee_paid": _extract_clob_fee(status),
                                        "taker_maker": "maker",
                                    }
                            except Exception as poll_exc:
                                log_event(logger, "maker_poll_error", f"[MAKER] Poll error: {poll_exc}", level=30)
                        # Order didn't fill — cancel it
                        try:
                            await loop.run_in_executor(None, polymarket_client.client.cancel, order_id)
                            log_event(logger, "maker_order_cancelled", f"[MAKER] Order {order_id} cancelled after {max_wait:.0f}s unfilled")
                        except Exception as cancel_exc:
                            log_event(logger, "maker_cancel_error", f"[MAKER] Cancel failed: {cancel_exc}", level=30)
                        # If market has < 10s remaining, do NOT fall back to FOK
                        if seconds_remaining - max_wait < 10:
                            log_event(logger, "maker_expiry_too_close",
                                f"[MAKER] {seconds_remaining - max_wait:.0f}s remaining after cancel — skipping FOK fallback")
                            return {"status": "unfilled", "reason": "expiry_too_close",
                                    "fee_paid": 0.0, "taker_maker": None}
                        return {"status": "unfilled", "reason": "maker_timeout",
                                "fee_paid": 0.0, "taker_maker": None}
                    return {"status": "maker_posted", "price": limit_price, "response": resp,
                            "fee_paid": 0.0, "taker_maker": "maker"}
            except Exception as exc:
                log_event(logger, "maker_order_fallback", f"Maker order failed, falling back to FOK: {exc}", level=30)
        # FOK market order fallback — gated in live mode on net_edge floor.
        # Post speed-bump removal (Feb 2026), crossing the spread from a VPS
        # is a losing race. Only take FOK when net_edge is big enough that
        # the fee + adverse-selection cost is still clearly profitable.
        _fok_floor = getattr(config, "live_fok_net_edge_min", 0.10) if config else 0.10
        if mode == "live" and net_edge < _fok_floor:
            log_event(
                logger,
                "fok_skipped_low_edge",
                f"[MAKER] net_edge={net_edge:.4f} below FOK floor {_fok_floor:.4f} — "
                f"skipping taker fallback",
            )
            return {"status": "unfilled", "reason": "fok_skipped_low_edge",
                    "fee_paid": 0.0, "taker_maker": None}
        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            order_args = MarketOrderArgs(token_id=token_id, amount=size_usdc)
            signed = await loop.run_in_executor(None, polymarket_client.client.create_market_order, order_args)
            resp = await loop.run_in_executor(None, lambda: polymarket_client.client.post_order(signed, orderType=OrderType.FOK))
            log_event(logger, "order_executed", f"LIVE order posted", {"response": str(resp)})
            _fill_price = None
            if isinstance(resp, dict):
                try:
                    _fill_price = float(resp.get("price") or resp.get("filledPrice") or 0.0) or None
                except (TypeError, ValueError):
                    _fill_price = None
            return {
                "status": "filled",
                "response": resp,
                "price": _fill_price,
                "fee_paid": _extract_clob_fee(resp),
                "taker_maker": "taker",
            }
        except Exception as exc:
            log_event(logger, "order_error", f"Execution failed: {exc}", level=40)
            return {"status": "error", "error": str(exc),
                    "fee_paid": 0.0, "taker_maker": None}
    else:
        tag = "[DRY-RUN]" if mode == "dry-run" else "[PAPER]"
        maker_tag = " [MAKER]" if config and getattr(config, 'use_maker_orders', False) else ""
        log_event(logger, "order_simulated", f"{tag}{maker_tag} Simulated buy {size_usdc} USDC on {token_id}")
        # MODEL-02: always return populated fee_paid + taker_maker so
        # trade_log rows are non-NULL even in dry-run / paper modes.
        return {"status": "simulated", "mode": mode,
                "fee_paid": 0.0, "taker_maker": "simulated"}


async def execute_emergency_exit(polymarket_client, position, mode):
    log_event(logger, "emergency_exit", "EMERGENCY EXIT", {
        "side": position.side, "token_id": position.token_id, "entry_price": position.entry_price,
    })
    if mode == "live":
        loop = asyncio.get_event_loop()
        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            order_args = MarketOrderArgs(token_id=position.token_id, amount=position.size_usdc)
            signed = await loop.run_in_executor(None, polymarket_client.client.create_market_order, order_args)
            resp = await loop.run_in_executor(None, lambda: polymarket_client.client.post_order(signed, orderType=OrderType.FOK))
            log_event(logger, "emergency_exit_executed", "Emergency exit filled", {"response": str(resp)})
            return {"status": "filled", "response": resp}
        except Exception as exc:
            log_event(logger, "emergency_exit_error", f"Emergency exit failed: {exc}", level=40)
            return {"status": "error", "error": str(exc)}
    else:
        tag = "[DRY-RUN]" if mode == "dry-run" else "[PAPER]"
        log_event(logger, "emergency_exit_simulated", f"{tag} Simulated emergency exit")
        return {"status": "simulated", "mode": mode}


async def settle_with_retry(discovery, market_id, config):
    """FIX 3: Retry loop with exponential backoff for settlement."""
    for attempt in range(config.settlement_max_retries):
        loop = asyncio.get_event_loop()
        try:
            settled_market = await loop.run_in_executor(None, discovery.get_market_by_id, market_id)
            if settled_market and settled_market.get("closed"):
                log_event(logger, "settlement_resolved", f"Market {market_id} settled on attempt {attempt + 1}")
                return settled_market
        except Exception as exc:
            log_event(logger, "settlement_poll_error", f"Settlement poll attempt {attempt + 1} failed: {exc}")
        if attempt < config.settlement_max_retries - 1:
            delay = config.settlement_retry_delay * (2 ** attempt)
            log_event(logger, "settlement_retry", f"Retry {attempt + 2}/{config.settlement_max_retries} in {delay:.0f}s")
            await asyncio.sleep(delay)
    log_event(logger, "settlement_exhausted", f"Market {market_id} unsettled after {config.settlement_max_retries} attempts", level=40)
    return None


_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_HISTORY_FILE = os.path.join(_DATA_DIR, "trade_history.json")


_MAX_TRADES = 500


def save_rolling_stats(stats):
    # Cap trades list — archive overflow to Supabase
    if len(stats.trades) > _MAX_TRADES:
        overflow = stats.trades[:-_MAX_TRADES]
        stats.trades = stats.trades[-_MAX_TRADES:]
        try:
            from agents.utils.supabase_logger import _client
            client = _client()
            if client:
                rows = [{"ts": t.timestamp, "data": t.model_dump()} for t in overflow]
                client.table("trade_archive").insert(rows).execute()
                logger.info(f"[STATS] Archived {len(overflow)} trades to Supabase")
            else:
                logger.warning(f"[STATS] Trade archive skipped — Supabase client unavailable ({len(overflow)} trades lost from Supabase)")
        except Exception as exc:
            logger.warning(f"[STATS] Trade archive failed: {exc}")

    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_HISTORY_FILE, "w") as f:
        f.write(stats.model_dump_json(indent=2))

    # Upsert to Supabase as durable backup — run in a daemon thread so the
    # caller (always async context) isn't blocked for 400–1600ms waiting on
    # two synchronous HTTP calls. The write-failure alerter handles outages.
    stats_snapshot = stats.model_dump()
    stats_snapshot["trade_count"] = stats.total_trades
    stats_snapshot["total_pnl"] = stats.total_pnl
    stats_snapshot["wins"] = stats.total_wins
    stats_snapshot["losses"] = stats.total_losses
    stats_snapshot["win_rate"] = stats.win_rate

    def _supabase_upsert(data):
        try:
            from agents.utils.supabase_logger import _client, _on_write_failure
            client = _client()
            if not client:
                _on_write_failure(
                    RuntimeError("Supabase client unavailable"),
                    "rolling_stats:client_none",
                )
                return
            written_at = datetime.now(timezone.utc).isoformat()
            data["updated_at"] = written_at
            client.table("rolling_stats").upsert({
                "id": "singleton",
                "data": data,
            }).execute()
        except Exception as exc:
            logger.error(f"[STATS] Supabase save failed — stats may be lost on redeploy: {exc}")
            try:
                from agents.utils.supabase_logger import _on_write_failure
                _on_write_failure(exc, "rolling_stats:save")
            except Exception as _alert_exc:
                logger.warning(f"[STATS] Failure-counter hook failed: {_alert_exc}")

    threading.Thread(target=_supabase_upsert, args=(stats_snapshot,), daemon=True).start()


def load_rolling_stats():
    # FORCE_RESET: nuke local file AND return fresh stats
    if os.environ.get("FORCE_RESET", "").strip() == "1":
        try:
            os.remove(_HISTORY_FILE)
        except FileNotFoundError:
            pass
        logger.info("[STATS] FORCE_RESET=1 — returning fresh RollingStats")
        return RollingStats(simulated_balance=100.0)

    # Try local file first
    file_stats = None
    try:
        with open(_HISTORY_FILE, "r") as f:
            data = f.read().strip()
            if data:
                file_stats = RollingStats.model_validate_json(data)
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning(f"[STATS] Local file corrupted, falling back to Supabase: {exc}")

    # Cross-check: prefer Supabase if it carries a reset_token the local file doesn't know about.
    # This is the primary mechanism for deliberate clean-era resets.
    # We also prefer Supabase if its updated_at is strictly newer than the local file's.
    if file_stats is not None:
        try:
            from agents.utils.supabase_logger import _client
            client = _client()
            if client:
                resp = client.table("rolling_stats").select("data").eq("id", "singleton").execute()
                if resp.data and len(resp.data) > 0:
                    supa_data = resp.data[0]["data"]
                    supa_updated = supa_data.get("updated_at", "")
                    supa_reset_token = supa_data.get("reset_token", "")
                    file_reset_token = getattr(file_stats, "reset_token", "") or ""
                    supa_stats = RollingStats.model_validate(supa_data)
                    # PRIORITY 1: Supabase has a reset_token the local file doesn't — deliberate reset
                    if supa_reset_token and supa_reset_token != file_reset_token:
                        # COR-08: previously logged at INFO, which hid an
                        # event that overwrites local state. An operator
                        # who wiped Supabase by accident would not notice
                        # their local rolling_stats got replaced. Now
                        # logged at WARNING plus a Telegram alert so the
                        # overwrite is visible in Railway logs and phone
                        # notifications. Best-effort — the loader must
                        # never raise on the alert path.
                        logger.warning(
                            "[STATS] Supabase reset_token mismatch "
                            f"(supabase={supa_reset_token!r} local={file_reset_token!r}) — "
                            "using Supabase clean state. Verify this is intentional."
                        )
                        try:
                            from agents.utils.supabase_logger import _send_telegram_alert
                            _send_telegram_alert(
                                "[PolyGuez] rolling_stats reset_token mismatch detected. "
                                f"Supabase={supa_reset_token}, local={file_reset_token}. "
                                "Using Supabase state — verify this is intentional."
                            )
                        except Exception as _alert_exc:
                            logger.warning(f"[STATS] Telegram alert on reset_token mismatch failed: {_alert_exc}")
                        return supa_stats
                    # PRIORITY 2: Supabase updated_at is newer than the local file's mtime
                    # (handles trade-count-decreasing archival). We compare Supabase's ISO
                    # updated_at against the file's mtime converted to UTC ISO — RollingStats
                    # itself carries no updated_at field, so the filesystem mtime is the only
                    # honest local timestamp we have.
                    try:
                        file_mtime_iso = datetime.fromtimestamp(
                            os.path.getmtime(_HISTORY_FILE), tz=timezone.utc
                        ).isoformat()
                    except OSError:
                        file_mtime_iso = ""
                    if supa_updated and supa_updated > file_mtime_iso:
                        if supa_stats.total_trades > file_stats.total_trades:
                            logger.info(f"[STATS] Supabase is newer ({supa_updated} > {file_mtime_iso}, "
                                f"trades: {supa_stats.total_trades} > {file_stats.total_trades}) — using Supabase")
                            return supa_stats
        except Exception as exc:
            logger.warning(f"[STATS] Supabase cross-check failed: {exc}")
        logger.info("[STATS] Loaded from file")
        return file_stats
    
    # Fallback to Supabase if file not found
    try:
        from agents.utils.supabase_logger import _client
        client = _client()
        if client:
            resp = client.table("rolling_stats").select("data").eq("id", "singleton").execute()
            if resp.data and len(resp.data) > 0:
                logger.info("[STATS] Loaded from Supabase (file missing)")
                return RollingStats.model_validate(resp.data[0]["data"])
    except Exception as exc:
        logger.warning(f"[STATS] Supabase load failed: {exc}")
    logger.info("[STATS] Starting fresh — no history found")
    return RollingStats()
