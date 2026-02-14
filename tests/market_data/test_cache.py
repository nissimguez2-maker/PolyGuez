import time
import threading
import pytest

from src.market_data.cache import OrderBookCache
from src.market_data.schema import OrderBookSnapshot, OrderBookLevel


def make_snapshot(token_id: str, best_bid: float, best_ask: float, ts: float = None):
    ts = ts or time.time()
    bids = [OrderBookLevel(price=best_bid, size=1.0)]
    asks = [OrderBookLevel(price=best_ask, size=1.0)]
    return OrderBookSnapshot(token_id=token_id, timestamp=ts, best_bid=best_bid, best_ask=best_ask, best_bid_size=1.0, best_ask_size=1.0, spread=abs(best_ask-best_bid), spread_pct=(abs(best_ask-best_bid)/best_ask if best_ask else None), bids=bids, asks=asks, source="test")


def test_update_snapshot_and_best_prices():
    c = OrderBookCache()
    snap = make_snapshot("t1", 0.49, 0.51)
    c.update(snap)
    got = c.get("t1")
    assert got is not None
    assert got.best_bid == 0.49
    assert got.best_ask == 0.51


def test_stale_detection():
    c = OrderBookCache()
    old_ts = time.time() - 1000
    snap = make_snapshot("t2", 0.4, 0.6, ts=old_ts)
    c.update(snap)
    age = c.get_age("t2")
    assert age is not None and age > 900


def test_thread_safety_smoke():
    c = OrderBookCache()

    def writer():
        for i in range(100):
            snap = make_snapshot("tok", 0.1 + i*0.001, 0.9)
            c.update(snap)

    def reader():
        for _ in range(100):
            _ = c.get("tok")

    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=reader)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    # smoke: no exceptions and cache returns snapshot
    assert c.get("tok") is not None
