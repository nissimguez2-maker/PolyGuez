import time
import pytest

from src.order_executor import place_entry_order_with_gate
from src.config.settings import get_settings
from src.market_data.telemetry import telemetry


class DummyPolymarket:
    def __init__(self):
        self.called = False

    def execute_order(self, price, size, side, token_id, gate_checked=False):
        self.called = True
        assert gate_checked is True  # enforce gate flag
        return "order_123"


class FakeLevel:
    def __init__(self, price, size):
        self.price = price
        self.size = size


class FakeOrderBook:
    def __init__(self, bids=None, asks=None, timestamp=None):
        self.bids = bids or []
        self.asks = asks or []
        self.timestamp = timestamp or time.time()


class FakeAdapter:
    def __init__(self, book=None):
        self.book = book

    def get_orderbook(self, token_id):
        return self.book


def test_executor_blocks_on_wide_spread():
    settings = get_settings()
    settings.MAX_ENTRY_SPREAD = 0.05
    pm = DummyPolymarket()
    book = FakeOrderBook(bids=[FakeLevel(0.01, 10)], asks=[FakeLevel(0.60, 10)], timestamp=time.time())
    adapter = FakeAdapter(book=book)
    # create isolated RiskManager to avoid repo legacy logs influencing kill-switch
    from agents.application.risk_manager import RiskManager
    # ensure primary paper log exists and contains no closed trades to avoid legacy fallback
    import tempfile, os
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
    tf.write(b"{}\n")
    tf.flush()
    tf.close()
    settings.PAPER_LOG_PATH = tf.name
    rm = RiskManager(settings.INITIAL_EQUITY, settings.MAX_EXPOSURE_PCT, settings.BASE_RISK_PCT)
    res = place_entry_order_with_gate(polymarket=pm, token_id="t1", price=0.02, size=1.0, side="BUY", adapter=adapter, risk_manager=rm)
    assert res["allowed"] is False
    assert res["reason"] in ("spread_too_wide", "spread_hard_reject")
    assert not pm.called


def test_executor_allows_and_calls_polymarket_on_ok_spread():
    settings = get_settings()
    settings.MAX_ENTRY_SPREAD = 0.5
    pm = DummyPolymarket()
    book = FakeOrderBook(bids=[FakeLevel(0.01, 10)], asks=[FakeLevel(0.02, 10)], timestamp=time.time())
    adapter = FakeAdapter(book=book)
    from agents.application.risk_manager import RiskManager
    import tempfile
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
    tf.write(b"{}\n")
    tf.flush()
    tf.close()
    settings.PAPER_LOG_PATH = tf.name
    rm = RiskManager(settings.INITIAL_EQUITY, settings.MAX_EXPOSURE_PCT, settings.BASE_RISK_PCT)
    res = place_entry_order_with_gate(polymarket=pm, token_id="t2", price=0.015, size=1.0, side="BUY", adapter=adapter, risk_manager=rm)
    assert res["allowed"] is True
    assert res.get("order_id") == "order_123"
    assert pm.called


def find_key_for_bucket(target: int) -> str:
    from src.utils.ab_router import ab_bucket
    i = 0
    while True:
        k = f"test-key-{i}"
        if ab_bucket(k) == target:
            return k
        i += 1


def test_variant_blocks_on_spread_but_control_allows(tmp_path):
    settings = get_settings()
    # ensure variant threshold is set
    settings.MAX_SPREAD_PCT_VARIANT = 0.03
    settings.ENTRY_FILTERS_AB_ENABLED = True
    # ensure edge filter not active for this specific spread test
    settings.MIN_EDGE_CENTS_VARIANT = None
    # find keys
    variant_key = find_key_for_bucket(1)
    control_key = find_key_for_bucket(0)

    pm = DummyPolymarket()
    # wide spread book
    book = FakeOrderBook(bids=[FakeLevel(0.49, 10)], asks=[FakeLevel(0.52, 10)], timestamp=time.time())
    adapter = FakeAdapter(book=book)
    from agents.application.risk_manager import RiskManager
    tf = tmp_path / "paper.jsonl"
    tf.write_text("{}\n")
    settings.PAPER_LOG_PATH = str(tf)
    rm = RiskManager(settings.INITIAL_EQUITY, settings.MAX_EXPOSURE_PCT, settings.BASE_RISK_PCT)

    # variant should be blocked (spread ~ (0.52-0.49)/0.505 ≈ 0.059 > 0.03)
    res_variant = place_entry_order_with_gate(polymarket=pm, token_id=variant_key, price=0.505, size=1.0, side="BUY", adapter=adapter, risk_manager=rm)
    assert res_variant["allowed"] is False
    assert res_variant["reason"] == "max_spread_pct"

    # control should allow (filters not applied for control)
    pm2 = DummyPolymarket()
    res_control = place_entry_order_with_gate(polymarket=pm2, token_id=control_key, price=0.505, size=1.0, side="BUY", adapter=adapter, risk_manager=rm)
    assert res_control["allowed"] is True
    assert pm2.called


def test_variant_blocks_on_edge_but_control_allows(tmp_path):
    settings = get_settings()
    settings.MIN_EDGE_CENTS_VARIANT = 0.02
    settings.ENTRY_FILTERS_AB_ENABLED = True
    variant_key = find_key_for_bucket(1)
    control_key = find_key_for_bucket(0)

    pm = DummyPolymarket()
    # mid ~0.50; price very close to mid -> small edge
    book = FakeOrderBook(bids=[FakeLevel(0.49, 10)], asks=[FakeLevel(0.51, 10)], timestamp=time.time())
    adapter = FakeAdapter(book=book)
    from agents.application.risk_manager import RiskManager
    tf = tmp_path / "paper2.jsonl"
    tf.write_text("{}\n")
    settings.PAPER_LOG_PATH = str(tf)
    rm = RiskManager(settings.INITIAL_EQUITY, settings.MAX_EXPOSURE_PCT, settings.BASE_RISK_PCT)

    # price chosen very close to mid (edge 0.005) < 0.02 -> variant blocked
    res_variant = place_entry_order_with_gate(polymarket=pm, token_id=variant_key, price=0.5005, size=1.0, side="BUY", adapter=adapter, risk_manager=rm)
    assert res_variant["allowed"] is False
    assert res_variant["reason"] == "min_edge"

    # control should allow
    pm2 = DummyPolymarket()
    res_control = place_entry_order_with_gate(polymarket=pm2, token_id=control_key, price=0.5005, size=1.0, side="BUY", adapter=adapter, risk_manager=rm)
    assert res_control["allowed"] is True
    assert pm2.called

