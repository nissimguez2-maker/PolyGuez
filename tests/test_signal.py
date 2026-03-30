"""Tests for PolyGuez Momentum signal evaluation."""

import unittest

from agents.strategies.polyguez_strategy import evaluate_entry_signal
from agents.utils.objects import PolyGuezConfig, RollingStats, TradeRecord


def _default_config(**overrides):
    return PolyGuezConfig(**overrides)


def _stats_with_trades(outcomes, pnls=None):
    """Build RollingStats with N trades of given outcomes."""
    stats = RollingStats()
    for i, outcome in enumerate(outcomes):
        pnl = (pnls[i] if pnls else (0.5 if outcome == "win" else -0.5))
        stats.trades.append(TradeRecord(outcome=outcome, pnl=pnl, side="YES"))
    return stats


class TestSignalEvaluation(unittest.TestCase):
    """Test evaluate_entry_signal with various inputs."""

    def test_all_conditions_met_up(self):
        """Strong upward momentum, good edge, should fire."""
        config = _default_config(velocity_threshold=0.01, min_edge=0.02, max_spread=0.10)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05,
            btc_price=65000.0,
            yes_price=0.50,
            no_price=0.48,
            spread=0.02,
            elapsed_seconds=30.0,
            usdc_balance=100.0,
            config=config,
            rolling_stats=stats,
            has_position=False,
        )
        self.assertTrue(signal.all_conditions_met)
        self.assertEqual(signal.direction, "up")

    def test_all_conditions_met_down(self):
        """Strong downward momentum."""
        config = _default_config(velocity_threshold=0.01, min_edge=0.02, max_spread=0.10)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=-0.05,
            btc_price=65000.0,
            yes_price=0.48,
            no_price=0.50,
            spread=0.02,
            elapsed_seconds=30.0,
            usdc_balance=100.0,
            config=config,
            rolling_stats=stats,
            has_position=False,
        )
        self.assertTrue(signal.all_conditions_met)
        self.assertEqual(signal.direction, "down")

    def test_velocity_too_low(self):
        """Velocity below threshold → velocity_ok is False."""
        config = _default_config(velocity_threshold=0.10)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05,
            btc_price=65000.0,
            yes_price=0.50,
            no_price=0.48,
            spread=0.02,
            elapsed_seconds=30.0,
            usdc_balance=100.0,
            config=config,
            rolling_stats=stats,
            has_position=False,
        )
        self.assertFalse(signal.velocity_ok)
        self.assertFalse(signal.all_conditions_met)

    def test_spread_too_wide(self):
        """Spread above max_spread → spread_ok is False."""
        config = _default_config(velocity_threshold=0.01, min_edge=0.02, max_spread=0.05)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05,
            btc_price=65000.0,
            yes_price=0.50,
            no_price=0.48,
            spread=0.08,
            elapsed_seconds=30.0,
            usdc_balance=100.0,
            config=config,
            rolling_stats=stats,
            has_position=False,
        )
        self.assertFalse(signal.spread_ok)
        self.assertFalse(signal.all_conditions_met)

    def test_has_position_blocks(self):
        """Already holding a position → no_position is False."""
        config = _default_config(velocity_threshold=0.01, min_edge=0.02, max_spread=0.10)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05,
            btc_price=65000.0,
            yes_price=0.50,
            no_price=0.48,
            spread=0.02,
            elapsed_seconds=30.0,
            usdc_balance=100.0,
            config=config,
            rolling_stats=stats,
            has_position=True,
        )
        self.assertFalse(signal.no_position)
        self.assertFalse(signal.all_conditions_met)

    def test_early_window_edge(self):
        """Early window (< 60s) uses normal min_edge."""
        config = _default_config(
            velocity_threshold=0.01,
            min_edge=0.05,
            max_spread=0.10,
            early_edge_multiplier=1.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05,
            btc_price=65000.0,
            yes_price=0.50,
            no_price=0.48,
            spread=0.02,
            elapsed_seconds=30.0,
            usdc_balance=100.0,
            config=config,
            rolling_stats=stats,
            has_position=False,
        )
        self.assertAlmostEqual(signal.required_edge, 0.05)

    def test_mid_window_edge(self):
        """Mid window (60-150s) requires 1.5x edge."""
        config = _default_config(
            velocity_threshold=0.01,
            min_edge=0.02,
            max_spread=0.10,
            early_window_seconds=60,
            mid_window_seconds=150,
            mid_edge_multiplier=1.5,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05,
            btc_price=65000.0,
            yes_price=0.50,
            no_price=0.48,
            spread=0.02,
            elapsed_seconds=90.0,
            usdc_balance=100.0,
            config=config,
            rolling_stats=stats,
            has_position=False,
        )
        self.assertAlmostEqual(signal.required_edge, 0.03)

    def test_late_window_edge(self):
        """Late window (>150s) requires 2.5x edge."""
        config = _default_config(
            velocity_threshold=0.01,
            min_edge=0.02,
            max_spread=0.10,
            mid_window_seconds=150,
            late_edge_multiplier=2.5,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05,
            btc_price=65000.0,
            yes_price=0.50,
            no_price=0.48,
            spread=0.02,
            elapsed_seconds=200.0,
            usdc_balance=100.0,
            config=config,
            rolling_stats=stats,
            has_position=False,
        )
        self.assertAlmostEqual(signal.required_edge, 0.05)

    def test_low_balance_fails(self):
        """Balance below floor → balance_ok is False."""
        config = _default_config(
            velocity_threshold=0.01,
            min_edge=0.02,
            max_spread=0.10,
            min_capital_floor=3.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05,
            btc_price=65000.0,
            yes_price=0.50,
            no_price=0.48,
            spread=0.02,
            elapsed_seconds=30.0,
            usdc_balance=2.0,
            config=config,
            rolling_stats=stats,
            has_position=False,
        )
        self.assertFalse(signal.balance_ok)

    def test_tightened_criteria_on_losing_streak(self):
        """Low win rate tightens velocity/edge thresholds."""
        config = _default_config(
            velocity_threshold=0.04,
            min_edge=0.02,
            max_spread=0.10,
            cooldown_tightened_multiplier=1.5,
            cooldown_startup_trades=5,
            cooldown_win_rate_short=0.50,
        )
        # 2 wins, 4 losses = 33% win rate, below 50%
        stats = _stats_with_trades(["win", "win", "loss", "loss", "loss", "loss"])
        signal = evaluate_entry_signal(
            btc_velocity=0.05,  # above 0.04 but below 0.04*1.5=0.06
            btc_price=65000.0,
            yes_price=0.50,
            no_price=0.48,
            spread=0.02,
            elapsed_seconds=30.0,
            usdc_balance=100.0,
            config=config,
            rolling_stats=stats,
            has_position=False,
        )
        # velocity 0.05 < tightened threshold 0.06
        self.assertFalse(signal.velocity_ok)


if __name__ == "__main__":
    unittest.main()
