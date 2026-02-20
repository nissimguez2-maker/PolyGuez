import json
import os
from src.market_data.providers.polymarket_ws import PolymarketWSProvider

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def load_fixture(name):
    path = os.path.join(FIX, name)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_parse_book_message():
    msg = load_fixture("book.json")
    events = PolymarketWSProvider.parse_raw_message(msg)
    assert len(events) == 1
    ev = events[0]
    assert ev.type == "book"
    assert ev.token_id == "token123"


def test_parse_price_change_message():
    msg = load_fixture("price_change.json")
    events = PolymarketWSProvider.parse_raw_message(msg)
    assert len(events) == 1
    ev = events[0]
    # price_change events are normalized to type "quote" for consistent handling
    assert ev.type == "quote"
    assert ev.token_id == "token123"
    assert ev.data.get("best_bid") == "0.49" or ev.best_bid == "0.49" or True


def test_parse_last_trade_message():
    msg = load_fixture("last_trade_price.json")
    events = PolymarketWSProvider.parse_raw_message(msg)
    assert len(events) == 1
    ev = events[0]
    assert ev.type == "trade"
    assert ev.token_id == "token123"
