"""Tests for GammaMarketClient.get_market() list-unwrapping fix."""

import sys
import unittest
from unittest.mock import MagicMock, patch

# Stub only the heavy/unavailable dependencies — NOT agents.utils.objects,
# which has real Pydantic models used by other tests in the same process.
for mod in ["agents.polymarket.polymarket"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from agents.polymarket.gamma import GammaMarketClient  # noqa: E402


class TestGammaGetMarket(unittest.TestCase):
    """Tests that get_market() correctly unwraps Gamma API list responses."""

    def setUp(self):
        self.gamma = GammaMarketClient.__new__(GammaMarketClient)
        self.gamma.gamma_url = "https://gamma-api.polymarket.com"
        self.gamma.gamma_markets_endpoint = self.gamma.gamma_url + "/markets"
        self.gamma._http_headers = {}
        self.gamma._http_timeout = 15.0

    def _mock_response(self, payload, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = payload
        return resp

    def test_unwraps_list_response(self):
        """Gamma API returns a list; get_market() must return data[0]."""
        market_dict = {"id": 1849157, "closed": True, "outcomePrices": '["1","0"]'}
        with patch("agents.polymarket.gamma.httpx.get",
                   return_value=self._mock_response([market_dict])):
            result = self.gamma.get_market(1849157)
        self.assertEqual(result, market_dict)

    def test_returns_dict_directly_when_not_list(self):
        """If the API ever returns a plain dict, pass it through unchanged."""
        market_dict = {"id": 1849157, "closed": False}
        with patch("agents.polymarket.gamma.httpx.get",
                   return_value=self._mock_response(market_dict)):
            result = self.gamma.get_market(1849157)
        self.assertEqual(result, market_dict)

    def test_empty_list_returns_empty_list(self):
        """An empty list response should be returned as-is (falsy, not crash)."""
        with patch("agents.polymarket.gamma.httpx.get",
                   return_value=self._mock_response([])):
            result = self.gamma.get_market(1849157)
        self.assertEqual(result, [])

    def test_raises_on_non_200(self):
        """Non-200 HTTP status must raise an exception."""
        with patch("agents.polymarket.gamma.httpx.get",
                   return_value=self._mock_response({}, status_code=404)):
            with self.assertRaises(Exception) as ctx:
                self.gamma.get_market(1849157)
        self.assertIn("404", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
