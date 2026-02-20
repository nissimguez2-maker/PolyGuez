import pytest


class DummyTelemetry:
    def __init__(self):
        self.gauges = {}
        self.set_calls = []

    def set_gauge(self, key: str, value: float):
        self.gauges[key] = value
        self.set_calls.append((key, value))


class DummyAdapter:
    def __init__(self, subs):
        self._subs = set(subs)


def test_update_subs_gauge_updates_telemetry(monkeypatch):
    from src.market_data.telemetry_helpers import update_subs_gauge
    telemetry = DummyTelemetry()
    adapter = DummyAdapter(["t1", "t2", "t3"])
    count = update_subs_gauge(adapter, telemetry)
    assert count == 3
    assert telemetry.set_calls
    assert telemetry.gauges.get("market_data_active_subscriptions") == 3.0

def test_update_subs_gauge_after_unsubscribe(monkeypatch):
    from src.market_data.telemetry_helpers import update_subs_gauge
    telemetry = DummyTelemetry()
    adapter = DummyAdapter(["t1", "t2"])
    update_subs_gauge(adapter, telemetry)
    # simulate unsubscribe
    adapter._subs.remove("t1")
    telemetry.set_calls.clear()
    count = update_subs_gauge(adapter, telemetry)
    assert count == 1
    assert telemetry.gauges.get("market_data_active_subscriptions") == 1.0

