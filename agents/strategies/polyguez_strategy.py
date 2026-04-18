"""PolyGuez Momentum — strategy brain."""

import asyncio
import json
import math
import os
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

logger = get_logger("polyguez.strategy")
_prompter = Prompter()


def _linear_edge_for_remaining(remaining_seconds, base, close, window=300.0):
    """LATENCY-TASK-6: linearly interpolate the required edge.

    `base` is the edge required at the start of the window
    (remaining == window). `close` is the edge required at expiry
    (remaining == 0). When remaining falls in between, we interpolate
    so late entries must clear a strictly higher bar. Degrades
    gracefully: if base >= close, returns max(base, close) — the
    step config is still a valid linear config.
    """
    if window <= 0:
        return max(base, close)
    r = max(0.0, min(float(remaining_seconds), float(window)))
    # `frac_elapsed` is 0 at window start, 1 at close. We interpolate
    # from `base` toward `close` as frac_elapsed increases.
    frac_elapsed = 1.0 - (r / window)
    return base + (close - base) * frac_elapsed


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

    # Terminal probability via logistic model.
    # MODEL-06(a): `k` is sourced from PolyGuezConfig.k_logistic rather than
    # a module-level constant. Effective k still decays as
    # 1/sqrt(seconds_remaining / 60.0) — that time-scaling stays hardcoded.
    strike_delta = chainlink_price - price_to_beat
    seconds_remaining = max(1.0, 300.0 - elapsed_seconds)
    k_prior = getattr(config, "k_logistic", 0.035)
    k = k_prior / math.sqrt(seconds_remaining / 60.0)
    clamped = max(-500.0, min(500.0, -k * strike_delta))
    terminal_probability_yes = 1.0 / (1.0 + math.exp(clamped))

    # Delta direction (from Chainlink vs P2B) — used for v2 terminal probability
    # This is what actually matters: which side is the oracle favoring?
    delta_direction = "up" if strike_delta >= 0 else "down"

    # Use delta_direction as the primary direction for entry decisions
    direction = delta_direction

    # Velocity-delta agreement: warn when momentum opposes delta direction
    velocity_agrees = (btc_velocity > 0 and delta_direction == "up") or (btc_velocity < 0 and delta_direction == "down")

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
    # Fee-adjusted edge: subtract the expected Polymarket fee drag at this
    # token price. Logged for calibration; NOT (yet) used to gate entries —
    # see CLAUDE.md rule on not changing signal gates without calibrated
    # outcome data, and docs/k_recalibration_2026_04_16.md Phase 1.
    _fee_coef = getattr(config, "taker_fee_coefficient", 0.072)
    net_edge = terminal_edge - _fee_coef * token_price * (1.0 - token_price)

    # LATENCY-TASK-6: edge requirement scales with time-to-expiry. "step"
    # (legacy) uses three coarse buckets; "linear" interpolates from
    # edge_scaling_base (at window start) to edge_scaling_close (at
    # window close), and applies the same interpolation to the
    # terminal-edge gate below. Step mode is the default for backwards
    # compatibility.
    _edge_mode = getattr(config, "edge_scaling_mode", "step")
    min_terminal_edge_eff = config.min_terminal_edge
    if _edge_mode == "linear":
        required_edge = _linear_edge_for_remaining(
            seconds_remaining,
            base=config.edge_scaling_base,
            close=config.edge_scaling_close,
        )
        # Mirror the same interpolation onto the terminal-edge gate so
        # late-window entries also need a strictly larger terminal edge.
        min_terminal_edge_eff = _linear_edge_for_remaining(
            seconds_remaining,
            base=config.min_terminal_edge,
            close=max(config.min_terminal_edge,
                      config.edge_scaling_close * (config.min_terminal_edge / max(config.edge_scaling_base, 1e-9))),
        )
    else:
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
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
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
    # LATENCY-TASK-6: terminal-edge gate uses the time-scaled threshold
    # when linear mode is on; otherwise identical to the legacy check.
    terminal_edge_ok = terminal_edge > min_terminal_edge_eff

    # Use strict delta threshold in fast-moving markets
    fast_market = abs(btc_velocity) > config.velocity_threshold * 3
    active_delta_threshold = config.conviction_min_delta_strict if fast_market else config.conviction_min_delta
    delta_magnitude_ok = abs(strike_delta) > active_delta_threshold

    # Stale Chainlink guard near expiry
    chainlink_fresh_ok = True
    if chainlink_age > config.chainlink_stale_max_age and seconds_remaining < config.chainlink_stale_expiry_window:
        chainlink_fresh_ok = False
        log_event(logger, "signal_stale_cl",
            f"[SIGNAL] chainlink_stale age={chainlink_age:.1f}s seconds_remaining={seconds_remaining:.0f}s → blocked")

    # CLOB consensus: don't trade against overwhelming market consensus
    our_price = yes_price if direction == "up" else no_price
    clob_consensus_ok = our_price >= config.min_clob_consensus

    # V4: Time-of-day filter
    current_hour_utc = datetime.now(timezone.utc).hour
    time_of_day_ok = current_hour_utc not in config.blocked_hours_utc

    # V4: Entry price sweet-spot filter
    entry_token_price = yes_price if direction == "up" else no_price
    entry_price_ok = config.min_entry_token_price <= entry_token_price <= config.max_entry_token_price

    # V4: Direction mode filter
    direction_ok = (config.direction_mode == "both" or config.direction_mode == direction)

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
        (time_of_day_ok, f"blocked_hour_utc={current_hour_utc}"),
        (entry_price_ok, f"entry_price={entry_token_price:.3f}_outside_{config.min_entry_token_price}-{config.max_entry_token_price}"),
        (direction_ok, f"direction={direction}_blocked_by_{config.direction_mode}"),
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
        oracle_gap_ok=oracle_gap_ok,
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
        net_edge=net_edge,
        terminal_edge_ok=terminal_edge_ok,
        delta_magnitude_ok=delta_magnitude_ok,
        time_of_day_ok=time_of_day_ok,
        entry_price_ok=entry_price_ok,
        direction_ok=direction_ok,
        price_feed_ok=price_feed_ok,
        velocity_agrees_direction=velocity_agrees,
    )


def calculate_position_size(usdc_balance, config, edge=0.0, depth=0.0, size_multiplier=1.0):
    # Edge-scaled sizing: fractional Kelly interpolation between normal and strong
    if getattr(config, 'edge_scaled_sizing', False):
        if usdc_balance < config.low_balance_threshold:
            base = config.bet_size_low_balance_normal
            top = config.bet_size_low_balance_strong
        else:
            base = config.bet_size_normal
            top = config.bet_size_strong
        edge_range = config.strong_edge_threshold - config.min_edge
        if edge_range > 0:
            frac = max(0.0, min(1.0, (edge - config.min_edge) / edge_range))
        else:
            frac = 1.0 if edge >= config.strong_edge_threshold else 0.0
        raw = base + (top - base) * frac
    else:
        # Original binary tier logic
        is_strong = edge >= config.strong_edge_threshold and depth >= config.strong_depth_threshold
        if usdc_balance < config.low_balance_threshold:
            raw = config.bet_size_low_balance_strong if is_strong else config.bet_size_low_balance_normal
        else:
            raw = config.bet_size_strong if is_strong else config.bet_size_normal
    # Cap individual bet by max_capital_fraction
    max_bet = usdc_balance * getattr(config, 'max_capital_fraction', 0.20)
    sized = min(raw, max_bet) if max_bet > 0 else raw
    # Apply daily loss tier multiplier (tiered reduction, not hard stop)
    return sized * max(0.0, min(1.0, size_multiplier))


def calculate_max_capital_at_risk(usdc_balance, config):
    fraction = getattr(config, 'max_capital_fraction', 0.20)
    computed = min(usdc_balance * fraction, config.bet_size_strong * 3)
    result = max(computed, config.bet_size_strong)
    return result


def check_daily_loss_limit(rolling_stats, config, usdc_balance):
    # In dry-run / paper mode the daily loss limit is meaningless — it's a sandbox.
    # Only enforce in live mode where real capital is at risk.
    if getattr(config, "mode", "dry-run") != "live":
        return True
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if rolling_stats.daily_pnl_reset_utc != today:
        return True
    limit = config.max_daily_loss
    if limit is None:
        limit = calculate_max_capital_at_risk(usdc_balance, config)
    return rolling_stats.daily_pnl > -abs(limit)


def get_daily_loss_size_multiplier(rolling_stats, config, usdc_balance):
    """Tiered daily loss reduction: reduces position size before hard stop.

    Tiers (relative to max_daily_loss):
      - 0%  → 50% of limit: full size (1.0)
      - 50% → 75% of limit: reduce to 50% sizing
      - 75% → 100% of limit: reduce to 25% sizing
      - >= 100% of limit: hard stop (0.0) — check_daily_loss_limit also returns False here
    """
    # In dry-run / paper mode: always full size, no daily loss reduction.
    if getattr(config, "mode", "dry-run") != "live":
        return 1.0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if rolling_stats.daily_pnl_reset_utc != today:
        return 1.0  # New day, full size
    limit = config.max_daily_loss
    if limit is None:
        limit = calculate_max_capital_at_risk(usdc_balance, config)
    limit = abs(limit)
    loss = -rolling_stats.daily_pnl  # positive number = loss
    if loss < limit * 0.50:
        return 1.0    # Tier 0: full size
    elif loss < limit * 0.75:
        log_event(logger, "daily_loss_tier",
            f"[RISK] Daily loss ${loss:.2f} → Tier 1 (50–75% limit): sizing reduced to 50%")
        return 0.5    # Tier 1: half size
    elif loss < limit * 1.00:
        log_event(logger, "daily_loss_tier",
            f"[RISK] Daily loss ${loss:.2f} → Tier 2 (75–100% limit): sizing reduced to 25%")
        return 0.25   # Tier 2: quarter size
    else:
        return 0.0    # Tier 3: hard stop (duplicates check_daily_loss_limit behaviour)


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
        # Fall through to velocity check as secondary exit trigger
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
                    # Dynamic timeout based on seconds_remaining
                    max_wait = min(30.0, max(5.0, seconds_remaining * 0.4))
                    polls = int(max_wait / 2)
                    # Poll for fill confirmation
                    order_id = None
                    if isinstance(resp, dict):
                        order_id = resp.get("orderID") or resp.get("id")
                    elif hasattr(resp, 'orderID'):
                        order_id = resp.orderID
                    if order_id:
                        for _poll in range(polls):
                            await asyncio.sleep(2)
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
        except Exception as exc:
            logger.warning(f"[STATS] Trade archive failed: {exc}")

    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_HISTORY_FILE, "w") as f:
        f.write(stats.model_dump_json(indent=2))
    # Upsert to Supabase as durable backup + verify
    try:
        from agents.utils.supabase_logger import _client
        client = _client()
        if client:
            stats_data = stats.model_dump()
            written_at = datetime.now(timezone.utc).isoformat()
            stats_data["updated_at"] = written_at
            # Surface computed @property values into the persisted blob so
            # downstream readers (refresh_context.py, dashboard, any ad-hoc
            # SQL) see real numbers instead of null. RollingStats.model_dump()
            # skips @property by design; we inject them explicitly.
            stats_data["trade_count"] = stats.total_trades
            stats_data["total_pnl"] = stats.total_pnl
            stats_data["wins"] = stats.total_wins
            stats_data["losses"] = stats.total_losses
            stats_data["win_rate"] = stats.win_rate
            client.table("rolling_stats").upsert({
                "id": "singleton",
                "data": stats_data,
            }).execute()
            # Verify write-back: confirm the persisted updated_at matches what we just wrote.
            # A "row exists" check was insufficient — a silently-cached/failed write would still
            # return the stale row and pass. Comparing updated_at catches real write failures.
            verify = client.table("rolling_stats").select("data").eq("id", "singleton").execute()
            if not verify.data:
                logger.error("[STATS] Supabase write-back verification FAILED — row not found after upsert")
            else:
                persisted = (verify.data[0].get("data") or {}).get("updated_at")
                if persisted != written_at:
                    logger.error(
                        f"[STATS] Supabase write-back verification FAILED — "
                        f"persisted updated_at={persisted} != written_at={written_at}"
                    )
    except Exception as exc:
        logger.error(f"[STATS] Supabase save failed — stats may be lost on redeploy: {exc}")


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
