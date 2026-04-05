"""PolyGuez Momentum — strategy brain."""

import asyncio
import json
import math
import os
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

logger = get_logger("polyguez.strategy")
_prompter = Prompter()


def evaluate_entry_signal(
    btc_velocity, btc_price, yes_price, no_price, spread,
    elapsed_seconds, usdc_balance, config, rolling_stats,
    has_position, open_position_count=0,
    chainlink_price=0.0, chainlink_age=-1.0, binance_chainlink_gap=0.0,
    clob_depth=0.0, price_to_beat=None,
    price_feed_ok=True,
):
    # Momentum direction (from velocity) — used for v1 legacy conditions only
    momentum_direction = "up" if btc_velocity > 0 else "down"

    # Short-circuit: no P2B means no entry
    if price_to_beat is None:
        return SignalState(
            btc_velocity=btc_velocity, btc_price=btc_price,
            chainlink_price=chainlink_price, binance_chainlink_gap=binance_chainlink_gap,
            yes_price=yes_price, no_price=no_price, spread=spread,
            elapsed_seconds=elapsed_seconds, direction=momentum_direction,
            momentum_direction=momentum_direction,
            p2b_source="none",
            price_feed_ok=price_feed_ok,
        )

    # Terminal probability via logistic model
    strike_delta = chainlink_price - price_to_beat
    seconds_remaining = max(1.0, 300.0 - elapsed_seconds)
    k = 0.035 / math.sqrt(seconds_remaining / 60.0)
    clamped = max(-500.0, min(500.0, -k * strike_delta))
    terminal_probability_yes = 1.0 / (1.0 + math.exp(clamped))

    # Delta direction (from Chainlink vs P2B) — used for v2 terminal probability
    # This is what actually matters: which side is the oracle favoring?
    delta_direction = "up" if strike_delta >= 0 else "down"

    # Use delta_direction as the primary direction for entry decisions
    direction = delta_direction

    if delta_direction == "up":
        selected_side_probability = terminal_probability_yes
        token_price = yes_price
    else:
        selected_side_probability = 1.0 - terminal_probability_yes
        token_price = no_price

    # v2: fair value IS the terminal probability
    estimated_fv = selected_side_probability
    terminal_edge = selected_side_probability - token_price
    edge = estimated_fv - token_price

    if elapsed_seconds <= config.early_window_seconds:
        required_edge = config.min_edge * config.early_edge_multiplier
    elif elapsed_seconds <= config.mid_window_seconds:
        required_edge = config.min_edge * config.mid_edge_multiplier
    else:
        required_edge = config.min_edge * config.late_edge_multiplier

    effective_velocity_threshold = config.velocity_threshold
    effective_required_edge = required_edge
    if (
        rolling_stats.total_trades >= config.cooldown_startup_trades
        and rolling_stats.win_rate < config.cooldown_win_rate_short
    ):
        effective_velocity_threshold *= config.cooldown_tightened_multiplier
        effective_required_edge *= config.cooldown_tightened_multiplier

    pos_size = calculate_position_size(usdc_balance, config, edge=edge, depth=clob_depth)

    cooldown_ok = True
    if rolling_stats.cooldown_until:
        try:
            until = datetime.fromisoformat(rolling_stats.cooldown_until)
            if datetime.now(timezone.utc) < until:
                cooldown_ok = False
        except (ValueError, TypeError):
            pass

    gap_favors = False
    if delta_direction == "up" and binance_chainlink_gap > 0:
        gap_favors = True
    elif delta_direction == "down" and binance_chainlink_gap < 0:
        gap_favors = True
    if config.min_oracle_gap == 0.0:
        oracle_gap_ok = True
    else:
        oracle_gap_ok = gap_favors and abs(binance_chainlink_gap) >= config.min_oracle_gap

    clob_mispricing_ok = edge > 0 and token_price < estimated_fv
    # depth < 0 means unmeasurable (no wallet / API error) — skip gate
    depth_ok = True if clob_depth < 0 else clob_depth >= config.min_clob_depth
    terminal_edge_ok = terminal_edge > config.min_terminal_edge

    # Use strict delta threshold in fast-moving markets
    fast_market = abs(btc_velocity) > config.velocity_threshold * 3
    active_delta_threshold = config.conviction_min_delta_strict if fast_market else config.conviction_min_delta
    delta_magnitude_ok = abs(strike_delta) > active_delta_threshold

    # Stale Chainlink guard near expiry
    chainlink_fresh_ok = True
    if chainlink_age > 15.0 and seconds_remaining < 90.0:
        chainlink_fresh_ok = False
        log_event(logger, "signal_stale_cl",
            f"[SIGNAL] chainlink_stale age={chainlink_age:.1f}s seconds_remaining={seconds_remaining:.0f}s → blocked")

    # CLOB consensus: don't trade against overwhelming market consensus
    our_price = yes_price if direction == "up" else no_price
    clob_consensus_ok = our_price >= config.min_clob_consensus

    # Build all conditions for diagnostic logging
    _velocity_ok = abs(btc_velocity) > effective_velocity_threshold
    _edge_ok = edge > effective_required_edge
    _spread_ok = spread < config.max_spread
    _no_position = not has_position
    _daily_loss_ok = check_daily_loss_limit(rolling_stats, config, usdc_balance)
    _balance_ok = usdc_balance >= pos_size
    _position_limit_ok = open_position_count < config.max_open_positions

    # Log first failing condition for quick bottleneck identification
    _conditions = [
        (price_feed_ok, "price_feed_stale"),
        (chainlink_fresh_ok, f"stale_chainlink={chainlink_age:.0f}s_near_expiry"),
        (terminal_edge_ok, f"terminal_edge={terminal_edge:.4f}<{config.min_terminal_edge}"),
        (delta_magnitude_ok, f"delta={abs(strike_delta):.1f}<{active_delta_threshold}({'strict' if fast_market else 'normal'})"),
        (_edge_ok, f"edge={edge:.4f}<{effective_required_edge:.4f}"),
        (_spread_ok, f"spread={spread:.4f}>={config.max_spread}"),
        (depth_ok, f"depth={clob_depth:.0f}<{config.min_clob_depth}"),
        (clob_consensus_ok, f"consensus={our_price:.3f}<{config.min_clob_consensus}"),
        (_no_position, "already_in_position"),
        (cooldown_ok, "in_cooldown"),
        (_daily_loss_ok, "daily_loss_limit"),
        (_balance_ok, f"balance=${usdc_balance:.2f}"),
        (_position_limit_ok, "position_limit"),
    ]
    _first_fail = next((reason for ok, reason in _conditions if not ok), None)
    if _first_fail:
        log_event(logger, "signal_blocked",
            f"[SIGNAL] edge={edge:.4f} depth={clob_depth:.0f} "
            f"gap={binance_chainlink_gap:.2f} delta={strike_delta:.1f} "
            f"t_edge={terminal_edge:.4f} spread={spread:.4f} → {_first_fail}")
    else:
        _delta_tag = "strict" if fast_market else "normal"
        log_event(logger, "signal_all_met",
            f"[SIGNAL] ALL MET edge={edge:.4f} depth={clob_depth:.0f} "
            f"gap={binance_chainlink_gap:.2f} delta={strike_delta:.1f}(thr={active_delta_threshold}/{_delta_tag}) "
            f"t_edge={terminal_edge:.4f} spread={spread:.4f}")

    return SignalState(
        btc_velocity=btc_velocity, btc_price=btc_price,
        chainlink_price=chainlink_price, binance_chainlink_gap=binance_chainlink_gap,
        yes_price=yes_price, no_price=no_price, spread=spread,
        elapsed_seconds=elapsed_seconds, direction=direction,
        momentum_direction=momentum_direction,
        estimated_fair_value=estimated_fv, edge=edge,
        required_edge=effective_required_edge, gap_favors_position=gap_favors,
        velocity_ok=_velocity_ok,
        oracle_gap_ok=oracle_gap_ok, clob_mispricing_ok=clob_mispricing_ok,
        edge_ok=_edge_ok,
        spread_ok=_spread_ok,
        no_position=_no_position, cooldown_ok=cooldown_ok,
        daily_loss_ok=_daily_loss_ok,
        balance_ok=_balance_ok,
        position_limit_ok=_position_limit_ok,
        depth_ok=depth_ok,
        clob_spread_raw=spread,
        depth_at_ask_raw=clob_depth,
        chainlink_fresh_ok=chainlink_fresh_ok,
        clob_consensus_ok=clob_consensus_ok,
        p2b_value=price_to_beat, p2b_source="description",
        strike_delta=strike_delta,
        terminal_probability=selected_side_probability,
        terminal_edge=terminal_edge,
        terminal_edge_ok=terminal_edge_ok,
        delta_magnitude_ok=delta_magnitude_ok,
        price_feed_ok=price_feed_ok,
    )


def calculate_position_size(usdc_balance, config, edge=0.0, depth=0.0):
    is_strong = edge >= config.strong_edge_threshold and depth >= config.strong_depth_threshold
    if usdc_balance < config.low_balance_threshold:
        return config.bet_size_low_balance_strong if is_strong else config.bet_size_low_balance_normal
    return config.bet_size_strong if is_strong else config.bet_size_normal


def calculate_max_capital_at_risk(usdc_balance, config):
    return max(config.bet_size_strong, 7.0)


def check_daily_loss_limit(rolling_stats, config, usdc_balance):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if rolling_stats.daily_pnl_reset_utc != today:
        return True
    limit = config.max_daily_loss
    if limit is None:
        limit = calculate_max_capital_at_risk(usdc_balance, config)
    return rolling_stats.daily_pnl > -abs(limit)


def compute_cooldown(rolling_stats, config):
    total = rolling_stats.total_trades
    if total < config.cooldown_startup_trades:
        return 1
    if not rolling_stats.trades:
        return 0
    last_trade = rolling_stats.trades[-1]
    wr = rolling_stats.win_rate
    if last_trade.outcome == "win":
        if wr >= config.cooldown_win_rate_no_cooldown:
            return 0
        return config.cooldown_cycles_short
    else:
        if wr >= config.cooldown_win_rate_short:
            return config.cooldown_cycles_short
        return config.cooldown_cycles_long


def check_emergency_exit(btc_velocity, entry_direction, config, chainlink_price=0.0, price_to_beat=0.0):
    """FIX 1: Uses separate thresholds per exit path."""
    if chainlink_price > 0 and price_to_beat > 0:
        chainlink_move = chainlink_price - price_to_beat
        if entry_direction == "up" and chainlink_move < -config.reversal_chainlink_threshold:
            return True
        if entry_direction == "down" and chainlink_move > config.reversal_chainlink_threshold:
            return True
        return False
    if entry_direction == "up" and btc_velocity < -config.reversal_velocity_threshold:
        return True
    if entry_direction == "down" and btc_velocity > config.reversal_velocity_threshold:
        return True
    return False


def compute_clob_depth(order_book, side):
    """FIX 2: Compute ask-side depth within $0.05 of best price.

    Supports both dict-style books and OrderBookSummary objects with
    .asks/.bids attributes containing OrderSummary objects.
    """
    if not order_book:
        return 0.0
    # Support both attribute access (OrderBookSummary) and dict access
    try:
        entries = order_book.asks if hasattr(order_book, 'asks') else order_book.get("asks", [])
    except Exception:
        return 0.0
    if not entries:
        return 0.0
    try:
        first = entries[0]
        best_price = float(first.price if hasattr(first, 'price') else first["price"])
    except (KeyError, ValueError, TypeError, IndexError, AttributeError):
        return 0.0
    depth = 0.0
    for entry in entries:
        try:
            price = float(entry.price if hasattr(entry, 'price') else entry["price"])
            size = float(entry.size if hasattr(entry, 'size') else entry["size"])
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
        if price - best_price <= 0.05:
            depth += size
    return depth


async def get_llm_confirmation(signal_state, rolling_stats, config, price_to_beat=0.0, gap_direction="unknown", clob_depth_summary=""):
    if not config.llm_enabled:
        return ("GO", "llm-disabled", "", 0.0)

    start = asyncio.get_event_loop().time()

    prompt = _prompter.momentum_confirmation(
        velocity=signal_state.btc_velocity, direction=signal_state.direction,
        yes_price=signal_state.yes_price, no_price=signal_state.no_price,
        spread=signal_state.spread, elapsed_seconds=signal_state.elapsed_seconds,
        win_rate=rolling_stats.win_rate, recent_trades_summary="",
        context_data="", chainlink_price=signal_state.chainlink_price,
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
        log_event(logger, "llm_timeout", f"LLM confirmation timed out after {config.llm_timeout}s — skipping trade", level=30)
        return ("NO-GO", "timeout-skipped", adapter.name, config.llm_timeout)

    elapsed = asyncio.get_event_loop().time() - start

    logger.debug(f"LLM raw reason: {reason}")
    if reason == "parse-fallback":
        logger.warning(f"LLM parse-fallback fired — raw response could not be parsed, defaulting to NO-GO")

    log_event(logger, "llm_verdict", f"LLM ({adapter.name}): {verdict}", {
        "verdict": verdict, "reason": reason,
        "provider": adapter.name, "response_time": round(elapsed, 2),
    })
    return (verdict, reason, adapter.name, round(elapsed, 2))


async def execute_entry(polymarket_client, token_id, size_usdc, mode, config=None):
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
                    order_args = OrderArgs(token_id=token_id, price=limit_price, size=size_usdc, side=BUY)
                    signed = await loop.run_in_executor(None, polymarket_client.client.create_order, order_args)
                    resp = await loop.run_in_executor(None, lambda: polymarket_client.client.post_order(signed, orderType=OrderType.GTC))
                    log_event(logger, "maker_order_posted", f"[MAKER] Limit order at {limit_price:.4f}")
                    return {"status": "maker_posted", "price": limit_price, "response": resp}
            except Exception as exc:
                log_event(logger, "maker_order_fallback", f"Maker order failed, falling back to FOK: {exc}", level=30)
        # FOK market order fallback
        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            order_args = MarketOrderArgs(token_id=token_id, amount=size_usdc)
            signed = await loop.run_in_executor(None, polymarket_client.client.create_market_order, order_args)
            resp = await loop.run_in_executor(None, lambda: polymarket_client.client.post_order(signed, orderType=OrderType.FOK))
            log_event(logger, "order_executed", f"LIVE order posted", {"response": str(resp)})
            return {"status": "filled", "response": resp}
        except Exception as exc:
            log_event(logger, "order_error", f"Execution failed: {exc}", level=40)
            return {"status": "error", "error": str(exc)}
    else:
        tag = "[DRY-RUN]" if mode == "dry-run" else "[PAPER]"
        maker_tag = " [MAKER]" if config and getattr(config, 'use_maker_orders', False) else ""
        log_event(logger, "order_simulated", f"{tag}{maker_tag} Simulated buy {size_usdc} USDC on {token_id}")
        return {"status": "simulated", "mode": mode}


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
        except Exception as exc:
            logger.warning(f"[STATS] Trade archive failed: {exc}")

    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_HISTORY_FILE, "w") as f:
        f.write(stats.model_dump_json(indent=2))
    # Upsert to Supabase as durable backup
    try:
        from agents.utils.supabase_logger import _client
        client = _client()
        if client:
            client.table("rolling_stats").upsert({
                "id": "singleton",
                "data": stats.model_dump(),
            }).execute()
    except Exception as exc:
        logger.warning(f"[STATS] Supabase save failed: {exc}")


def load_rolling_stats():
    # Try local file first
    try:
        with open(_HISTORY_FILE, "r") as f:
            data = f.read().strip()
            if data:
                logger.info("[STATS] Loaded from file")
                return RollingStats.model_validate_json(data)
    except (FileNotFoundError, json.JSONDecodeError, Exception):
        pass
    # Fallback to Supabase
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
