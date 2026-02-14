import asyncio

from src.market_data.adapter import MarketDataAdapter
from src.config.settings import get_settings


class FakeProvider:
    def __init__(self):
        self.subs = []

    async def start(self):
        pass

    async def stop(self):
        pass

    async def subscribe(self, token_ids):
        self.subs.extend(token_ids)

    async def unsubscribe(self, token_ids):
        for t in token_ids:
            try:
                self.subs.remove(t)
            except ValueError:
                pass


def test_adapter_subscribe_calls_provider(monkeypatch):
    # Use FakeProvider as the WS provider
    fake = FakeProvider()
    adapter = MarketDataAdapter(provider=fake)

    # call subscribe
    asyncio.run(adapter.subscribe("tok1"))
    assert "tok1" in fake.subs


def test_adapter_subscribe_forwards_to_rtds(monkeypatch):
    settings = get_settings()
    settings.MARKET_DATA_RTDS_ENABLED = True
    settings.MARKET_DATA_RTDS_URL = "wss://example/"

    fake = FakeProvider()
    # instantiate adapter (it will create an RTDS provider)
    adapter = MarketDataAdapter(provider=fake)

    called = []

    async def fake_rtds_sub(subs):
        called.extend(subs)

    # monkeypatch the rtds_provider.subscribe method
    adapter.rtds_provider.subscribe = fake_rtds_sub

    asyncio.run(adapter.subscribe("tok2"))
    assert "tok2" in fake.subs
    assert "tok2" in called

