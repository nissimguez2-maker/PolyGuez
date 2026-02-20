"""Tests for /confirm endpoint CLOSE action support."""
import sys
sys.path.append(".")

from webhook_server_fastapi import app
from src.config.settings import get_settings
from fastapi.testclient import TestClient


def test_confirm_accepts_close_action():
    """Test that /confirm endpoint accepts CLOSE action (alias for EXIT)."""
    s = get_settings()
    s.DEBUG_ENDPOINTS_ENABLED = True
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()

    with TestClient(app) as client:
        # Test CLOSE action - should NOT get INVALID_ACTION error
        # (will get other error like trade not found, but not INVALID_ACTION)
        r = client.post("/confirm", json={
            "trade_id": "nonexistent_trade_123",
            "action": "CLOSE",
            "action_id": "close_123"
        })
        
        # Should NOT be INVALID_ACTION error (CLOSE should be valid)
        j = r.json()
        assert "INVALID_ACTION" not in j.get("error", ""), \
            f"CLOSE should be valid action but got INVALID_ACTION error: {j}"


def test_confirm_rejects_invalid_action():
    """Test that /confirm endpoint rejects invalid actions."""
    s = get_settings()
    s.DEBUG_ENDPOINTS_ENABLED = True
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()

    with TestClient(app) as client:
        # Test invalid action
        r = client.post("/confirm", json={
            "trade_id": "trade_123",
            "action": "INVALID_ACTION",
            "action_id": "invalid_123"
        })
        
        # Should return 200 with ok=False (not raise exception)
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is False
        assert "INVALID_ACTION" in j["error"]


def test_confirm_accepts_all_valid_actions():
    """Test that /confirm accepts ADD, HEDGE, EXIT, and CLOSE."""
    s = get_settings()
    s.DEBUG_ENDPOINTS_ENABLED = True
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()

    valid_actions = ["ADD", "HEDGE", "EXIT", "CLOSE"]
    
    for action in valid_actions:
        # Each action should be accepted (not rejected as invalid)
        # We test by checking the error message - if action is invalid,
        # we get INVALID_ACTION error; otherwise we get different error (e.g., trade not found)
        with TestClient(app) as client:
            r = client.post("/confirm", json={
                "trade_id": "nonexistent_trade",
                "action": action,
                "size": 5.0 if action == "ADD" else None
            })
            
            # Should NOT be INVALID_ACTION error
            j = r.json()
            assert "INVALID_ACTION" not in j.get("error", ""), \
                f"Action {action} should be valid but got INVALID_ACTION error"
