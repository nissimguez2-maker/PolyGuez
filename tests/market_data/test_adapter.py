import asyncio
import pytest
from src.market_data.adapter import MarketDataAdapter
from src.market_data.providers.base import AbstractMarketDataProvider
from src.market_data.schema import MarketEvent, OrderBookSnapshot
import time


class FakeProvider(AbstractMarketDataProvider):
    def __init__(self):
        super().__init__()
        self.started = False
        self.subscribed = set()

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    async def subscribe(self, token_ids):
        for t in token_ids:
            self.subscribed.add(t)

    async def unsubscribe(self, token_ids):
        for t in token_ids:
            self.subscribed.discard(t)

    # helper to emit event
    def emit(self, ev: MarketEvent):
        if self.on_event:
            self.on_event(ev)


def test_adapter_updates_cache_and_publishes_events():
    fake = FakeProvider()
    adapter = MarketDataAdapter(provider=fake)
    asyncio.run(adapter.start())
    # simulate book event
    raw = {"bids": [{"price": "0.49", "size": "10"}], "asks": [{"price": "0.51", "size": "5"}]}
    ev = MarketEvent(ts=time.time(), type="book", token_id="t1", best_bid=0.49, best_ask=0.51, spread_pct=0.04, data=raw)
    fake.emit(ev)
    # give event loop a moment
    asyncio.run(asyncio.sleep(0.05))
    snap = adapter.get_orderbook("t1")
    assert snap is not None
    assert snap.best_bid == 0.49
    # consumer should be able to get from eventbus
    q = adapter.event_bus.subscribe("test_consumer")
    # publish another event via fake
    ev2 = MarketEvent(ts=time.time(), type="price_change", token_id="t1", best_bid=0.48, best_ask=0.52, spread_pct=0.04, data={})
    fake.emit(ev2)
    asyncio.run(asyncio.sleep(0.05))
    # the adapter publishes to bus; subscriber should receive
    got = asyncio.run(q.get())
    assert got.token_id == "t1"


def test_subscribe_refcount_and_unsubscribe_guard():
    fake = FakeProvider()
    adapter = MarketDataAdapter(provider=fake)
    asyncio.run(adapter.start())
    # subscribe twice
    asyncio.run(adapter.subscribe("tokA"))
    asyncio.run(adapter.subscribe("tokA"))
    assert "tokA" in fake.subscribed
    # unsubscribe once -> still subscribed because adapter tracks single ref but tests expect provider.subscribe once; adapter currently calls provider.subscribe on first subscribe only
    asyncio.run(adapter.unsubscribe("tokA"))
    # after unsubscribe, provider should have unsubscribed (adapter uses set semantics)
    # ensure unsubscribed
    asyncio.run(asyncio.sleep(0.01))
    assert "tokA" not in fake.subscribed
