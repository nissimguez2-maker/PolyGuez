import asyncio

import pytest


def test_rtds_unsubscribe_no_open_attr(monkeypatch):
    import asyncio
    from src.market_data.providers.polymarket_rtds import PolymarketRTDSProvider

    class DummyWS:
        # no .open attribute, no .closed
        async def send(self, msg):
            raise RuntimeError("send should not be called when not open")

    async def run():
        p = PolymarketRTDSProvider("wss://example")
        # set internal ws to dummy object missing .open
        p._ws = DummyWS()
        p._subs = ["t1", "t2"]
        # calling unsubscribe should not raise
        await p.unsubscribe(["t1"])
        assert "t1" not in p._subs

    asyncio.run(run())


def test_rtds_subscribe_when_ws_none(monkeypatch):
    import asyncio
    from src.market_data.providers.polymarket_rtds import PolymarketRTDSProvider

    async def run():
        p = PolymarketRTDSProvider("wss://example")
        p._ws = None
        p._subs = []
        # should not raise even if ws is None
        await p.subscribe(["a"])
        assert "a" in p._subs

    asyncio.run(run())

