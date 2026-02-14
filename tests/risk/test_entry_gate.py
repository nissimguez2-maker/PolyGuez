import json
import time
import pytest

from agents.application.risk_manager import RiskManager
from src.config.settings import get_settings
from src.market_data.telemetry import telemetry


class FakeLevel:
    def __init__(self, price, size):
        self.price = price
        self.size = size


class FakeOrderBook:
    def __init__(self, bids=None, asks=None, timestamp=None):
        self.bids = bids or []
        self.asks = asks or []
        # timestamp in seconds
        self.timestamp = timestamp or time.time()


class FakeAdapter:
    def __init__(self, book: FakeOrderBook = None):
        self._book = book

    def get_orderbook(self, token_id):
        return self._book


@pytest.fixture(autouse=True)
def reset_telemetry_and_settings(tmp_path, monkeypatch):
    # reset telemetry counters/gauges
    telemetry.counters.clear()
    telemetry.gauges.clear()
    # ensure settings use conservative defaults for tests
    settings = get_settings()
    settings.MAX_ENTRY_SPREAD = 0.05
    settings.HARD_REJECT_SPREAD = 0.30
    settings.ENTRY_REQUIRE_FRESH_BOOK = True
    settings.ENTRY_MAX_BOOK_AGE_SECONDS = 20
    settings.REQUIRE_MARKET_QUALITY_HEALTHY = True
    settings.DISABLE_CONFIDENCE_GE = 7
    settings.MIN_TOP_LEVEL_SIZE = 0.0
    settings.KILL_SWITCH_ENABLED = True
    settings.KILL_SWITCH_LOOKBACK_CLOSED = 3
    settings.KILL_SWITCH_MAX_REALIZED_LOSS = -5.0
    settings.KILL_SWITCH_MIN_WINRATE = 0.25
    yield


def test_block_confidence_ge_7():
    rm = RiskManager(100.0, 0.25, 0.02)
    allowed, reason, _ = rm.check_entry_allowed(token_id="t1", confidence=7, adapter=FakeAdapter())
    assert not allowed
    assert reason == "confidence_disabled"


def test_block_when_no_orderbook():
    rm = RiskManager(100.0, 0.25, 0.02)
    allowed, reason, _ = rm.check_entry_allowed(token_id="t1", confidence=5, adapter=FakeAdapter(book=None))
    assert not allowed
    assert reason == "no_orderbook"


def test_block_when_stale_orderbook():
    rm = RiskManager(100.0, 0.25, 0.02)
    old_ts = time.time() - 60
    book = FakeOrderBook(bids=[FakeLevel(0.01, 10)], asks=[FakeLevel(0.99, 10)], timestamp=old_ts)
    adapter = FakeAdapter(book=book)
    allowed, reason, details = rm.check_entry_allowed(token_id="t1", confidence=5, adapter=adapter)
    assert not allowed
    assert reason == "stale_orderbook"
    assert "book_age_s" in details


def test_block_when_spread_too_wide():
    rm = RiskManager(100.0, 0.25, 0.02)
    book = FakeOrderBook(bids=[FakeLevel(0.01, 10)], asks=[FakeLevel(0.50, 10)], timestamp=time.time())
    adapter = FakeAdapter(book=book)
    allowed, reason, _ = rm.check_entry_allowed(token_id="t1", confidence=5, adapter=adapter)
    assert not allowed
    assert reason in ("spread_too_wide", "spread_hard_reject")
    if reason == "spread_too_wide":
        assert telemetry.counters.get("market_data_blocked_spread_total", 0) >= 1


def test_hard_reject_spread():
    rm = RiskManager(100.0, 0.25, 0.02)
    book = FakeOrderBook(bids=[FakeLevel(0.01, 10)], asks=[FakeLevel(0.40, 10)], timestamp=time.time())
    adapter = FakeAdapter(book=book)
    # set HARD_REJECT_SPREAD low for test
    settings = get_settings()
    settings.HARD_REJECT_SPREAD = 0.1
    allowed, reason, _ = rm.check_entry_allowed(token_id="t1", confidence=5, adapter=adapter)
    assert not allowed
    assert reason == "spread_hard_reject"


def test_block_when_quality_unhealthy():
    rm = RiskManager(100.0, 0.25, 0.02)
    # pass a healthy orderbook but upstream market_quality_healthy=False
    book = FakeOrderBook(bids=[FakeLevel(0.01, 10)], asks=[FakeLevel(0.02, 10)], timestamp=time.time())
    adapter = FakeAdapter(book=book)
    allowed, reason, _ = rm.check_entry_allowed(token_id="t1", confidence=5, market_quality_healthy=False, adapter=adapter)
    assert not allowed
    assert reason == "market_quality_unhealthy"


def test_kill_switch_blocks_entries(tmp_path):
    # write recent closed trades with large negative pnl
    p = tmp_path / "paper_trades.jsonl"
    lines = [
        json.dumps({"trade_id": "t1", "realized_pnl": -2.0, "exit_time_utc": "2026-01-01T00:00:00Z"}),
        json.dumps({"trade_id": "t2", "realized_pnl": -2.0, "exit_time_utc": "2026-01-01T01:00:00Z"}),
        json.dumps({"trade_id": "t3", "realized_pnl": -2.0, "exit_time_utc": "2026-01-01T02:00:00Z"}),
    ]
    p.write_text("\n".join(lines), encoding="utf-8")
    settings = get_settings()
    settings.PAPER_LOG_PATH = str(p)
    settings.KILL_SWITCH_LOOKBACK_CLOSED = 3
    settings.KILL_SWITCH_MAX_REALIZED_LOSS = -5.0
    settings.KILL_SWITCH_MIN_WINRATE = 0.25

    rm = RiskManager(100.0, 0.25, 0.02)
    allowed, reason, _ = rm.check_entry_allowed(token_id="t1", confidence=5, adapter=FakeAdapter(book=FakeOrderBook(bids=[FakeLevel(0.01,10)], asks=[FakeLevel(0.02,10)], timestamp=time.time())))
    assert not allowed
    assert reason == "kill_switch"
    assert telemetry.gauges.get("market_data_kill_switch_active", 0) == 1

