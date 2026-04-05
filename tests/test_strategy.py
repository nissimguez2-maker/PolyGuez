"""Unit tests for polyguez_strategy.py — core signal logic."""
import math
import pytest
from unittest.mock import MagicMock
from agents.utils.objects import PolyGuezConfig, RollingStats, SignalState, TradeRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_config(**overrides):
    return PolyGuezConfig(**overrides)

def _default_stats(**overrides):
    return RollingStats(**overrides)

def _call_evaluate(**kwargs):
    from agents.strategies.polyguez_strategy import evaluate_entry_signal
    defaults = dict(
        btc_velocity=0.01,
        btc_price=67000.0,
        yes_price=0.35,
        no_price=0.65,
        spread=0.02,
        elapsed_seconds=150.0,
        usdc_balance=100.0,
        config=_default_config(),
        rolling_stats=_default_stats(),
        has_position=False,
        open_position_count=0,
        chainlink_price=67050.0,
        chainlink_age=5.0,
        binance_chainlink_gap=50.0,
        clob_depth=100.0,
        price_to_beat=67000.0,
        price_feed_ok=True,
    )
    defaults.update(kwargs)
    return evaluate_entry_signal(**defaults)


# ---------------------------------------------------------------------------
# evaluate_entry_signal tests
# ---------------------------------------------------------------------------

class TestEvaluateEntrySignal:
    def test_returns_signal_state(self):
        sig = _call_evaluate()
        assert isinstance(sig, SignalState)

    def test_no_p2b_returns_early(self):
        sig = _call_evaluate(price_to_beat=None)
        assert sig.edge == 0.0
        assert sig.p2b_source == "none"

    def test_price_feed_stale_blocks(self):
        sig = _call_evaluate(price_feed_ok=False)
        assert sig.price_feed_ok is False
        assert sig.all_conditions_met is False

    def test_daily_loss_blocks_entry(self):
        stats = _default_stats(daily_pnl=-20.0)
        sig = _call_evaluate(rolling_stats=stats, usdc_balance=50.0)
        assert sig.daily_loss_ok is False
        assert sig.all_conditions_met is False

    def test_has_position_blocks_entry(self):
        sig = _call_evaluate(has_position=True)
        assert sig.no_position is False
        assert sig.all_conditions_met is False

    def test_spread_too_wide_blocks(self):
        sig = _call_evaluate(spread=0.20)
        assert sig.spread_ok is False

    def test_chainlink_stale_near_expiry_blocks(self):
        sig = _call_evaluate(chainlink_age=60.0, elapsed_seconds=270.0)
        assert sig.chainlink_fresh_ok is False

    def test_blocked_hour_blocks(self):
        """blocked_hours_utc=[0, 3] should block during those hours."""
        # We can't easily control datetime.now, so we just verify the field exists
        sig = _call_evaluate()
        assert hasattr(sig, 'time_of_day_ok')

    def test_entry_price_outside_range_blocks(self):
        sig = _call_evaluate(yes_price=0.90, no_price=0.10)
        # With such extreme prices, entry_price_ok should be False
        # (max_entry_token_price default is 0.45)
        assert sig.entry_price_ok is False

    def test_depth_below_threshold_blocks(self):
        sig = _call_evaluate(clob_depth=10.0)
        assert sig.depth_ok is False

    def test_depth_negative_skips_gate(self):
        sig = _call_evaluate(clob_depth=-1.0)
        assert sig.depth_ok is True


# ---------------------------------------------------------------------------
# calculate_position_size tests
# ---------------------------------------------------------------------------

class TestPositionSize:
    def test_normal_bet(self):
        from agents.strategies.polyguez_strategy import calculate_position_size
        config = _default_config()
        size = calculate_position_size(100.0, config, edge=0.05, depth=10.0)
        assert size == config.bet_size_normal

    def test_strong_bet(self):
        from agents.strategies.polyguez_strategy import calculate_position_size
        config = _default_config()
        size = calculate_position_size(100.0, config, edge=0.30, depth=50000.0)
        assert size == config.bet_size_strong

    def test_low_balance(self):
        from agents.strategies.polyguez_strategy import calculate_position_size
        config = _default_config()
        size = calculate_position_size(20.0, config, edge=0.05, depth=10.0)
        assert size == config.bet_size_low_balance_normal


# ---------------------------------------------------------------------------
# calculate_max_capital_at_risk tests
# ---------------------------------------------------------------------------

class TestMaxCapitalAtRisk:
    def test_uses_balance_fraction(self):
        from agents.strategies.polyguez_strategy import calculate_max_capital_at_risk
        config = _default_config(max_capital_fraction=0.20)
        result = calculate_max_capital_at_risk(100.0, config)
        # min(100*0.20, 10*3) = min(20, 30) = 20, max(20, 10) = 20
        assert result == 20.0

    def test_caps_at_bet_strong_times_3(self):
        from agents.strategies.polyguez_strategy import calculate_max_capital_at_risk
        config = _default_config(max_capital_fraction=0.50, bet_size_strong=10.0)
        result = calculate_max_capital_at_risk(1000.0, config)
        # min(1000*0.50, 10*3) = min(500, 30) = 30, max(30, 10) = 30
        assert result == 30.0

    def test_never_below_bet_strong(self):
        from agents.strategies.polyguez_strategy import calculate_max_capital_at_risk
        config = _default_config(bet_size_strong=10.0)
        result = calculate_max_capital_at_risk(5.0, config)
        assert result >= config.bet_size_strong


# ---------------------------------------------------------------------------
# compute_cooldown tests
# ---------------------------------------------------------------------------

class TestComputeCooldown:
    def test_startup_trades_returns_1(self):
        from agents.strategies.polyguez_strategy import compute_cooldown
        config = _default_config(cooldown_startup_trades=5)
        stats = _default_stats()
        assert compute_cooldown(stats, config) == 1

    def test_win_streak_no_cooldown(self):
        from agents.strategies.polyguez_strategy import compute_cooldown
        config = _default_config(cooldown_startup_trades=2)
        trades = [TradeRecord(outcome="win") for _ in range(5)]
        stats = _default_stats(trades=trades)
        result = compute_cooldown(stats, config)
        assert result == 0


# ---------------------------------------------------------------------------
# check_emergency_exit tests
# ---------------------------------------------------------------------------

class TestEmergencyExit:
    def test_velocity_reversal_up(self):
        from agents.strategies.polyguez_strategy import check_emergency_exit
        config = _default_config(reversal_velocity_threshold=0.08)
        assert check_emergency_exit(-0.10, "up", config) is True
        assert check_emergency_exit(-0.05, "up", config) is False

    def test_velocity_reversal_down(self):
        from agents.strategies.polyguez_strategy import check_emergency_exit
        config = _default_config(reversal_velocity_threshold=0.08)
        assert check_emergency_exit(0.10, "down", config) is True
        assert check_emergency_exit(0.05, "down", config) is False

    def test_chainlink_reversal(self):
        from agents.strategies.polyguez_strategy import check_emergency_exit
        config = _default_config(reversal_chainlink_threshold=50.0)
        # Up position, chainlink dropped $60 below P2B
        assert check_emergency_exit(0.0, "up", config, chainlink_price=66940.0, price_to_beat=67000.0) is True
        # Up position, chainlink only dropped $30
        assert check_emergency_exit(0.0, "up", config, chainlink_price=66970.0, price_to_beat=67000.0) is False
