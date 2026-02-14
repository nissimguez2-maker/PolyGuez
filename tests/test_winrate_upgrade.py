import os
import time
from src.utils.winrate_upgrade import check_market_quality_for_entry, ConfirmationStore


def test_check_mq_no_ask():
    class S: pass
    settings = type("S", (), {"MAX_SPREAD_ENTRY": 0.1, "MIN_ASK_SIZE": 5.0, "ENFORCE_DEPTH": True})()
    ok, reason, details = check_market_quality_for_entry(None, None, None, settings)
    assert not ok and reason == "no_entry_price"


def test_check_mq_spread_too_wide():
    settings = type("S", (), {"MAX_SPREAD_ENTRY": 0.1, "MIN_ASK_SIZE": 5.0, "ENFORCE_DEPTH": False})()
    ok, reason, details = check_market_quality_for_entry(0.5, 0.7, 10.0, settings)
    assert not ok and reason == "spread_too_wide"


def test_confirmation_store_delay_and_ttl(tmp_path):
    p = tmp_path / "pending.json"
    store = ConfirmationStore(str(p))
    key = "mkt|BULL|sig1"
    store.mark_pending(key, {"foo": "bar"})
    confirmed, _ = store.pop_if_confirmed(key, delay=1, ttl=5)
    assert not confirmed
    time.sleep(1.1)
    confirmed, payload = store.pop_if_confirmed(key, delay=1, ttl=5)
    assert confirmed
    assert payload is not None

