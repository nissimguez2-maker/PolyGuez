"""Tests for quote/price_change event caching in MarketDataAdapter."""
import sys
sys.path.append(".")
import asyncio

# Mock the websockets module before importing adapter
import unittest.mock
sys.modules['websockets'] = unittest.mock.MagicMock()
sys.modules['websockets.exceptions'] = unittest.mock.MagicMock()

from src.market_data.cache import OrderBookCache
from src.market_data.schema import MarketEvent, OrderBookSnapshot


def test_quote_event_caches_best_bid_ask():
    """Test that quote events with best_bid/best_ask are properly cached."""
    cache = OrderBookCache()
    
    # Simulate what adapter._handle_event does for quote events
    raw = {"timestamp": 1234567890.0}
    raw_ob = {
        "bids": [],
        "asks": [],
        "best_bid": 0.45,
        "best_ask": 0.55,
        "best_bid_size": None,
        "best_ask_size": None,
        "timestamp": raw.get("timestamp"),
    }
    snapshot = OrderBookSnapshot.from_raw("token_123", raw_ob, source="ws_quote")
    cache.update(snapshot)
    
    # Check that the cache has the snapshot with correct best_bid/best_ask
    cached = cache.get("token_123")
    assert cached is not None, "Snapshot should be cached"
    assert cached.best_bid == 0.45, f"Expected best_bid=0.45, got {cached.best_bid}"
    assert cached.best_ask == 0.55, f"Expected best_ask=0.55, got {cached.best_ask}"
    assert cached.source == "ws_quote", f"Expected source='ws_quote', got {cached.source}"


def test_quote_event_with_partial_data():
    """Test that quote events with only best_bid or only best_ask are handled."""
    cache = OrderBookCache()
    
    # Event with only best_bid
    raw_ob = {
        "bids": [],
        "asks": [],
        "best_bid": 0.45,
        "best_ask": None,
        "best_bid_size": 100.0,
        "best_ask_size": None,
        "timestamp": 1234567890.0,
    }
    snapshot = OrderBookSnapshot.from_raw("token_456", raw_ob, source="ws_quote")
    cache.update(snapshot)
    
    cached = cache.get("token_456")
    assert cached is not None
    assert cached.best_bid == 0.45
    assert cached.best_ask is None
    assert cached.best_bid_size == 100.0


def test_book_event_caching():
    """Test that book events with bids/asks lists are properly cached."""
    cache = OrderBookCache()
    
    raw = {
        "bids": [{"price": 0.47, "size": 100}, {"price": 0.46, "size": 200}],
        "asks": [{"price": 0.53, "size": 150}, {"price": 0.54, "size": 250}],
        "timestamp": 1234567890.0
    }
    snapshot = OrderBookSnapshot.from_raw("token_789", raw, source="ws_book")
    cache.update(snapshot)
    
    cached = cache.get("token_789")
    assert cached is not None, "Snapshot should be cached for book event"
    assert cached.best_bid == 0.47, f"Expected best_bid=0.47, got {cached.best_bid}"
    assert cached.best_ask == 0.53, f"Expected best_ask=0.53, got {cached.best_ask}"
    assert len(cached.bids) == 2, f"Expected 2 bids, got {len(cached.bids)}"
    assert len(cached.asks) == 2, f"Expected 2 asks, got {len(cached.asks)}"


def test_spread_calculation():
    """Test that spread and spread_pct are calculated correctly."""
    cache = OrderBookCache()
    
    raw_ob = {
        "bids": [],
        "asks": [],
        "best_bid": 0.45,
        "best_ask": 0.55,
        "best_bid_size": None,
        "best_ask_size": None,
        "timestamp": 1234567890.0,
    }
    snapshot = OrderBookSnapshot.from_raw("token_spread", raw_ob, source="ws_quote")
    cache.update(snapshot)
    
    cached = cache.get("token_spread")
    assert cached is not None
    assert abs(cached.spread - 0.10) < 0.0001, f"Expected spread≈0.10, got {cached.spread}"
    assert abs(cached.spread_pct - 0.1818) < 0.01, f"Expected spread_pct~0.1818, got {cached.spread_pct}"
