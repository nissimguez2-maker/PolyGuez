import asyncio
from src.market_data.providers.polymarket_ws import PolymarketWSProvider
from src.market_data.telemetry import telemetry


def test_best_bid_ask_recognized_and_parsed():
    p = PolymarketWSProvider("wss://example")
    events = []
    p.on_event = lambda ev: events.append(ev)

    before_unknown = telemetry.get_snapshot().get("counters", {}).get("market_data_unknown_etype_total", 0)
    before_msgs = telemetry.get_snapshot().get("counters", {}).get("market_data_messages_total", 0)

    payload = {
        "event_type": "best_bid_ask",
        "asset_id": "TOK-1",
        "best_bid": "0.65",
        "best_ask": "0.66",
        "spread": "0.01",
        "timestamp": "1670000000000"
    }

    asyncio.run(p._handle_dict_msg(payload))

    after_unknown = telemetry.get_snapshot().get("counters", {}).get("market_data_unknown_etype_total", 0)
    after_msgs = telemetry.get_snapshot().get("counters", {}).get("market_data_messages_total", 0)

    # unknown counter should not increase for recognized best_bid_ask
    assert after_unknown == before_unknown
    assert after_msgs >= before_msgs + 1
    # ensure event emitted and token matches
    assert events, "no event emitted"
    ev = events[-1]
    assert ev.token_id == "TOK-1"
    assert ev.best_bid == float("0.65")
    assert ev.best_ask == float("0.66")
