import time

from src.market_data.providers.polymarket_rtds import PolymarketRTDSProvider


def test_rtds_parse_simple_message():
    msg = {
        "topic": "crypto_prices",
        "payload": {"token": "BTCUSD", "best_bid": 0.01, "best_ask": 0.02},
    }
    events = PolymarketRTDSProvider.parse_raw_message(msg)
    assert isinstance(events, list)
    assert len(events) == 1
    ev = events[0]
    assert ev.token_id == "BTCUSD"
    assert ev.type == "price_change"
    assert ev.best_bid == 0.01
    assert ev.best_ask == 0.02

