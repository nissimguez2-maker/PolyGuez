import asyncio
import sys


def test_adapter_unsubscribe_best_effort(monkeypatch):
    """
    If provider.unsubscribe raises, adapter.unsubscribe should catch it,
    increment telemetry counter 'market_data_unsubscribe_failed_total' and not raise.
    """
    sys.path.insert(0, ".")
    from src.market_data.adapter import MarketDataAdapter

    class DummyProvider:
        async def unsubscribe(self, token_ids):
            raise RuntimeError("boom")

    class FakeTelemetry:
        def __init__(self):
            self.counters = {}

        def incr(self, key: str, value: int = 1):
            self.counters[key] = self.counters.get(key, 0) + value

    fake_telemetry = FakeTelemetry()
    # monkeypatch the telemetry instance used by adapter.unsubscribe
    monkeypatch.setattr("src.market_data.telemetry.telemetry", fake_telemetry, raising=True)

    # create adapter and inject DummyProvider
    adapter = MarketDataAdapter(provider=None)
    adapter.provider = DummyProvider()
    adapter.rtds_provider = None
    # ensure token present
    adapter._subs.add("tok1")

    # run unsubscribe and ensure no exception, counter incremented
    async def run_unsub():
        await adapter.unsubscribe("tok1")

    asyncio.run(run_unsub())

    assert fake_telemetry.counters.get("market_data_unsubscribe_failed_total", 0) >= 1

