"""Tests for PolyGuez Momentum position sizing logic (fixed tiers)."""

import unittest

from agents.strategies.polyguez_strategy import (
    calculate_max_capital_at_risk,
    calculate_position_size,
)
from agents.utils.objects import PolyGuezConfig


def _default_config(**overrides):
    return PolyGuezConfig(**overrides)


class TestPositionSizing(unittest.TestCase):

    def test_normal_signal_normal_balance(self):
        """$100 balance, normal signal → $5.00."""
        config = _default_config()
        size = calculate_position_size(100.0, config, edge=0.10, depth=5000.0)
        self.assertEqual(size, 5.0)

    def test_strong_signal_normal_balance(self):
        """$100 balance, strong signal (edge>=0.25, depth>=40000) → $7.00."""
        config = _default_config()
        size = calculate_position_size(100.0, config, edge=0.30, depth=50000.0)
        self.assertEqual(size, 7.0)

    def test_normal_signal_low_balance(self):
        """$30 balance (<$40), normal signal → $3.00."""
        config = _default_config()
        size = calculate_position_size(30.0, config, edge=0.10, depth=5000.0)
        self.assertEqual(size, 3.0)

    def test_strong_signal_low_balance(self):
        """$30 balance (<$40), strong signal → $5.00."""
        config = _default_config()
        size = calculate_position_size(30.0, config, edge=0.30, depth=50000.0)
        self.assertEqual(size, 5.0)

    def test_edge_below_strong_threshold(self):
        """Edge just below 0.25 → normal tier even with high depth."""
        config = _default_config()
        size = calculate_position_size(100.0, config, edge=0.24, depth=50000.0)
        self.assertEqual(size, 5.0)

    def test_depth_below_strong_threshold(self):
        """Depth just below 40000 → normal tier even with high edge."""
        config = _default_config()
        size = calculate_position_size(100.0, config, edge=0.30, depth=39999.0)
        self.assertEqual(size, 5.0)

    def test_reduce_size_verdict(self):
        """REDUCE-SIZE → 50% of normal bet."""
        config = _default_config()
        full_size = calculate_position_size(100.0, config, edge=0.10, depth=5000.0)
        reduced = round(full_size * 0.5, 2)
        self.assertEqual(reduced, 2.5)

    def test_max_capital_at_risk(self):
        """Max capital at risk = max(bet_size_strong, 7.0)."""
        config = _default_config()
        cap = calculate_max_capital_at_risk(100.0, config)
        self.assertEqual(cap, 7.0)

    def test_max_capital_at_risk_custom_strong(self):
        """Custom bet_size_strong > 7 → cap = that value."""
        config = _default_config(bet_size_strong=10.0)
        cap = calculate_max_capital_at_risk(100.0, config)
        self.assertEqual(cap, 10.0)

    def test_custom_bet_sizes(self):
        """Custom config overrides."""
        config = _default_config(bet_size_normal=8.0, bet_size_strong=12.0)
        size_normal = calculate_position_size(100.0, config, edge=0.10, depth=5000.0)
        size_strong = calculate_position_size(100.0, config, edge=0.30, depth=50000.0)
        self.assertEqual(size_normal, 8.0)
        self.assertEqual(size_strong, 12.0)

    def test_balance_at_threshold_boundary(self):
        """Balance exactly at low_balance_threshold → normal tier."""
        config = _default_config()
        size = calculate_position_size(40.0, config, edge=0.10, depth=5000.0)
        self.assertEqual(size, 5.0)

    def test_balance_just_below_threshold(self):
        """Balance just below low_balance_threshold → low tier."""
        config = _default_config()
        size = calculate_position_size(39.99, config, edge=0.10, depth=5000.0)
        self.assertEqual(size, 3.0)


class TestEdgeScaledSizing(unittest.TestCase):
    """Tests for edge_scaled_sizing=True fractional Kelly interpolation."""

    def test_edge_at_min_returns_normal(self):
        """edge == min_edge → normal bet size."""
        config = _default_config(edge_scaled_sizing=True, min_edge=0.03, strong_edge_threshold=0.25)
        size = calculate_position_size(100.0, config, edge=0.03, depth=50000.0)
        self.assertAlmostEqual(size, config.bet_size_normal, places=2)

    def test_edge_at_strong_returns_strong(self):
        """edge == strong_edge_threshold → strong bet size."""
        config = _default_config(edge_scaled_sizing=True, min_edge=0.03, strong_edge_threshold=0.25)
        size = calculate_position_size(100.0, config, edge=0.25, depth=50000.0)
        self.assertAlmostEqual(size, config.bet_size_strong, places=2)

    def test_edge_halfway_returns_midpoint(self):
        """edge halfway between min_edge and strong_edge_threshold → linear interp."""
        config = _default_config(
            edge_scaled_sizing=True, min_edge=0.03, strong_edge_threshold=0.25,
            bet_size_normal=8.0, bet_size_strong=10.0,
        )
        mid_edge = (0.03 + 0.25) / 2  # 0.14
        size = calculate_position_size(100.0, config, edge=mid_edge, depth=50000.0)
        expected = 8.0 + (10.0 - 8.0) * 0.5  # 9.0
        self.assertAlmostEqual(size, expected, places=2)

    def test_edge_below_min_clamps_to_normal(self):
        """edge below min_edge → clamp to normal (frac=0)."""
        config = _default_config(edge_scaled_sizing=True, min_edge=0.03, strong_edge_threshold=0.25)
        size = calculate_position_size(100.0, config, edge=0.01, depth=50000.0)
        self.assertAlmostEqual(size, config.bet_size_normal, places=2)

    def test_edge_above_strong_clamps_to_strong(self):
        """edge above strong_edge_threshold → clamp to strong (frac=1)."""
        config = _default_config(edge_scaled_sizing=True, min_edge=0.03, strong_edge_threshold=0.25)
        size = calculate_position_size(100.0, config, edge=0.50, depth=50000.0)
        self.assertAlmostEqual(size, config.bet_size_strong, places=2)

    def test_still_capped_by_max_capital_fraction(self):
        """Edge-scaled size still respects max_capital_fraction cap."""
        config = _default_config(edge_scaled_sizing=True, bet_size_strong=50.0)
        size = calculate_position_size(100.0, config, edge=0.30, depth=50000.0)
        # max_bet = 100 * 0.20 = 20
        self.assertEqual(size, 20.0)

    def test_default_flag_false_preserves_binary(self):
        """Default edge_scaled_sizing=False uses original binary logic."""
        config = _default_config()
        self.assertFalse(config.edge_scaled_sizing)
        size = calculate_position_size(100.0, config, edge=0.10, depth=5000.0)
        self.assertEqual(size, config.bet_size_normal)


if __name__ == "__main__":
    unittest.main()
