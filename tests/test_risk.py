"""Tests for PolyGuez Momentum risk logic."""

import unittest
from datetime import datetime, timedelta, timezone

from agents.strategies.polyguez_strategy import (
    check_daily_loss_limit,
    check_emergency_exit,
    compute_cooldown,
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
        # max capital at risk for $100 = $10, daily loss limit = $10
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
        # Different day → always returns True (reset will happen in runner)
        self.assertTrue(check_daily_loss_limit(stats, config, usdc_balance=100.0))


class TestEmergencyExit(unittest.TestCase):

    def test_no_reversal(self):
        config = _default_config(reversal_threshold=0.08)
        self.assertFalse(check_emergency_exit(0.05, "up", config))

    def test_small_reversal_no_exit(self):
        config = _default_config(reversal_threshold=0.08)
        self.assertFalse(check_emergency_exit(-0.05, "up", config))

    def test_reversal_exceeds_threshold_up(self):
        config = _default_config(reversal_threshold=0.08)
        self.assertTrue(check_emergency_exit(-0.10, "up", config))

    def test_reversal_exceeds_threshold_down(self):
        config = _default_config(reversal_threshold=0.08)
        self.assertTrue(check_emergency_exit(0.10, "down", config))

    def test_same_direction_no_exit(self):
        config = _default_config(reversal_threshold=0.08)
        self.assertFalse(check_emergency_exit(0.10, "up", config))

    def test_exact_threshold_no_exit(self):
        """At exactly the threshold — not exceeded, so no exit."""
        config = _default_config(reversal_threshold=0.08)
        self.assertFalse(check_emergency_exit(-0.08, "up", config))


class TestAdaptiveCooldown(unittest.TestCase):

    def test_startup_conservative(self):
        """Fewer than 5 trades → always 1 cycle cooldown."""
        config = _default_config(cooldown_startup_trades=5)
        stats = _stats_with_trades(["win", "win"])
        self.assertEqual(compute_cooldown(stats, config), 1)

    def test_win_high_win_rate_no_cooldown(self):
        """Win with >= 60% win rate → no cooldown."""
        config = _default_config(
            cooldown_startup_trades=5,
            cooldown_win_rate_no_cooldown=0.60,
        )
        # 3 losses then 7 wins = 70% win rate, last trade is a win
        stats = _stats_with_trades(["loss"] * 3 + ["win"] * 7)
        self.assertEqual(compute_cooldown(stats, config), 0)

    def test_win_low_win_rate_1_cycle(self):
        """Win with < 60% win rate → 1 cycle cooldown."""
        config = _default_config(
            cooldown_startup_trades=5,
            cooldown_win_rate_no_cooldown=0.60,
            cooldown_cycles_short=1,
        )
        # 5 wins, 5 losses = 50%, last is win
        stats = _stats_with_trades(["loss"] * 5 + ["win"] * 5)
        self.assertEqual(compute_cooldown(stats, config), 1)

    def test_loss_high_win_rate_1_cycle(self):
        """Loss with >= 50% win rate → 1 cycle."""
        config = _default_config(
            cooldown_startup_trades=5,
            cooldown_win_rate_short=0.50,
            cooldown_cycles_short=1,
        )
        # 6 wins, 4 losses = 60%, last is loss
        stats = _stats_with_trades(["win"] * 6 + ["loss"] * 4)
        self.assertEqual(compute_cooldown(stats, config), 1)

    def test_loss_low_win_rate_2_cycles(self):
        """Loss with < 50% win rate → 2 cycles."""
        config = _default_config(
            cooldown_startup_trades=5,
            cooldown_win_rate_short=0.50,
            cooldown_cycles_long=2,
        )
        # 3 wins, 7 losses = 30%, last is loss
        stats = _stats_with_trades(["win"] * 3 + ["loss"] * 7)
        self.assertEqual(compute_cooldown(stats, config), 2)

    def test_empty_trades(self):
        """No trades at all → startup conservative (1 cycle)."""
        config = _default_config(cooldown_startup_trades=5)
        stats = RollingStats()
        self.assertEqual(compute_cooldown(stats, config), 1)


if __name__ == "__main__":
    unittest.main()
