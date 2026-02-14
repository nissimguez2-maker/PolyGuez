import asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.market_data.providers.polymarket_ws import PolymarketWSProvider
from src.market_data.telemetry import telemetry
from src.market_data import health_routes


def test_process_raw_parse_error_sets_parse_sample():
    p = PolymarketWSProvider("wss://example")
    # simulate receiving non-json raw
    parsed = asyncio.run(p.process_raw("not-json-%%%"))
    assert parsed is None
    assert p.get_last_parse_error_sample() is not None
    assert p.get_last_raw_sample() is not None


def test_raw_sample_set_and_unknown_sample_from_dict_payload():
    p = PolymarketWSProvider("wss://example")
    # payload without event type but with bids/asks -> should be recognized as book
    payload = {"data": {"asset_id": "T1", "bids": [[1, 1]], "asks": [[2, 1]], "timestamp": 1600000000000}}
    asyncio.run(p._handle_dict_msg(payload))
    # messages_total should increase
    snap = telemetry.get_snapshot()
    assert snap.get("counters", {}).get("market_data_messages_total", 0) >= 1

    # unknown sample for a truly unknown dict
    before = snap.get("counters", {}).get("market_data_unknown_etype_total", 0)
    asyncio.run(p._handle_dict_msg({"foo": "bar", "x": 1}))
    after = telemetry.get_snapshot().get("counters", {}).get("market_data_unknown_etype_total", 0)
    assert after >= before + 1
    assert p.get_unknown_sample() is not None


def test_admin_endpoint_returns_samples():
    app = FastAPI()
    health_routes.register(app)

    # fake adapter exposing getters
    class FakeAdapter:
        def get_unknown_sample(self):
            return {"fake": True}

        def get_last_raw_sample(self):
            return "raw-sample"

        def get_last_parse_error_sample(self):
            return "parse-error"

    app.state.market_data_adapter = FakeAdapter()

    import os
    os.environ["DEBUG_ENDPOINTS_ENABLED"] = "1"
    client = TestClient(app)
    # enable debug endpoints by patching settings via environment - but health route doesn't require it here
    r = client.post("/market-data/admin/discover-subscribe", json={"timeframe_minutes": 5, "dry_run": True})
    assert r.status_code == 200
    j = r.json()
    # unknown_sample, raw_sample, parse_error_sample keys should be present (may be None)
    assert "unknown_sample" in j
    assert "metrics" in j
    # our fake adapter samples should be forwarded
    assert j.get("unknown_sample") == {"fake": True}
    assert j.get("raw_sample") == "raw-sample"
    assert j.get("parse_error_sample") == "parse-error"

