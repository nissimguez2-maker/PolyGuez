"""Tests for PolyGuez Momentum position sizing logic."""

import unittest

from agents.strategies.polyguez_strategy import (
    calculate_max_capital_at_risk,
    calculate_position_size,
)
from agents.utils.objects import PolyGuezConfig


def _default_config(**overrides):
    return PolyGuezConfig(**overrides)


class TestPositionSizing(unittest.TestCase):

    def test_normal_sizing_100(self):
        """$100 balance → max capital $10 → position $3.00."""
        config = _default_config(max_capital_pct=0.10, position_size_pct=0.30)
        size = calculate_position_size(100.0, config)
        self.assertAlmostEqual(size, 3.00)

    def test_normal_sizing_47(self):
        """$47 balance → max capital $4.70 → position $1.41."""
        config = _default_config(max_capital_pct=0.10, position_size_pct=0.30)
        size = calculate_position_size(47.0, config)
        self.assertAlmostEqual(size, 1.41)

    def test_floor_kicks_in(self):
        """$20 balance → 10% = $2 < $3 floor → max capital = $3 → position = $0.90."""
        config = _default_config(max_capital_pct=0.10, min_capital_floor=3.0, position_size_pct=0.30)
        size = calculate_position_size(20.0, config)
        self.assertAlmostEqual(size, 0.90)

    def test_reduce_size_verdict(self):
        """REDUCE-SIZE → 50% of normal position size."""
        config = _default_config(max_capital_pct=0.10, position_size_pct=0.30)
        full_size = calculate_position_size(100.0, config)
        reduced = round(full_size * 0.5, 2)
        self.assertAlmostEqual(reduced, 1.50)

    def test_max_capital_at_risk_normal(self):
        """$100 balance → max capital = $10."""
        config = _default_config(max_capital_pct=0.10)
        cap = calculate_max_capital_at_risk(100.0, config)
        self.assertAlmostEqual(cap, 10.00)

    def test_max_capital_at_risk_floor(self):
        """$20 balance → 10% = $2, floor = $3 → max capital = $3."""
        config = _default_config(max_capital_pct=0.10, min_capital_floor=3.0)
        cap = calculate_max_capital_at_risk(20.0, config)
        self.assertAlmostEqual(cap, 3.00)

    def test_different_pcts(self):
        """Custom percentages."""
        config = _default_config(max_capital_pct=0.20, position_size_pct=0.50)
        size = calculate_position_size(100.0, config)
        self.assertAlmostEqual(size, 10.00)

    def test_very_small_balance(self):
        """$1 balance → floor $3 → position $0.90."""
        config = _default_config(max_capital_pct=0.10, min_capital_floor=3.0, position_size_pct=0.30)
        size = calculate_position_size(1.0, config)
        self.assertAlmostEqual(size, 0.90)

    def test_recalculation_independence(self):
        """Calling twice with different balances gives different results."""
        config = _default_config(max_capital_pct=0.10, position_size_pct=0.30)
        size1 = calculate_position_size(50.0, config)
        size2 = calculate_position_size(200.0, config)
        self.assertNotAlmostEqual(size1, size2)
        self.assertAlmostEqual(size1, 1.50)
        self.assertAlmostEqual(size2, 6.00)


if __name__ == "__main__":
    unittest.main()
