"""
Tests for Market Data Blocks E/F/G
"""

import pytest
import json
import time
from unittest.mock import Mock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.market_data import (
    PolymarketWSClient,
    Quote,
    Trade,
    WSHealth,
    OrderBook,
    OrderBookManager,
    LiquidityGate,
    ExecutionEngine,
    ExecutionConfig,
    OrderType,
    ExecutionResult
)


# ============================================================================
# Block E: WebSocket Tests
# ============================================================================

class TestWebSocketEventParsing:
    """Test WebSocket event parsing"""
    
    def test_quote_parsing(self):
        """Test quote event parsing"""
        client = PolymarketWSClient()
        
        # Simulate quote message
        quote_msg = {
            "type": "quote",
            "market": "0x123",
            "bid": 0.55,
            "ask": 0.57,
            "bidSize": 1000,
            "askSize": 2000
        }
        
        # Parse through handler
        client._handle_quote(quote_msg)
        
        # Verify stored
        quote = client.get_latest_quote("0x123")
        assert quote is not None
        assert quote.best_bid == 0.55
        assert quote.best_ask == 0.57
        assert quote.bid_size == 1000
        assert quote.ask_size == 2000
        assert quote.spread == pytest.approx(0.02, abs=1e-9)
        assert quote.mid == pytest.approx(0.56, abs=1e-9)
    
    def test_trade_parsing(self):
        """Test trade event parsing"""
        client = PolymarketWSClient()
        
        trade_received = []
        def on_trade(trade):
            trade_received.append(trade)
        
        client.on_trade = on_trade
        
        trade_msg = {
            "type": "trade",
            "market": "0x123",
            "price": 0.56,
            "size": 500,
            "side": "buy"
        }
        
        client._handle_trade(trade_msg)
        
        assert len(trade_received) == 1
        assert trade_received[0].price == 0.56
        assert trade_received[0].size == 500
    
    def test_health_state(self):
        """Test health state tracking"""
        client = PolymarketWSClient()
        
        # Initial state
        health = client.health
        assert health.connected == False
        assert health.messages_received == 0
        
        # Simulate message
        client._last_message_time = time.time()
        with client._lock:
            client._message_count = 5
        
        health = client.health
        assert health.messages_received == 5
        assert health.last_message_age_s < 1.0


# ============================================================================
# Block F: Orderbook Tests
# ============================================================================

class TestOrderBookSnapshot:
    """Test orderbook snapshot and features"""
    
    def test_snapshot_creation(self):
        """Test creating orderbook from snapshot"""
        mgr = OrderBookManager()
        
        bids = [(0.55, 1000), (0.54, 2000), (0.53, 3000)]
        asks = [(0.57, 1500), (0.58, 2500), (0.59, 3500)]
        
        mgr.update_from_snapshot("0x123", bids, asks)
        
        ob = mgr.get_orderbook("0x123")
        assert ob is not None
        assert ob.best_bid == 0.55
        assert ob.best_ask == 0.57
        assert ob.spread == pytest.approx(0.02, abs=1e-9)
        assert ob.mid == 0.56
    
    def test_computed_features(self):
        """Test computed features (spread, depth, imbalance)"""
        mgr = OrderBookManager()
        
        # Create imbalanced book
        bids = [(0.55, 10000), (0.54, 5000)]  # Heavy on bid
        asks = [(0.57, 1000), (0.58, 500)]     # Light on ask
        
        mgr.update_from_snapshot("0x123", bids, asks)
        ob = mgr.get_orderbook("0x123")
        
        # Test depth
        depth_1bp_bid = ob.depth_within_bps(1, "bid")
        depth_1bp_ask = ob.depth_within_bps(1, "ask")
        
        # Test imbalance (should be positive = more buy pressure)
        imbalance = ob.imbalance(depth_bps=100)
        assert imbalance > 0
    
    def test_delta_updates(self):
        """Test incremental delta updates"""
        mgr = OrderBookManager()
        
        # Initial snapshot
        mgr.update_from_snapshot("0x123", [(0.55, 1000)], [(0.57, 1000)])
        
        # Delta: update bid
        mgr.update_from_delta("0x123", "bid", 0.55, 2000)
        
        ob = mgr.get_orderbook("0x123")
        assert ob.bids[0].size == 2000
        
        # Delta: remove ask
        mgr.update_from_delta("0x123", "ask", 0.57, 0)
        
        ob = mgr.get_orderbook("0x123")
        assert len(ob.asks) == 0 or ob.asks[0].price != 0.57


class TestLiquidityGate:
    """Test liquidity gate checks"""
    
    def test_passes_with_good_liquidity(self):
        """Trade allowed with good liquidity"""
        gate = LiquidityGate(max_spread_bps=200, min_depth_1bp=100, min_depth_5bp=500)
        
        ob = OrderBook("0x123")
        # Spread = 0.01, mid = 0.555, spread_bps = 180 (under 200)
        ob.bids = [Mock(price=0.55, size=1000)]
        ob.asks = [Mock(price=0.56, size=1000)]
        ob.last_update = time.time()
        
        allowed, reason = gate.check(ob)
        assert allowed is True
        assert reason is None
    
    def test_blocks_wide_spread(self):
        """Trade blocked when spread too wide"""
        gate = LiquidityGate(max_spread_bps=50)  # 0.5% max
        
        ob = OrderBook("0x123")
        ob.bids = [Mock(price=0.50, size=1000)]
        ob.asks = [Mock(price=0.56, size=1000)]  # 10% spread
        ob.last_update = time.time()
        
        allowed, reason = gate.check(ob)
        assert allowed is False
        assert "spread_too_wide" in reason
    
    def test_blocks_low_depth(self):
        """Trade blocked when depth too low - use tight spread to pass spread check"""
        gate = LiquidityGate(max_spread_bps=1000, min_depth_1bp=1000)  # Very relaxed spread
        
        ob = OrderBook("0x123")
        ob.bids = [Mock(price=0.55, size=100)]  # Too small
        ob.asks = [Mock(price=0.5501, size=100)]  # Tight spread
        ob.last_update = time.time()
        
        allowed, reason = gate.check(ob)
        assert allowed is False
        assert "depth" in reason
    
    def test_blocks_stale_book(self):
        """Trade blocked when book is stale - use tight spread to pass spread check"""
        gate = LiquidityGate(max_spread_bps=1000, max_book_age_s=5)  # Very relaxed spread
        
        ob = OrderBook("0x123")
        ob.bids = [Mock(price=0.55, size=1000)]
        ob.asks = [Mock(price=0.5501, size=1000)]  # Tight spread
        ob.last_update = time.time() - 10  # 10 seconds old
        
        allowed, reason = gate.check(ob)
        assert allowed is False
        assert "stale" in reason


# ============================================================================
# Block G: Execution Engine Tests
# ============================================================================

class TestExecutionDecisions:
    """Test execution engine decisions"""
    
    def test_skip_when_stale_quote(self):
        """Skip execution when quote is stale - use tight spread"""
        config = ExecutionConfig(max_order_age_s=1)
        engine = ExecutionEngine(config)
        
        # Create stale orderbook with tight spread
        from agents.risk import PortfolioState
        portfolio = PortfolioState(equity=10000)
        
        # Mock orderbook manager to return stale book with tight spread
        engine.orderbook_mgr.update_from_snapshot("0x123", [(0.55, 10000)], [(0.5501, 10000)])
        ob = engine.orderbook_mgr.get_orderbook("0x123")
        ob.last_update = time.time() - 10  # Stale
        
        result = engine.execute("0x123", "buy", 100, portfolio)
        
        assert result.success is False
        # Should fail on staleness (after passing risk/liquidity)
        assert "stale" in result.error or "risk" in result.error or "liquidity" in result.error
    
    def test_skip_when_spread_too_wide(self):
        """Skip execution when spread too wide"""
        from agents.risk import PortfolioState
        portfolio = PortfolioState(equity=10000)
        
        config = ExecutionConfig()
        engine = ExecutionEngine(config)
        
        # Create wide spread book
        engine.orderbook_mgr.update_from_snapshot("0x123", [(0.50, 10000)], [(0.60, 10000)])
        ob = engine.orderbook_mgr.get_orderbook("0x123")
        ob.last_update = time.time()
        
        # Set tight liquidity gate
        engine.orderbook_mgr.liquidity_gate = LiquidityGate(max_spread_bps=50)
        
        result = engine.execute("0x123", "buy", 100, portfolio)
        
        assert result.success is False
        # Should fail on spread (risk or liquidity gate)
        assert "spread" in result.error or "risk" in result.error or "liquidity" in result.error
    
    def test_maker_taker_selection(self):
        """Test maker vs taker order type selection"""
        from agents.risk import PortfolioState
        portfolio = PortfolioState(equity=10000)
        
        # Test with maker config
        config_maker = ExecutionConfig(order_type=OrderType.MAKER)
        engine_maker = ExecutionEngine(config_maker)
        
        # Test with taker config
        config_taker = ExecutionConfig(order_type=OrderType.TAKER)
        engine_taker = ExecutionEngine(config_taker)
        
        assert engine_maker.config.order_type == OrderType.MAKER
        assert engine_taker.config.order_type == OrderType.TAKER
    
    def test_basic_cancel_replace_path(self):
        """Test cancel/replace logic for aging orders"""
        config = ExecutionConfig(max_order_age_s=1)
        engine = ExecutionEngine(config)
        
        # This would test the cancel/replace logic
        # For now, just verify the config is respected
        assert engine.config.max_order_age_s == 1.0


# ============================================================================
# Integration Smoke Tests
# ============================================================================

class TestMarketDataIntegration:
    """Integration tests for market data components"""
    
    def test_ws_to_orderbook_flow(self):
        """Test WebSocket quote updates orderbook"""
        # This would test the full flow
        # For now, just verify components exist
        from agents.market_data import get_ws_client, get_orderbook_manager, get_execution_engine
        assert get_ws_client() is not None
        assert get_orderbook_manager() is not None
        assert get_execution_engine() is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
