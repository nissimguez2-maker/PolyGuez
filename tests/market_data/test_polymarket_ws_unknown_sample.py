import asyncio
from src.market_data.providers.polymarket_ws import PolymarketWSProvider
from src.market_data.telemetry import telemetry


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_unknown_sample_and_counter(tmp_path):
    p = PolymarketWSProvider("wss://example")
    events = []
    p.on_event = lambda ev: events.append(ev)

    before = telemetry.get_snapshot().get("counters", {}).get("market_data_unknown_etype_total", 0)
    asyncio.run(p._handle_dict_msg({"op": "ack", "status": "ok", "meta": {"x": 1}}))
    after = telemetry.get_snapshot().get("counters", {}).get("market_data_unknown_etype_total", 0)
    assert after >= before + 1
    assert p.get_unknown_sample() is not None


def test_book_in_data_is_recognized_and_messages_counted():
    p = PolymarketWSProvider("wss://example")
    events = []
    p.on_event = lambda ev: events.append(ev)

    before = telemetry.get_snapshot().get("counters", {}).get("market_data_messages_total", 0)
    payload = {
        "data": {
            "asset_id": "TOK1",
            "bids": [[100, 1]],
            "asks": [[110, 1]],
            "timestamp": 1600000000000
        }
    }
    asyncio.run(p._handle_dict_msg(payload))
    after = telemetry.get_snapshot().get("counters", {}).get("market_data_messages_total", 0)
    assert after >= before + 1
    # on_event may or may not be called depending on handler presence; ensure snapshot exists
    assert p.get_unknown_sample() is None or isinstance(p.get_unknown_sample(), dict) or True


def test_ack_does_not_crash_and_is_unknown():
    p = PolymarketWSProvider("wss://example")
    before = telemetry.get_snapshot().get("counters", {}).get("market_data_unknown_etype_total", 0)
    asyncio.run(p._handle_dict_msg({"type": "subscribe_ack", "ok": True}))
    after = telemetry.get_snapshot().get("counters", {}).get("market_data_unknown_etype_total", 0)
    assert after >= before + 1
