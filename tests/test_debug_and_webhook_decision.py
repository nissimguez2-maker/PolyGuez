import json
from pathlib import Path

from fastapi.testclient import TestClient

import webhook_server_fastapi as ws
from src.config.settings import get_settings


class _Exposure:
    allowed = True
    reason = "ok"
    current_exposure = 0.0
    proposed_exposure = 1.0
    max_exposure = 10.0


class _FakeRiskManager:
    def calculate_position_size(self, confidence, base_size=None):
        return 1.0

    def check_exposure(self, proposed_trade_size, active_trades):
        return _Exposure()

    def check_direction_limit(self, side, active_trades):
        return True, "ok"


class _Trade:
    def __init__(self):
        self.trade_id = "trade_test_1"
        self.entry_price = 0.5


class _FakePositionManager:
    def __init__(self):
        self.active_trades = {}

    def create_trade(self, **kwargs):
        return _Trade()


def test_debug_config_endpoint_gate_and_openapi(monkeypatch):
    settings = get_settings()
    ws.app.router.on_startup.clear()
    ws.app.router.on_shutdown.clear()

    with TestClient(ws.app) as client:
        settings.DEBUG_ENDPOINTS_ENABLED = False
        r = client.get("/debug/config")
        assert r.status_code == 404

        settings.DEBUG_ENDPOINTS_ENABLED = True
        r = client.get("/debug/config")
        assert r.status_code == 200
        payload = r.json()
        assert "trading_mode" in payload
        assert "active_subscriptions" in payload

        openapi = client.get("/openapi.json").json()
        assert "/debug/config" in openapi["paths"]


def test_webhook_logs_decision_and_writes_paper_trade(tmp_path, monkeypatch, caplog):
    settings = get_settings()
    ws.app.router.on_startup.clear()
    ws.app.router.on_shutdown.clear()
    settings.TRADING_MODE = "paper"
    settings.DRY_RUN = False
    settings.DEBUG_ENDPOINTS_ENABLED = True
    settings.ENABLE_MARKET_QUALITY_GATE = False
    settings.ENABLE_PATTERN_GATE = False
    settings.WINRATE_UPGRADE_ENABLED = False
    settings.MIN_CONFIDENCE = 5
    settings.MAX_CONFIDENCE = 5
    settings.PAPER_LOG_PATH = str(tmp_path / "paper_trades.jsonl")
    settings.SESSION_ID = "test-session"

    monkeypatch.setattr(ws, "fetch_market_by_slug", lambda slug: {"id": "m1", "question": "q"})
    monkeypatch.setattr(ws, "resolve_up_down_tokens", lambda market: ("T1", "T2"))
    monkeypatch.setattr(
        ws,
        "_get_entry_price_for_trade",
        lambda token_id: {
            "entry_price": 0.5,
            "entry_method": "mid",
            "entry_ob_timestamp": "2026-01-01T00:00:00Z",
            "best_bid": 0.49,
            "best_ask": 0.51,
            "price_source": "test",
            "retry_used": False,
        },
    )
    monkeypatch.setattr(ws, "get_risk_manager", lambda: _FakeRiskManager())
    monkeypatch.setattr(ws, "get_position_manager", lambda: _FakePositionManager())

    payload = {
        "signal": "BULL",
        "signal_id": "sig-1",
        "confidence": 5,
        "rawConf": 5,
        "session": "LONDON",
    }

    with TestClient(ws.app) as client:
        caplog.clear()
        with caplog.at_level("INFO"):
            res = client.post("/webhook", json=payload)
        assert res.status_code == 200
        assert res.json().get("ok") is True

    assert "SIGNAL DECISION: decision=ENTER" in caplog.text

    log_path = Path(settings.PAPER_LOG_PATH)
    lines = [ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    trade = json.loads(lines[0])
    assert trade["trade_id"] == "trade_test_1"
