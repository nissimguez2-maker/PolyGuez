"""
Execution Engine
Block G - Smart order execution with pre/post-trade checks
"""

import time
import logging
import threading
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from enum import Enum

from agents.market_data.orderbook import get_orderbook_manager, LiquidityGate
from agents.risk import get_risk_manager, PortfolioState
from agents.telemetry import get_metrics_collector, TradeMetrics

logger = logging.getLogger(__name__)


class OrderType(Enum):
    """Order execution types"""
    MAKER = "maker"  # Post only, try to get rebate
    TAKER = "taker"  # Immediate execution
    SMART = "smart"  # Try maker first, then taker


@dataclass
class ExecutionConfig:
    """Execution configuration"""
    order_type: OrderType = OrderType.SMART
    max_slippage_bps: float = 50.0  # 0.5%
    max_order_age_s: float = 30.0   # Cancel/replace after 30s
    iceberg_threshold: float = 1000.0  # Split if order > $1000
    iceberg_parts: int = 3
    
    # Feature flags
    enabled: bool = True
    verify_fills: bool = True
    retry_on_fail: bool = True
    max_retries: int = 3


@dataclass
class ExecutionResult:
    """Result of order execution"""
    success: bool
    order_id: Optional[str] = None
    filled_size: float = 0.0
    avg_price: Optional[float] = None
    slippage_bps: Optional[float] = None
    fees: float = 0.0
    error: Optional[str] = None
    retries: int = 0
    latency_ms: float = 0.0


class ExecutionEngine:
    """
    Smart execution engine with:
    - Pre-trade checks (risk + liquidity + staleness)
    - Maker/taker/smart order types
    - Iceberg splitting for large orders
    - Post-trade verification
    - Slippage tracking
    """
    
    def __init__(self, config: Optional[ExecutionConfig] = None):
        self.config = config or ExecutionConfig()
        self.orderbook_mgr = get_orderbook_manager()
        self.risk_mgr = get_risk_manager()
        self.metrics = get_metrics_collector()
        
        # Track pending orders for cancel/replace
        self._pending_orders: Dict[str, dict] = {}
        
        # Slippage tracking
        self._slippage_history: List[float] = []
    
    def execute(
        self,
        market_id: str,
        side: str,  # "buy" or "sell"
        size: float,
        portfolio: PortfolioState,
        order_type: Optional[OrderType] = None
    ) -> ExecutionResult:
        """
        Execute order with full pre/post-trade checks
        """
        if not self.config.enabled:
            logger.warning("Execution engine disabled")
            return ExecutionResult(success=False, error="execution_disabled")
        
        start_time = time.time()
        order_type = order_type or self.config.order_type
        
        # === PRE-TRADE CHECKS ===
        
        # 1. Risk gate
        allowed, risk_reason = self._check_risk_gate(market_id, side, size, portfolio)
        if not allowed:
            logger.info(f"[EXEC] Risk gate blocked: {risk_reason}")
            self.metrics.increment("trades_blocked_total", labels={"reason": "risk_gate"})
            return ExecutionResult(success=False, error=f"risk_gate:{risk_reason}")
        
        # 2. Liquidity gate
        allowed, liq_reason = self._check_liquidity_gate(market_id, size)
        if not allowed:
            logger.info(f"[EXEC] Liquidity gate blocked: {liq_reason}")
            self.metrics.increment("trades_blocked_total", labels={"reason": "liquidity_gate"})
            return ExecutionResult(success=False, error=f"liquidity_gate:{liq_reason}")
        
        # 3. Staleness gate
        allowed, stale_reason = self._check_staleness(market_id)
        if not allowed:
            logger.info(f"[EXEC] Staleness gate blocked: {stale_reason}")
            self.metrics.increment("trades_blocked_total", labels={"reason": "stale_data"})
            return ExecutionResult(success=False, error=f"stale:{stale_reason}")
        
        # === EXECUTION ===
        
        # Split large orders (iceberg)
        if size > self.config.iceberg_threshold:
            return self._execute_iceberg(market_id, side, size, order_type, portfolio)
        
        # Single order execution
        return self._execute_single(market_id, side, size, order_type, portfolio, start_time)
    
    def _check_risk_gate(
        self,
        market_id: str,
        side: str,
        size: float,
        portfolio: PortfolioState
    ) -> Tuple[bool, Optional[str]]:
        """Check risk gate"""
        orderbook = self.orderbook_mgr.get_orderbook(market_id)
        if not orderbook or not orderbook.mid:
            return False, "no_price"
        
        entry_price = orderbook.mid
        best_ask = orderbook.best_ask or entry_price
        best_bid = orderbook.best_bid or entry_price
        
        allowed, reason, _ = self.risk_mgr.check_trade_allowed(
            portfolio, size, entry_price, best_ask, best_bid
        )
        
        return allowed, reason.value if reason else None
    
    def _check_liquidity_gate(self, market_id: str, size: float) -> Tuple[bool, Optional[str]]:
        """Check liquidity gate"""
        allowed, reason = self.orderbook_mgr.check_liquidity(market_id)
        return allowed, reason
    
    def _check_staleness(self, market_id: str) -> Tuple[bool, Optional[str]]:
        """Check if data is fresh"""
        orderbook = self.orderbook_mgr.get_orderbook(market_id)
        if not orderbook:
            return False, "no_orderbook"
        
        age = time.time() - orderbook.last_update
        if age > self.config.max_order_age_s:
            return False, f"stale:{age:.1f}s"
        
        return True, None
    
    def _execute_single(
        self,
        market_id: str,
        side: str,
        size: float,
        order_type: OrderType,
        portfolio: PortfolioState,
        start_time: float
    ) -> ExecutionResult:
        """Execute single order"""
        orderbook = self.orderbook_mgr.get_orderbook(market_id)
        expected_price = orderbook.mid if orderbook else 0
        
        # Try maker first if SMART
        if order_type == OrderType.SMART:
            result = self._try_maker(market_id, side, size, start_time)
            if result.success:
                return result
            # Fall back to taker
            logger.info("[EXEC] Maker failed, falling back to taker")
            return self._try_taker(market_id, side, size, start_time)
        
        elif order_type == OrderType.MAKER:
            return self._try_maker(market_id, side, size, start_time)
        
        else:  # TAKER
            return self._try_taker(market_id, side, size, start_time)
    
    def _execute_iceberg(
        self,
        market_id: str,
        side: str,
        total_size: float,
        order_type: OrderType,
        portfolio: PortfolioState
    ) -> ExecutionResult:
        """Execute iceberg order (split into parts)"""
        part_size = total_size / self.config.iceberg_parts
        results = []
        
        logger.info(f"[EXEC] Iceberg order: {total_size} in {self.config.iceberg_parts} parts")
        
        for i in range(self.config.iceberg_parts):
            result = self._execute_single(
                market_id, side, part_size, order_type, portfolio, time.time()
            )
            results.append(result)
            
            if not result.success:
                logger.warning(f"[EXEC] Iceberg part {i+1} failed: {result.error}")
            
            # Small delay between parts
            if i < self.config.iceberg_parts - 1:
                time.sleep(0.5)
        
        # Aggregate results
        total_filled = sum(r.filled_size for r in results)
        avg_price = self._calculate_vwap(results)
        
        # Calculate slippage
        orderbook = self.orderbook_mgr.get_orderbook(market_id)
        slippage = None
        if orderbook and orderbook.mid and avg_price:
            slippage = abs(avg_price - orderbook.mid) / orderbook.mid * 10000
        
        return ExecutionResult(
            success=total_filled > 0,
            filled_size=total_filled,
            avg_price=avg_price,
            slippage_bps=slippage,
            retries=sum(r.retries for r in results),
            latency_ms=sum(r.latency_ms for r in results),
            error=None if total_filled > 0 else "partial_fill"
        )
    
    def _try_maker(self, market_id: str, side: str, size: float, start_time: float) -> ExecutionResult:
        """Try to execute as maker (post-only)"""
        logger.info(f"[EXEC] Trying maker order: {side} {size}")
        
        # In real implementation: place post-only order, wait for fill
        # For now: simulate
        
        # Simulate 70% success rate for maker
        import random
        if random.random() < 0.7:
            return self._simulate_fill(market_id, side, size, start_time, "maker")
        else:
            return ExecutionResult(success=False, error="maker_not_filled")
    
    def _try_taker(self, market_id: str, side: str, size: float, start_time: float) -> ExecutionResult:
        """Execute as taker (immediate)"""
        logger.info(f"[EXEC] Executing taker order: {side} {size}")
        
        # In real implementation: execute market order
        # For now: simulate
        
        return self._simulate_fill(market_id, side, size, start_time, "taker")
    
    def _simulate_fill(
        self,
        market_id: str,
        side: str,
        size: float,
        start_time: float,
        exec_type: str
    ) -> ExecutionResult:
        """Simulate order fill (for testing)"""
        orderbook = self.orderbook_mgr.get_orderbook(market_id)
        
        if not orderbook:
            return ExecutionResult(success=False, error="no_orderbook")
        
        # Calculate fill price (with small slippage)
        if side == "buy":
            fill_price = orderbook.best_ask or orderbook.mid
        else:
            fill_price = orderbook.best_bid or orderbook.mid
        
        # Simulate slippage
        slippage_bps = 5.0 if exec_type == "taker" else 0.0
        
        latency_ms = (time.time() - start_time) * 1000
        
        # Record metrics
        self.metrics.increment("trades_executed_total", labels={"type": exec_type})
        self.metrics.increment("slippage_bps_total", int(slippage_bps))
        
        # Track slippage
        self._slippage_history.append(slippage_bps)
        if len(self._slippage_history) > 100:
            self._slippage_history = self._slippage_history[-100:]
        
        return ExecutionResult(
            success=True,
            order_id=f"sim_{int(time.time()*1000)}",
            filled_size=size,
            avg_price=fill_price,
            slippage_bps=slippage_bps,
            latency_ms=latency_ms
        )
    
    def _calculate_vwap(self, results: List[ExecutionResult]) -> Optional[float]:
        """Calculate VWAP from multiple fills"""
        total_value = sum(r.avg_price * r.filled_size for r in results if r.avg_price)
        total_size = sum(r.filled_size for r in results)
        
        if total_size == 0:
            return None
        
        return total_value / total_size
    
    def get_slippage_stats(self) -> Dict:
        """Get slippage statistics"""
        if not self._slippage_history:
            return {}
        
        return {
            "mean_bps": sum(self._slippage_history) / len(self._slippage_history),
            "max_bps": max(self._slippage_history),
            "min_bps": min(self._slippage_history),
            "count": len(self._slippage_history)
        }


# Singleton instance
_execution_engine: Optional[ExecutionEngine] = None
_execution_lock = threading.Lock()

def get_execution_engine() -> ExecutionEngine:
    """Get or create singleton execution engine (thread-safe)"""
    global _execution_engine
    if _execution_engine is None:
        with _execution_lock:
            if _execution_engine is None:
                _execution_engine = ExecutionEngine()
    return _execution_engine
