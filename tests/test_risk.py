"""Tests for PolyGuez Momentum risk logic."""

import unittest
from datetime import datetime, timedelta, timezone

from agents.strategies.polyguez_strategy import (
    check_daily_loss_limit,
    check_emergency_exit,
    compute_cooldown,
    settle_with_retry,
)
from agents.utils.objects import PolyGuezConfig, RollingStats, TradeRecord


def _default_config(**overrides):
    return PolyGuezConfig(**overrides)


def _stats_with_trades(outcomes, pnls=None):
    stats = RollingStats()
    for i, outcome in enumerate(outcomes):
        pnl = (pnls[i] if pnls else (0.5 if outcome == "win" else -0.5))
        stats.trades.append(TradeRecord(outcome=outcome, pnl=pnl, side="YES"))
    return stats


class TestDailyLossLimit(unittest.TestCase):

    def test_under_limit(self):
        config = _default_config(max_capital_pct=0.10)
        stats = RollingStats(daily_pnl=-5.0, daily_pnl_reset_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        self.assertTrue(check_daily_loss_limit(stats, config, usdc_balance=100.0))

    def test_at_limit(self):
        config = _default_config(max_capital_pct=0.10)
        stats = RollingStats(daily_pnl=-10.0, daily_pnl_reset_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        self.assertFalse(check_daily_loss_limit(stats, config, usdc_balance=100.0))

    def test_over_limit(self):
        config = _default_config(max_capital_pct=0.10)
        stats = RollingStats(daily_pnl=-15.0, daily_pnl_reset_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        self.assertFalse(check_daily_loss_limit(stats, config, usdc_balance=100.0))

    def test_custom_override(self):
        config = _default_config(max_daily_loss=5.0)
        stats = RollingStats(daily_pnl=-4.0, daily_pnl_reset_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        self.assertTrue(check_daily_loss_limit(stats, config, usdc_balance=100.0))

    def test_custom_override_exceeded(self):
        config = _default_config(max_daily_loss=5.0)
        stats = RollingStats(daily_pnl=-6.0, daily_pnl_reset_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        self.assertFalse(check_daily_loss_limit(stats, config, usdc_balance=100.0))

    def test_new_day_resets(self):
        config = _default_config(max_capital_pct=0.10)
        stats = RollingStats(daily_pnl=-50.0, daily_pnl_reset_utc="2020-01-01")
        self.assertTrue(check_daily_loss_limit(stats, config, usdc_balance=100.0))


class TestEmergencyExit(unittest.TestCase):
    """FIX 1: Tests use the new split threshold fields."""

    # -- Velocity-based fallback (no Chainlink data) -----------------------

    def test_no_reversal(self):
        config = _default_config(reversal_velocity_threshold=0.08)
        self.assertFalse(check_emergency_exit(0.05, "up", config))

    def test_small_reversal_no_exit(self):
        config = _default_config(reversal_velocity_threshold=0.08)
        self.assertFalse(check_emergency_exit(-0.05, "up", config))

    def test_reversal_exceeds_threshold_up(self):
        config = _default_config(reversal_velocity_threshold=0.08)
        self.assertTrue(check_emergency_exit(-0.10, "up", config))

    def test_reversal_exceeds_threshold_down(self):
        config = _default_config(reversal_velocity_threshold=0.08)
        self.assertTrue(check_emergency_exit(0.10, "down", config))

    def test_same_direction_no_exit(self):
        config = _default_config(reversal_velocity_threshold=0.08)
        self.assertFalse(check_emergency_exit(0.10, "up", config))

    def test_exact_threshold_no_exit(self):
        config = _default_config(reversal_velocity_threshold=0.08)
        self.assertFalse(check_emergency_exit(-0.08, "up", config))

    # -- Chainlink-based exit (primary) — now uses reversal_chainlink_threshold

    def test_chainlink_reversal_up_triggers_exit(self):
        config = _default_config(reversal_chainlink_threshold=50.0)
        self.assertTrue(check_emergency_exit(
            0.05, "up", config,
            chainlink_price=64940.0, price_to_beat=65000.0,
        ))

    def test_chainlink_reversal_down_triggers_exit(self):
        config = _default_config(reversal_chainlink_threshold=50.0)
        self.assertTrue(check_emergency_exit(
            -0.05, "down", config,
            chainlink_price=65060.0, price_to_beat=65000.0,
        ))

    def test_chainlink_no_reversal(self):
        config = _default_config(reversal_chainlink_threshold=50.0)
        self.assertFalse(check_emergency_exit(
            0.05, "up", config,
            chainlink_price=64970.0, price_to_beat=65000.0,
        ))

    def test_chainlink_favorable_move_no_exit(self):
        config = _default_config(reversal_chainlink_threshold=50.0)
        self.assertFalse(check_emergency_exit(
            0.05, "up", config,
            chainlink_price=65100.0, price_to_beat=65000.0,
        ))

    def test_chainlink_overrides_velocity(self):
        config = _default_config(reversal_chainlink_threshold=50.0)
        self.assertFalse(check_emergency_exit(
            -1.0, "up", config,
            chainlink_price=65010.0, price_to_beat=65000.0,
        ))

    # -- FIX 1: Verify the two thresholds are independent --

    def test_velocity_threshold_independent_of_chainlink(self):
        config = _default_config(
            reversal_velocity_threshold=0.05,
            reversal_chainlink_threshold=100.0,
        )
        self.assertTrue(check_emergency_exit(-0.06, "up", config))
        self.assertFalse(check_emergency_exit(-0.04, "up", config))

    def test_chainlink_threshold_independent_of_velocity(self):
        config = _default_config(
            reversal_velocity_threshold=0.05,
            reversal_chainlink_threshold=30.0,
        )
        self.assertTrue(check_emergency_exit(
            0.01, "up", config,
            chainlink_price=64965.0, price_to_beat=65000.0,
        ))
        self.assertFalse(check_emergency_exit(
            0.01, "up", config,
            chainlink_price=64975.0, price_to_beat=65000.0,
        ))


class TestAdaptiveCooldown(unittest.TestCase):

    def test_startup_conservative(self):
        config = _default_config(cooldown_startup_trades=5)
        stats = _stats_with_trades(["win", "win"])
        self.assertEqual(compute_cooldown(stats, config), 1)

    def test_win_high_win_rate_no_cooldown(self):
        config = _default_config(
            cooldown_startup_trades=5,
            cooldown_win_rate_no_cooldown=0.60,
        )
        stats = _stats_with_trades(["loss"] * 3 + ["win"] * 7)
        self.assertEqual(compute_cooldown(stats, config), 0)

    def test_win_low_win_rate_1_cycle(self):
        config = _default_config(
            cooldown_startup_trades=5,
            cooldown_win_rate_no_cooldown=0.60,
            cooldown_cycles_short=1,
        )
        stats = _stats_with_trades(["loss"] * 5 + ["win"] * 5)
        self.assertEqual(compute_cooldown(stats, config), 1)

    def test_loss_high_win_rate_1_cycle(self):
        config = _default_config(
            cooldown_startup_trades=5,
            cooldown_win_rate_short=0.50,
            cooldown_cycles_short=1,
        )
        stats = _stats_with_trades(["win"] * 6 + ["loss"] * 4)
        self.assertEqual(compute_cooldown(stats, config), 1)

    def test_loss_low_win_rate_2_cycles(self):
        config = _default_config(
            cooldown_startup_trades=5,
            cooldown_win_rate_short=0.50,
            cooldown_cycles_long=2,
        )
        stats = _stats_with_trades(["win"] * 3 + ["loss"] * 7)
        self.assertEqual(compute_cooldown(stats, config), 2)

    def test_empty_trades(self):
        config = _default_config(cooldown_startup_trades=5)
        stats = RollingStats()
        self.assertEqual(compute_cooldown(stats, config), 1)


if __name__ == "__main__":
    unittest.main()
