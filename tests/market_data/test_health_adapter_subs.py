import pytest
from fastapi.testclient import TestClient

def test_health_uses_adapter_subs(monkeypatch):
    # import app and clear startup/shutdown to avoid side-effects
    from webhook_server_fastapi import app
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()

    # create dummy adapter with _subs
    class DummyAdapter:
        def __init__(self, subs):
            self._subs = set(subs)

    import webhook_server_fastapi as ws
    # ensure telemetry gauge differs
    from src.market_data.telemetry import telemetry
    telemetry.set_gauge("market_data_active_subscriptions", 0.0)

    ws._market_data_adapter = DummyAdapter(["a", "b"])

    with TestClient(app) as client:
        r = client.get("/market-data/health")
        assert r.status_code == 200
        data = r.json()
        # active_subscriptions should reflect adapter._subs (2) not telemetry previous value
        assert data["active_subscriptions"] == 2

