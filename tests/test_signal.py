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
        config = _default_config(
            velocity_threshold=0.01, min_edge=0.02, max_spread=0.10,
            min_oracle_gap=10.0, min_clob_depth=50.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            chainlink_price=64985.0, binance_chainlink_gap=15.0,
            clob_depth=100.0,
        )
        self.assertTrue(signal.all_conditions_met)
        self.assertEqual(signal.direction, "up")
        self.assertTrue(signal.depth_ok)

    def test_all_conditions_met_down(self):
        config = _default_config(
            velocity_threshold=0.01, min_edge=0.02, max_spread=0.10,
            min_oracle_gap=10.0, min_clob_depth=50.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=-0.05, btc_price=65000.0,
            yes_price=0.48, no_price=0.50, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            chainlink_price=65015.0, binance_chainlink_gap=-15.0,
            clob_depth=100.0,
        )
        self.assertTrue(signal.all_conditions_met)
        self.assertEqual(signal.direction, "down")

    def test_velocity_too_low(self):
        config = _default_config(velocity_threshold=0.10, min_clob_depth=0.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            clob_depth=100.0,
        )
        self.assertFalse(signal.velocity_ok)
        self.assertFalse(signal.all_conditions_met)

    def test_spread_too_wide(self):
        config = _default_config(
            velocity_threshold=0.01, min_edge=0.02, max_spread=0.05, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.08,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            clob_depth=100.0,
        )
        self.assertFalse(signal.spread_ok)
        self.assertFalse(signal.all_conditions_met)

    def test_has_position_blocks(self):
        config = _default_config(
            velocity_threshold=0.01, min_edge=0.02, max_spread=0.10, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=True,
            clob_depth=100.0,
        )
        self.assertFalse(signal.no_position)
        self.assertFalse(signal.all_conditions_met)

    def test_early_window_edge(self):
        config = _default_config(
            velocity_threshold=0.01, min_edge=0.05, max_spread=0.10,
            early_edge_multiplier=1.0, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            clob_depth=100.0,
        )
        self.assertAlmostEqual(signal.required_edge, 0.05)

    def test_mid_window_edge(self):
        config = _default_config(
            velocity_threshold=0.01, min_edge=0.02, max_spread=0.10,
            early_window_seconds=60, mid_window_seconds=150,
            mid_edge_multiplier=1.5, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=90.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            clob_depth=100.0,
        )
        self.assertAlmostEqual(signal.required_edge, 0.03)

    def test_late_window_edge(self):
        config = _default_config(
            velocity_threshold=0.01, min_edge=0.02, max_spread=0.10,
            mid_window_seconds=150, late_edge_multiplier=2.5, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=200.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            clob_depth=100.0,
        )
        self.assertAlmostEqual(signal.required_edge, 0.05)

    def test_low_balance_fails(self):
        config = _default_config(
            velocity_threshold=0.01, min_edge=0.02, max_spread=0.10,
            min_capital_floor=3.0, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=2.0,
            config=config, rolling_stats=stats, has_position=False,
            clob_depth=100.0,
        )
        self.assertFalse(signal.balance_ok)

    def test_tightened_criteria_on_losing_streak(self):
        config = _default_config(
            velocity_threshold=0.04, min_edge=0.02, max_spread=0.10,
            cooldown_tightened_multiplier=1.5, cooldown_startup_trades=5,
            cooldown_win_rate_short=0.50, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win", "win", "loss", "loss", "loss", "loss"])
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            clob_depth=100.0,
        )
        self.assertFalse(signal.velocity_ok)

    # -- Oracle gap tests ---------------------------------------------------

    def test_oracle_gap_ok_up(self):
        config = _default_config(
            min_oracle_gap=10.0, velocity_threshold=0.01, min_edge=0.02,
            max_spread=0.10, min_clob_depth=50.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            chainlink_price=64985.0, binance_chainlink_gap=15.0, clob_depth=100.0,
        )
        self.assertTrue(signal.oracle_gap_ok)

    def test_oracle_gap_too_small(self):
        config = _default_config(
            min_oracle_gap=20.0, velocity_threshold=0.01, min_edge=0.02,
            max_spread=0.10, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            chainlink_price=64990.0, binance_chainlink_gap=10.0, clob_depth=100.0,
        )
        self.assertFalse(signal.oracle_gap_ok)

    def test_oracle_gap_wrong_direction(self):
        config = _default_config(
            min_oracle_gap=10.0, velocity_threshold=0.01, min_edge=0.02,
            max_spread=0.10, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            chainlink_price=65020.0, binance_chainlink_gap=-20.0, clob_depth=100.0,
        )
        self.assertFalse(signal.oracle_gap_ok)

    def test_oracle_gap_ok_down(self):
        config = _default_config(
            min_oracle_gap=10.0, velocity_threshold=0.01, min_edge=0.02,
            max_spread=0.10, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=-0.05, btc_price=65000.0,
            yes_price=0.48, no_price=0.50, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            chainlink_price=65015.0, binance_chainlink_gap=-15.0, clob_depth=100.0,
        )
        self.assertTrue(signal.oracle_gap_ok)

    # -- CLOB mispricing tests ----------------------------------------------

    def test_clob_mispricing_ok(self):
        config = _default_config(
            velocity_threshold=0.01, min_edge=0.02, max_spread=0.10,
            min_oracle_gap=10.0, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            chainlink_price=64985.0, binance_chainlink_gap=15.0, clob_depth=100.0,
        )
        self.assertTrue(signal.clob_mispricing_ok)
        self.assertGreater(signal.estimated_fair_value, signal.yes_price)

    def test_clob_no_mispricing(self):
        config = _default_config(
            velocity_threshold=0.001, min_edge=0.001, max_spread=0.10,
            min_oracle_gap=10.0, min_clob_depth=0.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal2 = evaluate_entry_signal(
            btc_velocity=0.0001, btc_price=65000.0,
            yes_price=1.0, no_price=0.00, spread=0.00,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            chainlink_price=64985.0, binance_chainlink_gap=15.0, clob_depth=100.0,
        )
        self.assertFalse(signal2.clob_mispricing_ok)

    # -- FIX 2: CLOB depth gate tests --------------------------------------

    def test_depth_ok_sufficient(self):
        config = _default_config(
            velocity_threshold=0.01, min_edge=0.02, max_spread=0.10,
            min_oracle_gap=10.0, min_clob_depth=50.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            chainlink_price=64985.0, binance_chainlink_gap=15.0, clob_depth=100.0,
        )
        self.assertTrue(signal.depth_ok)

    def test_depth_too_thin_blocks_entry(self):
        config = _default_config(
            velocity_threshold=0.01, min_edge=0.02, max_spread=0.10,
            min_oracle_gap=10.0, min_clob_depth=50.0,
        )
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            chainlink_price=64985.0, binance_chainlink_gap=15.0, clob_depth=30.0,
        )
        self.assertFalse(signal.depth_ok)
        self.assertFalse(signal.all_conditions_met)

    def test_depth_at_threshold_passes(self):
        config = _default_config(min_clob_depth=50.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            chainlink_price=64985.0, binance_chainlink_gap=15.0, clob_depth=50.0,
        )
        self.assertTrue(signal.depth_ok)

    def test_depth_zero_blocks(self):
        config = _default_config(min_clob_depth=50.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            clob_depth=0.0,
        )
        self.assertFalse(signal.depth_ok)

    def test_depth_gate_disabled(self):
        config = _default_config(min_clob_depth=0.0)
        stats = _stats_with_trades(["win"] * 6)
        signal = evaluate_entry_signal(
            btc_velocity=0.05, btc_price=65000.0,
            yes_price=0.50, no_price=0.48, spread=0.02,
            elapsed_seconds=30.0, usdc_balance=100.0,
            config=config, rolling_stats=stats, has_position=False,
            clob_depth=0.0,
        )
        self.assertTrue(signal.depth_ok)


class TestComputeClobDepth(unittest.TestCase):

    def test_normal_book(self):
        book = {
            "asks": [
                {"price": "0.50", "size": "100"},
                {"price": "0.51", "size": "200"},
                {"price": "0.52", "size": "150"},
                {"price": "0.60", "size": "500"},
            ],
            "bids": [],
        }
        depth = compute_clob_depth(book, "buy")
        self.assertAlmostEqual(depth, 450.0)

    def test_empty_book(self):
        self.assertEqual(compute_clob_depth({}, "buy"), 0.0)
        self.assertEqual(compute_clob_depth({"asks": [], "bids": []}, "buy"), 0.0)

    def test_single_level(self):
        book = {"asks": [{"price": "0.50", "size": "75"}], "bids": []}
        depth = compute_clob_depth(book, "buy")
        self.assertAlmostEqual(depth, 75.0)

    def test_none_book(self):
        self.assertEqual(compute_clob_depth(None, "buy"), 0.0)


if __name__ == "__main__":
    unittest.main()
