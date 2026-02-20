import asyncio
import time

from src.market_data.providers.polymarket_rest import PolymarketRESTProvider


class DummyOrder:
    def __init__(self, bids=None, asks=None, timestamp=None):
        self.bids = bids or []
        self.asks = asks or []
        self.timestamp = timestamp or time.time()


def test_rest_refresh_returns_market_event(monkeypatch):
    # Arrange: monkeypatch Polymarket.get_orderbook to return a dummy orderbook
    class FakePolymarket:
        def get_orderbook(self, token_id):
            return DummyOrder(bids=[type("L", (), {"price": 0.01, "size": 10})], asks=[type("L", (), {"price": 0.02, "size": 5})], timestamp=time.time())

    monkeypatch.setattr("agents.polymarket.polymarket.Polymarket", FakePolymarket)
    provider = PolymarketRESTProvider()

    # Act: call refresh (async)
    ev = asyncio.run(provider.refresh("token123"))

    # Assert: event returned with expected token and best prices
    assert ev is not None
    assert ev.type == "book"
    assert ev.token_id == "token123"
    assert ev.best_bid == 0.01
    assert ev.best_ask == 0.02

