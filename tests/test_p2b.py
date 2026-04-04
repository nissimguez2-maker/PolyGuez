"""Tests for Price-to-Beat extraction and cross-check logic."""

import sys
import unittest
from unittest.mock import MagicMock

# Stub heavy dependencies so market_discovery can be imported without web3/etc
for mod in [
    "web3", "web3.auto", "web3.middleware",
    "agents.polymarket.polymarket", "agents.polymarket.gamma",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from agents.strategies.market_discovery import MarketDiscovery


class TestExtractPriceToBeat(unittest.TestCase):

    def test_real_description_price_to_beat(self):
        desc = (
            'Will the price of Bitcoin be higher or lower than the opening '
            '\'Price to Beat" of $66,649.22 at 2:35pm ET on May 1?'
        )
        result = MarketDiscovery.extract_price_to_beat({"description": desc})
        self.assertAlmostEqual(result, 66649.22)

    def test_dollar_amounts_before_p2b(self):
        desc = (
            "This market pays $1.00 if BTC is above the opening "
            "'Price to Beat' of $65,000.00 at expiry."
        )
        result = MarketDiscovery.extract_price_to_beat({"description": desc})
        self.assertAlmostEqual(result, 65000.00)

    def test_empty_description_returns_none(self):
        self.assertIsNone(MarketDiscovery.extract_price_to_beat({"description": ""}))
        self.assertIsNone(MarketDiscovery.extract_price_to_beat({}))
        self.assertIsNone(MarketDiscovery.extract_price_to_beat({"description": None}))

    def test_no_dollar_amount_returns_none(self):
        self.assertIsNone(MarketDiscovery.extract_price_to_beat(
            {"description": "Will BTC go up or down in 5 minutes?"}
        ))

    def test_implausible_low_value_returns_none(self):
        desc = "Price to Beat of $500.00 at expiry."
        self.assertIsNone(MarketDiscovery.extract_price_to_beat({"description": desc}))

    def test_implausible_high_value_returns_none(self):
        desc = "Price to Beat of $999,999.00 at expiry."
        self.assertIsNone(MarketDiscovery.extract_price_to_beat({"description": desc}))

    def test_opening_fallback(self):
        desc = "Market resolves based on opening $67,123.45 BTC price."
        result = MarketDiscovery.extract_price_to_beat({"description": desc})
        self.assertAlmostEqual(result, 67123.45)

    def test_broad_fallback_within_sanity(self):
        desc = "BTC was at $68,500.00 when this market was created."
        result = MarketDiscovery.extract_price_to_beat({"description": desc})
        self.assertAlmostEqual(result, 68500.00)

    def test_broad_fallback_outside_sanity(self):
        desc = "Payout is $2.50 per share."
        self.assertIsNone(MarketDiscovery.extract_price_to_beat({"description": desc}))


class TestCrossCheckPriceToBeat(unittest.TestCase):

    def test_matching_values_within_tolerance(self):
        passes, div = MarketDiscovery.cross_check_price_to_beat(
            description_p2b=65000.0,
            chainlink_price=65010.0,
            discovery_lag_seconds=0.0,
            btc_price=65000.0,
        )
        self.assertTrue(passes)
        self.assertAlmostEqual(div, 10.0)

    def test_diverging_values_outside_tolerance(self):
        passes, div = MarketDiscovery.cross_check_price_to_beat(
            description_p2b=65000.0,
            chainlink_price=65200.0,
            discovery_lag_seconds=0.0,
            btc_price=65000.0,
        )
        self.assertFalse(passes)
        self.assertAlmostEqual(div, 200.0)

    def test_lag_increases_tolerance(self):
        # Without lag: tolerance = max(30, 65000*0.0005) + 0 = 32.5
        passes_no_lag, _ = MarketDiscovery.cross_check_price_to_beat(
            description_p2b=65000.0,
            chainlink_price=65060.0,
            discovery_lag_seconds=0.0,
            btc_price=65000.0,
        )
        self.assertFalse(passes_no_lag)

        # With 10s lag: tolerance = 32.5 + 30 = 62.5 → 60 divergence passes
        passes_lag, _ = MarketDiscovery.cross_check_price_to_beat(
            description_p2b=65000.0,
            chainlink_price=65060.0,
            discovery_lag_seconds=10.0,
            btc_price=65000.0,
        )
        self.assertTrue(passes_lag)

    def test_none_p2b_returns_false(self):
        passes, _ = MarketDiscovery.cross_check_price_to_beat(
            description_p2b=None,
            chainlink_price=65000.0,
        )
        self.assertFalse(passes)

    def test_zero_chainlink_returns_false(self):
        passes, _ = MarketDiscovery.cross_check_price_to_beat(
            description_p2b=65000.0,
            chainlink_price=0.0,
        )
        self.assertFalse(passes)


class TestExtractPriceToBeatChainlinkFallback(unittest.TestCase):
    """Tests for the Tier 4 Chainlink fallback in extract_price_to_beat."""

    def test_chainlink_fallback_when_no_dollar_in_description(self):
        """When description has no dollar amount, chainlink_price is returned as P2B."""
        market = {
            "description": (
                "This market will resolve to 'Up' if the Bitcoin price at the end of "
                "the time range is greater than or equal to the price at the beginning "
                "of that range."
            )
        }
        result = MarketDiscovery.extract_price_to_beat(market, chainlink_price=65000.0)
        self.assertEqual(result, 65000.0)

    def test_chainlink_fallback_returns_none_when_chainlink_also_none(self):
        """When description has no dollar amount and chainlink_price is None, returns None."""
        market = {
            "description": (
                "This market will resolve to 'Up' if the Bitcoin price at the end of "
                "the time range is greater than or equal to the price at the beginning "
                "of that range."
            )
        }
        result = MarketDiscovery.extract_price_to_beat(market, chainlink_price=None)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
