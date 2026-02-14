import asyncio
import pytest

from src.market_data.event_bus import AsyncEventBus
from src.market_data.telemetry import telemetry
from src.market_data.schema import MarketEvent


def make_event(i: int) -> MarketEvent:
    return MarketEvent(ts=1.0 + i, type="book", token_id=str(i), best_bid=None, best_ask=None, spread_pct=None, data={})


def test_subscribe_unsubscribe_loop():
    bus = AsyncEventBus(queue_maxsize=10)
    q = bus.subscribe("t1")
    assert q is not None

    # publish one event and receive
    ev = make_event(1)
    asyncio.run(bus.publish(ev))
    got = asyncio.run(q.get())
    assert got.token_id == ev.token_id

    bus.unsubscribe("t1")
    # publish should not raise
    asyncio.run(bus.publish(make_event(2)))
    # after unsubscribe queue stays and won't get new events
    assert q.empty()


def test_backpressure_drop_on_full():
    telemetry.counters.clear()
    bus = AsyncEventBus(queue_maxsize=2)
    q1 = bus.subscribe("s1")
    # fill and overflow
    asyncio.run(bus.publish(make_event(1)))
    asyncio.run(bus.publish(make_event(2)))
    # this publish will drop oldest and increment telemetry
    asyncio.run(bus.publish(make_event(3)))
    # ensure dropped counter incremented
    assert telemetry.counters.get("market_data_eventbus_dropped_total", 0) >= 1
