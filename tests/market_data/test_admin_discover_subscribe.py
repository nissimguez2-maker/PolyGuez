import sys
import json
from fastapi.testclient import TestClient
sys.path.append(".")

from webhook_server_fastapi import app
from src.config.settings import get_settings


def test_endpoint_disabled():
    # ensure disabled
    get_settings().DEBUG_ENDPOINTS_ENABLED = False
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()
    with TestClient(app) as client:
        r = client.post("/market-data/admin/discover-subscribe", json={})
        assert r.status_code == 404


def test_dry_run_discovery(monkeypatch):
    # enable debug
    s = get_settings()
    s.DEBUG_ENDPOINTS_ENABLED = True
    s.DEBUG_ENDPOINTS_TOKEN = "tok"
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()

    # monkeypatch discovery to return fake market
    def fake_find(tf, now, http_client, signal_id=None):
        return {"market": {"slug": "btc-updown-5m-1000", "id": "m1", "clobTokenIds": ["A","B"]}, "clobTokenIds": ["A","B"]}
    # patch the symbol used by the endpoint module directly
    monkeypatch.setattr("src.market_data.health_routes.find_current_btc_updown_market", fake_find)

    with TestClient(app) as client:
        r = client.post("/market-data/admin/discover-subscribe", headers={"X-Debug-Token": "tok"}, json={"timeframe_minutes":5, "dry_run": True, "wait_seconds": 0})
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True
        assert j["clob_token_ids"] == ["A","B"]
        assert j["subscribed_count"] == 0


def test_subscribe_invoked(monkeypatch):
    # enable debug
    s = get_settings()
    s.DEBUG_ENDPOINTS_ENABLED = True
    s.DEBUG_ENDPOINTS_TOKEN = "tok"
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()

    # fake discovery
    def fake_find(tf, now, http_client, signal_id=None):
        return {"market": {"slug": "btc-updown-5m-1000", "id": "m1", "clobTokenIds": ["T1","T2"]}, "clobTokenIds": ["T1","T2"]}
    # patch the symbol used by the endpoint module directly
    monkeypatch.setattr("src.market_data.health_routes.find_current_btc_updown_market", fake_find)

    # fake adapter
    class FakeAdapter:
        def __init__(self):
            self._subs = set()
            self.calls = []
        async def subscribe(self, token):
            self.calls.append(token)
            self._subs.add(token)

    import webhook_server_fastapi as ws
    ws._market_data_adapter = FakeAdapter()

    with TestClient(app) as client:
        r = client.post("/market-data/admin/discover-subscribe", headers={"X-Debug-Token": "tok"}, json={"timeframe_minutes":5, "dry_run": False, "wait_seconds": 0})
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True
        assert j["subscribed_count"] == 2
        # adapter recorded two subscribes
        assert len(ws._market_data_adapter.calls) == 2

