"""PolyGuez strategy core — pure signal evaluation, sizing, and risk functions.

Contains the deterministic, side-effect-free functions extracted from
polyguez_strategy.py. No IO, no LLM calls, no Supabase writes.
polyguez_strategy.py re-exports everything from here for backwards compatibility.
"""

import math
from datetime import datetime, timezone

from agents.utils.logger import get_logger, log_event
from agents.utils.objects import SignalState

logger = get_logger("polyguez.strategy")


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

    delta_direction = "up" if strike_delta >= 0 else "down"
    direction = delta_direction
    velocity_agrees = (btc_velocity > 0 and delta_direction == "up") or (btc_velocity < 0 and delta_direction == "down")

    if delta_direction == "up":
        selected_side_probability = terminal_probability_yes
        token_price = yes_price
    else:
        selected_side_probability = 1.0 - terminal_probability_yes
        token_price = no_price

    estimated_fv = selected_side_probability
    terminal_edge = selected_side_probability - token_price
    edge = estimated_fv - token_price
    _fee_coef = getattr(config, "taker_fee_coefficient", 0.072)
    net_edge = terminal_edge - _fee_coef * token_price * (1.0 - token_price)

    _edge_mode = getattr(config, "edge_scaling_mode", "step")
    min_terminal_edge_eff = config.min_terminal_edge
    if _edge_mode == "linear":
        required_edge = _linear_edge_for_remaining(
            seconds_remaining,
            base=config.edge_scaling_base,
            close=config.edge_scaling_close,
        )
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

    clob_mispricing_ok = edge > 0 and token_price < estimated_fv  # noqa: F841
    depth_ok = True if clob_depth < 0 else clob_depth >= config.min_clob_depth
    terminal_edge_ok = terminal_edge > min_terminal_edge_eff
    _min_net = getattr(config, "min_net_edge", 0.0)
    net_edge_ok = (net_edge >= _min_net) if _min_net > 0.0 else True

    fast_market = abs(btc_velocity) > config.velocity_threshold * 3
    active_delta_threshold = config.conviction_min_delta_strict if fast_market else config.conviction_min_delta
    delta_magnitude_ok = abs(strike_delta) > active_delta_threshold

    chainlink_fresh_ok = True
    if chainlink_age > config.chainlink_stale_max_age and seconds_remaining < config.chainlink_stale_expiry_window:
        chainlink_fresh_ok = False
        log_event(logger, "signal_stale_cl",
            f"[SIGNAL] chainlink_stale age={chainlink_age:.1f}s seconds_remaining={seconds_remaining:.0f}s → blocked")

    our_price = yes_price if direction == "up" else no_price
    clob_consensus_ok = our_price >= config.min_clob_consensus
    current_hour_utc = datetime.now(timezone.utc).hour
    time_of_day_ok = current_hour_utc not in config.blocked_hours_utc
    entry_token_price = yes_price if direction == "up" else no_price
    entry_price_ok = config.min_entry_token_price <= entry_token_price <= config.max_entry_token_price
    direction_ok = (config.direction_mode == "both" or config.direction_mode == direction)

    _velocity_ok = abs(btc_velocity) > effective_velocity_threshold
    _edge_ok = edge > effective_required_edge
    _spread_ok = spread < config.max_spread
    _no_position = not has_position
    _daily_loss_ok = check_daily_loss_limit(rolling_stats, config, usdc_balance)
    _balance_ok = usdc_balance >= pos_size
    _position_limit_ok = open_position_count < config.max_open_positions

    _conditions = [
        (price_feed_ok, "price_feed_stale"),
        (chainlink_fresh_ok, f"stale_chainlink={chainlink_age:.0f}s_near_expiry"),
        (terminal_edge_ok, f"terminal_edge={terminal_edge:.4f}<{config.min_terminal_edge}"),
        (net_edge_ok, f"net_edge={net_edge:.4f}<{_min_net}"),
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
        net_edge_ok=net_edge_ok,
        delta_magnitude_ok=delta_magnitude_ok,
        time_of_day_ok=time_of_day_ok,
        entry_price_ok=entry_price_ok,
        direction_ok=direction_ok,
        price_feed_ok=price_feed_ok,
        velocity_agrees_direction=velocity_agrees,
    )


def calculate_position_size(usdc_balance, config, edge=0.0, depth=0.0, size_multiplier=1.0):
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
        is_strong = edge >= config.strong_edge_threshold and depth >= config.strong_depth_threshold
        if usdc_balance < config.low_balance_threshold:
            raw = config.bet_size_low_balance_strong if is_strong else config.bet_size_low_balance_normal
        else:
            raw = config.bet_size_strong if is_strong else config.bet_size_normal
    max_bet = usdc_balance * getattr(config, 'max_capital_fraction', 0.20)
    sized = min(raw, max_bet) if max_bet > 0 else raw
    return sized * max(0.0, min(1.0, size_multiplier))


def calculate_max_capital_at_risk(usdc_balance, config):
    fraction = getattr(config, 'max_capital_fraction', 0.20)
    computed = min(usdc_balance * fraction, config.bet_size_strong * 3)
    result = max(computed, config.bet_size_strong)
    return result


def check_daily_loss_limit(rolling_stats, config, usdc_balance):
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
    """Tiered daily loss reduction: reduces position size before hard stop."""
    if getattr(config, "mode", "dry-run") != "live":
        return 1.0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if rolling_stats.daily_pnl_reset_utc != today:
        return 1.0
    limit = config.max_daily_loss
    if limit is None:
        limit = calculate_max_capital_at_risk(usdc_balance, config)
    limit = abs(limit)
    loss = -rolling_stats.daily_pnl
    if loss < limit * 0.50:
        return 1.0
    elif loss < limit * 0.75:
        log_event(logger, "daily_loss_tier",
            f"[RISK] Daily loss ${loss:.2f} → Tier 1 (50–75% limit): sizing reduced to 50%")
        return 0.5
    elif loss < limit * 1.00:
        log_event(logger, "daily_loss_tier",
            f"[RISK] Daily loss ${loss:.2f} → Tier 2 (75–100% limit): sizing reduced to 25%")
        return 0.25
    else:
        return 0.0


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
    if entry_direction == "up" and btc_velocity < -config.reversal_velocity_threshold:
        return True
    if entry_direction == "down" and btc_velocity > config.reversal_velocity_threshold:
        return True
    return False


def compute_clob_depth(order_book, side):
    """FIX 2: Compute ask-side depth within $0.05 of best price."""
    if not order_book:
        return 0.0
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
