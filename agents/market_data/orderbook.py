"""
CLOB Level-2 Orderbook
Block F - Orderbook with liquidity analysis
"""

import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class PriceLevel:
    """Single price level in orderbook"""
    price: float
    size: float
    
    def __repr__(self):
        return f"{self.price:.4f}@{self.size:.2f}"


@dataclass
class OrderBook:
    """Level-2 orderbook for a market"""
    market_id: str
    bids: List[PriceLevel] = field(default_factory=list)  # Descending
    asks: List[PriceLevel] = field(default_factory=list)  # Ascending
    timestamp: float = field(default_factory=time.time)
    last_update: float = field(default_factory=time.time)
    
    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None
    
    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None
    
    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None
    
    @property
    def spread_bps(self) -> Optional[float]:
        """Spread in basis points"""
        if self.spread and self.mid:
            return (self.spread / self.mid) * 10000
        return None
    
    @property
    def mid(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None
    
    @property
    def microprice(self) -> Optional[float]:
        """Volume-weighted mid price"""
        if not self.bids or not self.asks:
            return None
        
        best_bid = self.bids[0]
        best_ask = self.asks[0]
        
        total_size = best_bid.size + best_ask.size
        if total_size == 0:
            return self.mid
        
        return (best_bid.price * best_ask.size + best_ask.price * best_bid.size) / total_size
    
    def depth_at_price(self, price: float, side: str) -> float:
        """Get depth at specific price level"""
        levels = self.bids if side == "bid" else self.asks
        for level in levels:
            if abs(level.price - price) < 1e-9:
                return level.size
        return 0.0
    
    def depth_within_bps(self, bps: float, side: str) -> float:
        """Get total depth within X basis points of best price"""
        if not self.mid:
            return 0.0
        
        levels = self.bids if side == "bid" else self.asks
        if not levels:
            return 0.0
        
        best = levels[0].price
        threshold = best * (bps / 10000)
        
        total = 0.0
        for level in levels:
            if side == "bid":
                if best - level.price <= threshold:
                    total += level.size
                else:
                    break
            else:
                if level.price - best <= threshold:
                    total += level.size
                else:
                    break
        
        return total
    
    def imbalance(self, depth_bps: float = 100) -> Optional[float]:
        """
        Orderbook imbalance (-1 to 1)
        Negative = more sell pressure, Positive = more buy pressure
        """
        bid_depth = self.depth_within_bps(depth_bps, "bid")
        ask_depth = self.depth_within_bps(depth_bps, "ask")
        
        total = bid_depth + ask_depth
        if total == 0:
            return None
        
        return (bid_depth - ask_depth) / total
    
    def volatility_proxy(self, levels: int = 5) -> Optional[float]:
        """
        Estimate volatility from orderbook shape
        Higher = more volatile (wider book)
        """
        if len(self.bids) < levels or len(self.asks) < levels:
            return None
        
        bid_range = self.bids[0].price - self.bids[levels-1].price
        ask_range = self.asks[levels-1].price - self.asks[0].price
        
        if self.mid and self.mid > 0:
            return ((bid_range + ask_range) / 2) / self.mid
        return None


@dataclass
class LiquidityGate:
    """Liquidity check configuration"""
    max_spread_bps: float = 100.0  # 1%
    min_depth_1bp: float = 100.0   # $100 at 1bp
    min_depth_5bp: float = 500.0   # $500 at 5bp
    max_book_age_s: float = 5.0    # Book must be fresh
    
    def check(self, orderbook: OrderBook) -> Tuple[bool, Optional[str]]:
        """
        Check if market has sufficient liquidity
        
        Returns: (allowed, reason)
        """
        # Check spread
        if orderbook.spread_bps is None:
            return False, "no_spread"
        
        if orderbook.spread_bps > self.max_spread_bps:
            return False, f"spread_too_wide:{orderbook.spread_bps:.0f}bps"
        
        # Check depth at 1bp
        depth_1bp_bid = orderbook.depth_within_bps(1, "bid")
        depth_1bp_ask = orderbook.depth_within_bps(1, "ask")
        
        if depth_1bp_bid < self.min_depth_1bp or depth_1bp_ask < self.min_depth_1bp:
            return False, f"depth_1bp_too_low:{min(depth_1bp_bid, depth_1bp_ask):.0f}"
        
        # Check depth at 5bp
        depth_5bp_bid = orderbook.depth_within_bps(5, "bid")
        depth_5bp_ask = orderbook.depth_within_bps(5, "ask")
        
        if depth_5bp_bid < self.min_depth_5bp or depth_5bp_ask < self.min_depth_5bp:
            return False, f"depth_5bp_too_low:{min(depth_5bp_bid, depth_5bp_ask):.0f}"
        
        # Check freshness
        age = time.time() - orderbook.last_update
        if age > self.max_book_age_s:
            return False, f"book_stale:{age:.1f}s"
        
        return True, None


class OrderBookManager:
    """Manages orderbooks for multiple markets"""
    
    def __init__(self, liquidity_gate: Optional[LiquidityGate] = None):
        self.orderbooks: Dict[str, OrderBook] = {}
        self.liquidity_gate = liquidity_gate or LiquidityGate()
        self._trade_history: Dict[str, List[Tuple[float, float]]] = defaultdict(list)  # price, size
    
    def update_from_snapshot(self, market_id: str, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]):
        """
        Update orderbook from snapshot
        
        Args:
            bids: List of (price, size) tuples, descending
            asks: List of (price, size) tuples, ascending
        """
        orderbook = OrderBook(market_id=market_id)
        
        orderbook.bids = [PriceLevel(p, s) for p, s in sorted(bids, key=lambda x: -x[0])]
        orderbook.asks = [PriceLevel(p, s) for p, s in sorted(asks, key=lambda x: x[0])]
        orderbook.last_update = time.time()
        
        self.orderbooks[market_id] = orderbook
    
    def update_from_delta(self, market_id: str, side: str, price: float, size: float):
        """Update single price level (delta)"""
        if market_id not in self.orderbooks:
            return
        
        orderbook = self.orderbooks[market_id]
        levels = orderbook.bids if side == "bid" else orderbook.asks
        
        # Find and update level
        found = False
        for i, level in enumerate(levels):
            if abs(level.price - price) < 1e-9:
                if size > 0:
                    level.size = size
                else:
                    levels.pop(i)
                found = True
                break
        
        # Add new level if not found and size > 0
        if not found and size > 0:
            new_level = PriceLevel(price, size)
            if side == "bid":
                # Insert in sorted order (descending)
                for i, level in enumerate(levels):
                    if price > level.price:
                        levels.insert(i, new_level)
                        break
                else:
                    levels.append(new_level)
            else:
                # Insert in sorted order (ascending)
                for i, level in enumerate(levels):
                    if price < level.price:
                        levels.insert(i, new_level)
                        break
                else:
                    levels.append(new_level)
        
        orderbook.last_update = time.time()
    
    def record_trade(self, market_id: str, price: float, size: float):
        """Record trade for analytics"""
        self._trade_history[market_id].append((price, size))
        
        # Keep last 100 trades
        if len(self._trade_history[market_id]) > 100:
            self._trade_history[market_id] = self._trade_history[market_id][-100:]
    
    def get_orderbook(self, market_id: str) -> Optional[OrderBook]:
        """Get orderbook for market"""
        return self.orderbooks.get(market_id)
    
    def check_liquidity(self, market_id: str) -> Tuple[bool, Optional[str]]:
        """Check if market passes liquidity gate"""
        orderbook = self.get_orderbook(market_id)
        if not orderbook:
            return False, "no_orderbook"
        
        return self.liquidity_gate.check(orderbook)
    
    def get_trade_volume(self, market_id: str, lookback: int = 20) -> float:
        """Get recent trade volume"""
        trades = self._trade_history.get(market_id, [])
        if not trades:
            return 0.0
        
        recent = trades[-lookback:]
        return sum(size for _, size in recent)
    
    def get_vwap(self, market_id: str, lookback: int = 20) -> Optional[float]:
        """Calculate volume-weighted average price"""
        trades = self._trade_history.get(market_id, [])
        if not trades:
            return None
        
        recent = trades[-lookback:]
        total_value = sum(p * s for p, s in recent)
        total_size = sum(s for _, s in recent)
        
        if total_size == 0:
            return None
        
        return total_value / total_size


# Singleton instance
_orderbook_manager: Optional[OrderBookManager] = None

def get_orderbook_manager() -> OrderBookManager:
    """Get or create singleton orderbook manager"""
    global _orderbook_manager
    if _orderbook_manager is None:
        _orderbook_manager = OrderBookManager()
    return _orderbook_manager
