"""PolyGuez Momentum — strategy brain.

Cleanly separated into:
  1. Signal logic  (deterministic, pure functions)
  2. Risk logic    (pure functions)
  3. LLM confirmation logic (async, advisory)
  4. Execution logic (thin wrappers around existing Polymarket plumbing)
"""

import asyncio
import json
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

# ---------------------------------------------------------------------------
# 1. Signal logic — deterministic, no I/O
# ---------------------------------------------------------------------------


def evaluate_entry_signal(
    btc_velocity,
    btc_price,
    yes_price,
    no_price,
    spread,
    elapsed_seconds,
    usdc_balance,
    config,
    rolling_stats,
    has_position,
    open_position_count=0,
    chainlink_price=0.0,
    binance_chainlink_gap=0.0,
):
    """Evaluate all 10 entry conditions (three-price-gap model). Returns a SignalState."""
    direction = "up" if btc_velocity > 0 else "down"

    # Fair value estimate based on momentum direction
    if direction == "up":
        estimated_fv = min(1.0, yes_price + abs(btc_velocity) * 10)
        token_price = yes_price
    else:
        estimated_fv = min(1.0, no_price + abs(btc_velocity) * 10)
        token_price = no_price

    edge = estimated_fv - token_price

    # Time-scaled edge requirement
    if elapsed_seconds <= config.early_window_seconds:
        required_edge = config.min_edge * config.early_edge_multiplier
    elif elapsed_seconds <= config.mid_window_seconds:
        required_edge = config.min_edge * config.mid_edge_multiplier
    else:
        required_edge = config.min_edge * config.late_edge_multiplier

    # Apply tightened criteria after losing streak
    effective_velocity_threshold = config.velocity_threshold
    effective_required_edge = required_edge
    if (
        rolling_stats.total_trades >= config.cooldown_startup_trades
        and rolling_stats.win_rate < config.cooldown_win_rate_short
    ):
        effective_velocity_threshold *= config.cooldown_tightened_multiplier
        effective_required_edge *= config.cooldown_tightened_multiplier

    # Position size for balance check
    pos_size = calculate_position_size(usdc_balance, config)

    # Check cooldown
    cooldown_ok = True
    if rolling_stats.cooldown_until:
        try:
            until = datetime.fromisoformat(rolling_stats.cooldown_until)
            if datetime.now(timezone.utc) < until:
                cooldown_ok = False
        except (ValueError, TypeError):
            pass

    # Oracle gap: Binance-Chainlink gap must exceed min_oracle_gap in the
    # direction that favors the trade (positive gap = Binance ahead for "up")
    gap_favors = False
    if direction == "up" and binance_chainlink_gap > 0:
        gap_favors = True
    elif direction == "down" and binance_chainlink_gap < 0:
        gap_favors = True
    oracle_gap_ok = gap_favors and abs(binance_chainlink_gap) >= config.min_oracle_gap

    # CLOB mispricing: the CLOB token hasn't caught up to the Chainlink move yet
    # If Binance leads Chainlink which leads CLOB, the token price should still
    # be "cheap" relative to fair value from the oracle gap signal.
    clob_mispricing_ok = edge > 0 and token_price < estimated_fv

    signal = SignalState(
        btc_velocity=btc_velocity,
        btc_price=btc_price,
        chainlink_price=chainlink_price,
        binance_chainlink_gap=binance_chainlink_gap,
        yes_price=yes_price,
        no_price=no_price,
        spread=spread,
        elapsed_seconds=elapsed_seconds,
        direction=direction,
        estimated_fair_value=estimated_fv,
        edge=edge,
        required_edge=effective_required_edge,
        gap_favors_position=gap_favors,
        velocity_ok=abs(btc_velocity) > effective_velocity_threshold,
        oracle_gap_ok=oracle_gap_ok,
        clob_mispricing_ok=clob_mispricing_ok,
        edge_ok=edge > effective_required_edge,
        spread_ok=spread < config.max_spread,
        no_position=not has_position,
        cooldown_ok=cooldown_ok,
        daily_loss_ok=check_daily_loss_limit(rolling_stats, config, usdc_balance),
        balance_ok=usdc_balance >= pos_size and usdc_balance >= config.min_capital_floor,
        position_limit_ok=open_position_count < config.max_open_positions,
    )
    return signal


# ---------------------------------------------------------------------------
# 2. Risk logic — pure functions
# ---------------------------------------------------------------------------


def calculate_position_size(usdc_balance, config):
    """Compute position size ceiling in USDC."""
    max_capital = usdc_balance * config.max_capital_pct
    if max_capital < config.min_capital_floor:
        max_capital = config.min_capital_floor
    pos_size = max_capital * config.position_size_pct
    return round(pos_size, 2)


def calculate_max_capital_at_risk(usdc_balance, config):
    """Compute max capital at risk for the current cycle."""
    cap = usdc_balance * config.max_capital_pct
    if cap < config.min_capital_floor:
        cap = config.min_capital_floor
    return round(cap, 2)


def check_daily_loss_limit(rolling_stats, config, usdc_balance):
    """Return True if trading is still allowed under the daily loss limit."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if rolling_stats.daily_pnl_reset_utc != today:
        return True  # New day, reset will happen in the runner
    limit = config.max_daily_loss
    if limit is None:
        limit = calculate_max_capital_at_risk(usdc_balance, config)
    return rolling_stats.daily_pnl > -abs(limit)


def compute_cooldown(rolling_stats, config):
    """Return cooldown duration in cycles (0 = no cooldown).

    Follows the adaptive cooldown spec.
    """
    total = rolling_stats.total_trades
    if total < config.cooldown_startup_trades:
        return 1  # Conservative startup

    if not rolling_stats.trades:
        return 0

    last_trade = rolling_stats.trades[-1]
    wr = rolling_stats.win_rate

    if last_trade.outcome == "win":
        if wr >= config.cooldown_win_rate_no_cooldown:
            return 0
        return config.cooldown_cycles_short
    else:  # loss or emergency-exit
        if wr >= config.cooldown_win_rate_short:
            return config.cooldown_cycles_short
        return config.cooldown_cycles_long


def check_emergency_exit(btc_velocity, entry_direction, config, chainlink_price=0.0, price_to_beat=0.0):
    """Return True if an emergency exit should be triggered.

    Primary: Chainlink price reversal vs price_to_beat exceeds threshold.
    Fallback: velocity-based reversal when Chainlink data unavailable.
    """
    # Chainlink-based exit (primary): if the Chainlink oracle has already
    # moved against our position by more than reversal_threshold
    if chainlink_price > 0 and price_to_beat > 0:
        chainlink_move = chainlink_price - price_to_beat
        if entry_direction == "up" and chainlink_move < -config.reversal_threshold:
            return True
        if entry_direction == "down" and chainlink_move > config.reversal_threshold:
            return True
        return False

    # Velocity-based fallback (when Chainlink data unavailable)
    if entry_direction == "up" and btc_velocity < -config.reversal_threshold:
        return True
    if entry_direction == "down" and btc_velocity > config.reversal_threshold:
        return True
    return False


# ---------------------------------------------------------------------------
# 3. LLM confirmation logic — async, advisory
# ---------------------------------------------------------------------------


async def get_llm_confirmation(signal_state, rolling_stats, config, price_to_beat=0.0, gap_direction="unknown", clob_depth_summary=""):
    """Run LLM confirmation with data providers. Returns (verdict, reason, provider, response_time)."""
    if not config.llm_enabled:
        return ("GO", "llm-disabled", "", 0.0)

    start = asyncio.get_event_loop().time()

    # Gather external context from data providers
    market_context = {
        "direction": signal_state.direction,
        "velocity": signal_state.btc_velocity,
        "market_question": "",
        "elapsed_seconds": signal_state.elapsed_seconds,
        "binance_chainlink_gap": signal_state.binance_chainlink_gap,
    }
    context_data = await fetch_all_providers(
        config.data_providers, market_context, timeout=config.data_provider_timeout,
    )

    # Format context for prompt
    context_str = ""
    for source, data in context_data.items():
        if "headlines" in data:
            context_str += f"NewsAPI headlines: {', '.join(data['headlines'][:5])}\n"
        if "context" in data and data["context"]:
            context_str += f"Web search: {data['context'][:500]}\n"
        if source == "chainlink" and data.get("price"):
            context_str += f"Chainlink on-chain: ${data['price']:.2f}\n"
        if "error" in data:
            context_str += f"({source} unavailable: {data['error']})\n"
    if not context_str:
        context_str = "(no external context available)"

    # Format recent trades
    recent = rolling_stats.last_n_trades
    if recent:
        trade_lines = []
        for t in recent[-5:]:
            trade_lines.append(f"  {t.outcome}: P&L={t.pnl or 0:.2f}, side={t.side}")
        trades_summary = "\n".join(trade_lines)
    else:
        trades_summary = "(no recent trades)"

    prompt = _prompter.momentum_confirmation(
        velocity=signal_state.btc_velocity,
        direction=signal_state.direction,
        yes_price=signal_state.yes_price,
        no_price=signal_state.no_price,
        spread=signal_state.spread,
        elapsed_seconds=signal_state.elapsed_seconds,
        win_rate=rolling_stats.win_rate,
        recent_trades_summary=trades_summary,
        context_data=context_str,
        chainlink_price=signal_state.chainlink_price,
        binance_chainlink_gap=signal_state.binance_chainlink_gap,
        gap_direction=gap_direction,
        price_to_beat=price_to_beat,
        clob_depth_summary=clob_depth_summary,
    )

    adapter = get_llm_adapter(config)
    remaining = config.llm_timeout - (asyncio.get_event_loop().time() - start)
    remaining = max(remaining, 1.0)

    verdict, reason = await adapter.confirm_trade(prompt, timeout=remaining)
    elapsed = asyncio.get_event_loop().time() - start

    log_event(logger, "llm_verdict", f"LLM ({adapter.name}): {verdict}", {
        "verdict": verdict,
        "reason": reason,
        "provider": adapter.name,
        "response_time": round(elapsed, 2),
    })

    return (verdict, reason, adapter.name, round(elapsed, 2))


# ---------------------------------------------------------------------------
# 4. Execution logic — thin wrappers
# ---------------------------------------------------------------------------


async def execute_entry(polymarket_client, token_id, size_usdc, mode):
    """Execute a market buy order. Returns order result dict.

    In dry-run/paper mode, simulates the fill.
    """
    if mode == "live":
        loop = asyncio.get_event_loop()
        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType

            order_args = MarketOrderArgs(token_id=token_id, amount=size_usdc)
            signed = await loop.run_in_executor(
                None, polymarket_client.client.create_market_order, order_args,
            )
            resp = await loop.run_in_executor(
                None, lambda: polymarket_client.client.post_order(signed, orderType=OrderType.FOK),
            )
            log_event(logger, "order_executed", f"LIVE order posted", {"response": str(resp)})
            return {"status": "filled", "response": resp}
        except Exception as exc:
            log_event(logger, "order_error", f"Execution failed: {exc}", level=40)
            return {"status": "error", "error": str(exc)}
    else:
        tag = "[DRY-RUN]" if mode == "dry-run" else "[PAPER]"
        log_event(logger, "order_simulated", f"{tag} Simulated buy {size_usdc} USDC on {token_id}")
        return {"status": "simulated", "mode": mode}


async def execute_emergency_exit(polymarket_client, position, mode):
    """Market-sell the current position for emergency exit."""
    log_event(logger, "emergency_exit", "EMERGENCY EXIT — velocity reversal exceeded threshold", {
        "side": position.side,
        "token_id": position.token_id,
        "entry_price": position.entry_price,
    })

    if mode == "live":
        loop = asyncio.get_event_loop()
        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType

            # Sell the opposite token or sell current position
            order_args = MarketOrderArgs(token_id=position.token_id, amount=position.size_usdc)
            signed = await loop.run_in_executor(
                None, polymarket_client.client.create_market_order, order_args,
            )
            resp = await loop.run_in_executor(
                None, lambda: polymarket_client.client.post_order(signed, orderType=OrderType.FOK),
            )
            log_event(logger, "emergency_exit_executed", "Emergency exit order filled", {"response": str(resp)})
            return {"status": "filled", "response": resp}
        except Exception as exc:
            log_event(logger, "emergency_exit_error", f"Emergency exit failed: {exc}", level=40)
            return {"status": "error", "error": str(exc)}
    else:
        tag = "[DRY-RUN]" if mode == "dry-run" else "[PAPER]"
        log_event(logger, "emergency_exit_simulated", f"{tag} Simulated emergency exit")
        return {"status": "simulated", "mode": mode}


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_HISTORY_FILE = os.path.join(_DATA_DIR, "trade_history.json")


def save_rolling_stats(stats):
    """Persist RollingStats to data/trade_history.json."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_HISTORY_FILE, "w") as f:
        f.write(stats.json(indent=2))


def load_rolling_stats():
    """Load RollingStats from disk, or return fresh instance."""
    try:
        with open(_HISTORY_FILE, "r") as f:
            return RollingStats.parse_raw(f.read())
    except (FileNotFoundError, json.JSONDecodeError, Exception):
        return RollingStats()
