"""Tests for PolyGuezConfig model_validator warnings."""

import logging
import unittest

from agents.utils.objects import PolyGuezConfig


class TestConfigValidator(unittest.TestCase):

    def test_warns_high_edge_and_delta(self, ):
        """min_terminal_edge > 0.10 AND conviction_min_delta > 50 → warning."""
        with self.assertLogs("polyguez.config", level="WARNING") as cm:
            PolyGuezConfig(min_terminal_edge=0.15, conviction_min_delta=60)
        self.assertTrue(any("block all trades" in msg for msg in cm.output))

    def test_warns_inverted_price_range(self):
        """min_entry_token_price > max_entry_token_price → warning."""
        with self.assertLogs("polyguez.config", level="WARNING") as cm:
            PolyGuezConfig(min_entry_token_price=0.80, max_entry_token_price=0.20)
        self.assertTrue(any("entry price filter" in msg for msg in cm.output))

    def test_warns_blocked_hours_excessive(self):
        """blocked_hours_utc > 12 hours → warning."""
        with self.assertLogs("polyguez.config", level="WARNING") as cm:
            PolyGuezConfig(blocked_hours_utc=list(range(13)))
        self.assertTrue(any("more than half the day" in msg for msg in cm.output))

    def test_warns_invalid_direction_mode(self):
        """direction_mode not in valid set → warning."""
        with self.assertLogs("polyguez.config", level="WARNING") as cm:
            PolyGuezConfig(direction_mode="sideways")
        self.assertTrue(any("not a recognized value" in msg for msg in cm.output))

    def test_no_warning_on_defaults(self):
        """Default config should not emit any warnings."""
        logger = logging.getLogger("polyguez.config")
        with self.assertRaises(AssertionError):
            # assertLogs raises AssertionError if no logs are emitted
            with self.assertLogs("polyguez.config", level="WARNING"):
                PolyGuezConfig()

    def test_validator_does_not_prevent_startup(self):
        """Suspicious config still instantiates (warnings, not errors)."""
        config = PolyGuezConfig(
            min_terminal_edge=0.20,
            conviction_min_delta=100,
            min_entry_token_price=0.90,
            max_entry_token_price=0.10,
            blocked_hours_utc=list(range(20)),
            direction_mode="invalid",
        )
        self.assertIsInstance(config, PolyGuezConfig)


if __name__ == "__main__":
    unittest.main()
