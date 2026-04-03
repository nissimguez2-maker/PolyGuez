"""Tests for PolyGuez Momentum signal evaluation."""

import unittest

from agents.strategies.polyguez_strategy import evaluate_entry_signal, compute_clob_depth
from agents.utils.objects import PolyGuezConfig, RollingStats, TradeRecord


def _default_config(**overrides):
    return PolyGuezConfig(**overrides)


def _stats_with_trades(outcomes, pnls=None):
    stats = RollingStats()
    for i, outcome in enumerate(outcomes):
        pnl = (pnls[i] if pnls else (0.5 if outcome == "win" else -0.5))
        stats.trades.append(TradeRecord(outcome=outcome, pnl=pnl, side="YES"))
    return stats


class TestSignalEvaluation(unittest.TestCase):

    def test_all_conditions_met_up(self):
        config = _default_config(velocity_threshold=0.01, min_edge=0.02, max_spread=0.10, min_oracle_gap=10.0, min_clob_depth=50.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64985.0, binance_chainlink_gap=15.0, clob_depth=100.0,
            price_to_beat=64935.0,
        )
        self.assertTrue(signal.all_conditions_met)
        self.assertTrue(signal.depth_ok)
        self.assertTrue(signal.terminal_edge_ok)
        self.assertTrue(signal.delta_magnitude_ok)

    def test_all_conditions_met_down(self):
        config = _default_config(velocity_threshold=0.01, min_edge=0.02, max_spread=0.10, min_oracle_gap=10.0, min_clob_depth=50.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=-0.05, btc_price=65000.0, yes_price=0.48, no_price=0.50, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=65015.0, binance_chainlink_gap=-15.0, clob_depth=100.0,
            price_to_beat=65065.0,
        )
        self.assertTrue(signal.all_conditions_met)
        self.assertTrue(signal.terminal_edge_ok)
        self.assertTrue(signal.delta_magnitude_ok)

    def test_velocity_too_low(self):
        config = _default_config(velocity_threshold=0.10, min_clob_depth=0.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64910.0, clob_depth=100.0, price_to_beat=64900.0,
        )
        self.assertFalse(signal.velocity_ok)

    def test_spread_too_wide(self):
        config = _default_config(velocity_threshold=0.01, min_edge=0.02, max_spread=0.05, min_clob_depth=0.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.08,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64910.0, clob_depth=100.0, price_to_beat=64900.0,
        )
        self.assertFalse(signal.spread_ok)

    def test_has_position_blocks(self):
        config = _default_config(velocity_threshold=0.01, min_edge=0.02, max_spread=0.10, min_clob_depth=0.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=True, chainlink_price=64910.0, clob_depth=100.0, price_to_beat=64900.0,
        )
        self.assertFalse(signal.no_position)

    def test_low_balance_fails(self):
        config = _default_config(velocity_threshold=0.01, min_edge=0.02, max_spread=0.10, bet_size_low_balance_normal=3.0, min_clob_depth=0.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=2.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64910.0, clob_depth=100.0, price_to_beat=64900.0,
        )
        self.assertFalse(signal.balance_ok)

    def test_tightened_criteria_on_losing_streak(self):
        config = _default_config(velocity_threshold=0.04, min_edge=0.02, max_spread=0.10,
            cooldown_tightened_multiplier=1.5, cooldown_startup_trades=5, cooldown_win_rate_short=0.50, min_clob_depth=0.0)
        stats = _stats_with_trades(["win", "win", "loss", "loss", "loss", "loss"])
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64910.0, clob_depth=100.0, price_to_beat=64900.0,
        )
        self.assertFalse(signal.velocity_ok)

    def test_oracle_gap_ok_up(self):
        config = _default_config(min_oracle_gap=10.0, velocity_threshold=0.01, min_edge=0.02, max_spread=0.10, min_clob_depth=0.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64985.0, binance_chainlink_gap=15.0, clob_depth=100.0,
            price_to_beat=64900.0,
        )
        self.assertTrue(signal.oracle_gap_ok)

    def test_oracle_gap_too_small(self):
        config = _default_config(min_oracle_gap=20.0, velocity_threshold=0.01, min_edge=0.02, max_spread=0.10, min_clob_depth=0.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64990.0, binance_chainlink_gap=10.0, clob_depth=100.0,
            price_to_beat=64900.0,
        )
        self.assertFalse(signal.oracle_gap_ok)

    def test_oracle_gap_wrong_direction(self):
        config = _default_config(min_oracle_gap=10.0, velocity_threshold=0.01, min_edge=0.02, max_spread=0.10, min_clob_depth=0.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=65020.0, binance_chainlink_gap=-20.0, clob_depth=100.0,
            price_to_beat=64900.0,
        )
        self.assertFalse(signal.oracle_gap_ok)

    # -- Depth gate tests --

    def test_depth_ok_sufficient(self):
        config = _default_config(min_clob_depth=50.0, velocity_threshold=0.01, min_edge=0.02, max_spread=0.10, min_oracle_gap=10.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64985.0, binance_chainlink_gap=15.0, clob_depth=100.0,
            price_to_beat=64900.0,
        )
        self.assertTrue(signal.depth_ok)

    def test_depth_too_thin_blocks_entry(self):
        config = _default_config(min_clob_depth=50.0, velocity_threshold=0.01, min_edge=0.02, max_spread=0.10, min_oracle_gap=10.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64985.0, binance_chainlink_gap=15.0, clob_depth=30.0,
            price_to_beat=64900.0,
        )
        self.assertFalse(signal.depth_ok)
        self.assertFalse(signal.all_conditions_met)

    def test_depth_at_threshold_passes(self):
        config = _default_config(min_clob_depth=50.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64985.0, binance_chainlink_gap=15.0, clob_depth=50.0,
            price_to_beat=64900.0,
        )
        self.assertTrue(signal.depth_ok)

    def test_depth_zero_blocks(self):
        config = _default_config(min_clob_depth=50.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64910.0, clob_depth=0.0, price_to_beat=64900.0,
        )
        self.assertFalse(signal.depth_ok)

    def test_depth_gate_disabled(self):
        config = _default_config(min_clob_depth=0.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64910.0, clob_depth=0.0, price_to_beat=64900.0,
        )
        self.assertTrue(signal.depth_ok)

    # -- P2B / terminal probability tests --

    def test_price_to_beat_none_short_circuits(self):
        config = _default_config()
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64950.0, clob_depth=100.0, price_to_beat=None,
        )
        self.assertFalse(signal.all_conditions_met)
        self.assertEqual(signal.p2b_source, "none")
        self.assertFalse(signal.terminal_edge_ok)
        self.assertFalse(signal.delta_magnitude_ok)

    def test_terminal_probability_up_positive_delta(self):
        """strike_delta=+100, 60s remaining → tp_yes ~0.94, direction=up → selected ~0.94."""
        config = _default_config(min_terminal_edge=0.05, conviction_min_delta=40.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=240.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=65100.0, clob_depth=100.0,
            price_to_beat=65000.0,
        )
        self.assertEqual(signal.direction, "up")
        self.assertAlmostEqual(signal.strike_delta, 100.0)
        self.assertGreater(signal.terminal_probability, 0.90)
        self.assertTrue(signal.terminal_edge_ok)
        self.assertTrue(signal.delta_magnitude_ok)
        self.assertEqual(signal.p2b_source, "description")

    def test_terminal_probability_down_negative_delta(self):
        """strike_delta=-100, 60s remaining → tp_yes ~0.06, direction=down → selected ~0.94."""
        config = _default_config(min_terminal_edge=0.05, conviction_min_delta=40.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=-0.05, btc_price=65000.0, yes_price=0.48, no_price=0.50, spread=0.02,
            elapsed_seconds=240.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64900.0, clob_depth=100.0,
            price_to_beat=65000.0,
        )
        self.assertEqual(signal.direction, "down")
        self.assertAlmostEqual(signal.strike_delta, -100.0)
        self.assertGreater(signal.terminal_probability, 0.90)
        self.assertTrue(signal.terminal_edge_ok)
        self.assertTrue(signal.delta_magnitude_ok)

    def test_delta_too_small_blocks(self):
        config = _default_config(conviction_min_delta=40.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=65010.0, clob_depth=100.0,
            price_to_beat=65000.0,
        )
        self.assertFalse(signal.delta_magnitude_ok)

    def test_terminal_edge_too_small_blocks(self):
        """Near 50/50 probability → terminal_edge near 0 → fails gate."""
        config = _default_config(min_terminal_edge=0.05, conviction_min_delta=1.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=65001.0, clob_depth=100.0,
            price_to_beat=65000.0,
        )
        self.assertFalse(signal.terminal_edge_ok)

    def test_strict_delta_in_fast_market(self):
        """Fast velocity (>3x threshold) uses conviction_min_delta_strict."""
        config = _default_config(
            velocity_threshold=0.05, conviction_min_delta=15.0,
            conviction_min_delta_strict=40.0, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        # velocity=0.20 > 0.05*3=0.15 → fast market → strict threshold (40)
        # delta=25 passes normal (15) but fails strict (40)
        signal = evaluate_entry_signal(
            btc_velocity=0.20, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64975.0, clob_depth=100.0,
            price_to_beat=64950.0,
        )
        self.assertFalse(signal.delta_magnitude_ok)

    def test_normal_delta_in_slow_market(self):
        """Slow velocity uses conviction_min_delta (normal)."""
        config = _default_config(
            velocity_threshold=0.05, conviction_min_delta=15.0,
            conviction_min_delta_strict=40.0, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        # velocity=0.10 < 0.05*3=0.15 → normal threshold (15)
        # delta=25 passes normal (15)
        signal = evaluate_entry_signal(
            btc_velocity=0.10, btc_price=65000.0, yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0, config=config, rolling_stats=stats,
            has_position=False, chainlink_price=64975.0, clob_depth=100.0,
            price_to_beat=64950.0,
        )
        self.assertTrue(signal.delta_magnitude_ok)


class TestComputeClobDepth(unittest.TestCase):

    def test_normal_book(self):
        book = {"asks": [{"price": "0.50", "size": "100"}, {"price": "0.51", "size": "200"},
                         {"price": "0.52", "size": "150"}, {"price": "0.60", "size": "500"}], "bids": []}
        self.assertAlmostEqual(compute_clob_depth(book, "buy"), 450.0)

    def test_empty_book(self):
        self.assertEqual(compute_clob_depth({}, "buy"), 0.0)
        self.assertEqual(compute_clob_depth({"asks": [], "bids": []}, "buy"), 0.0)

    def test_single_level(self):
        book = {"asks": [{"price": "0.50", "size": "75"}], "bids": []}
        self.assertAlmostEqual(compute_clob_depth(book, "buy"), 75.0)

    def test_none_book(self):
        self.assertEqual(compute_clob_depth(None, "buy"), 0.0)


if __name__ == "__main__":
    unittest.main()
