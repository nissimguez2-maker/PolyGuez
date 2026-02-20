import sys
import time

from fastapi.testclient import TestClient

sys.path.append(".")

import webhook_server_fastapi as ws
from src.config.settings import get_settings
from src.market_data.telemetry import telemetry


def test_discover_subscribe_updates_subscriptions_and_health(monkeypatch):
    settings = get_settings()
    settings.DEBUG_ENDPOINTS_ENABLED = True
    settings.DEBUG_ENDPOINTS_TOKEN = "tok"

    # prevent startup hooks from replacing fake adapter with real networked adapter
    ws.app.router.on_startup.clear()
    ws.app.router.on_shutdown.clear()

    # keep telemetry deterministic for this test
    telemetry.counters.clear()
    telemetry.gauges.clear()
    telemetry.set_last_msg_ts(None)

    def fake_find(tf, now, http_client, signal_id=None):
        return {
            "market": {"slug": "btc-updown-5m-1000", "id": "m1", "clobTokenIds": ["T1", "T2"]},
            "clobTokenIds": ["T1", "T2"],
        }

    monkeypatch.setattr("src.market_data.health_routes.find_current_btc_updown_market", fake_find)

    class FakeAdapter:
        def __init__(self):
            self._subs = set()
            self.calls = []
            self._started = True

        async def subscribe(self, token):
            self.calls.append(token)
            self._subs.add(token)

        async def unsubscribe(self, token):
            self._subs.discard(token)

        def inject_sample_ws_event(self):
            telemetry.incr("market_data_messages_total", 1)
            telemetry.set_last_msg_ts(time.time())

    fake = FakeAdapter()
    ws.app.state.market_data_adapter = fake

    with TestClient(ws.app) as client:
        resp = client.post(
            "/market-data/admin/discover-subscribe",
            headers={"X-Debug-Token": "tok"},
            json={"timeframe_minutes": 5, "dry_run": False, "wait_seconds": 0},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["ok"] is True
        assert payload["subscriptions"]["active_subscriptions"] > 0
        assert len(fake.calls) == 2

        fake.inject_sample_ws_event()
        health = client.get("/market-data/health")
        assert health.status_code == 200
        health_payload = health.json()
        assert health_payload["active_subscriptions"] > 0
        assert health_payload["last_msg_age_s"] is not None
