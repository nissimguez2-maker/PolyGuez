import sys
from fastapi.testclient import TestClient

sys.path.append(".")

from webhook_server_fastapi import app
from src.market_data.reconcile import ReconcileState


def test_subscriptions_view_reports_tokens(monkeypatch):
    # prevent startup side-effects
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()

    # fake adapter with two subscriptions
    class FakeAdapter:
        def __init__(self):
            self._subs = {"T1", "T2"}

    import webhook_server_fastapi as ws
    ws._market_data_adapter = FakeAdapter()
    ws._market_data_desired_refcount = {"T1": 2, "T2": 1}
    state = ReconcileState()
    state.missing_count["T2"] = 1
    ws._market_data_reconcile_state = state
    
    # Patch settings directly using monkeypatch
    import src.config.settings as _s
    
    def get_test_settings():
        settings = _s.Settings()
        settings.DEBUG_ENDPOINTS_ENABLED = True
        settings.DEBUG_ENDPOINTS_TOKEN = "test-token"
        return settings
    
    monkeypatch.setattr(_s, "get_settings", get_test_settings)
    monkeypatch.setattr(_s, "_settings", get_test_settings())

    with TestClient(app) as client:
        r = client.get("/market-data/subscriptions", headers={"X-Debug-Token": "test-token"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["active_subscriptions"] == 2
        tokens = {t["token_id"]: t for t in data["tokens"]}
        assert tokens["T1"]["refcount"] == 2
        assert tokens["T2"]["refcount"] == 1
        assert tokens["T2"]["missing_cycles"] == 1
