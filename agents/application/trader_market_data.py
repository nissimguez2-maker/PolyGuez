"""
Enhanced Trader with Market Data Integration (E/F/G)
Feature-flagged, backward compatible
"""

import os
import shutil
import time
from typing import Optional
from datetime import datetime

from agents.application.executor_enhanced import EnhancedExecutor
from agents.polymarket.gamma import GammaMarketClient as Gamma
from agents.polymarket.polymarket import Polymarket
from agents.risk import get_risk_manager, PortfolioState, Position
from agents.telemetry import get_metrics_collector, CycleMetrics

# New market data imports
from agents.market_data import (
    get_ws_client,
    get_orderbook_manager,
    get_execution_engine,
    start_market_data_health_server
)


class MarketDataEnhancedTrader:
    """
    Trader with optional market data enhancements (E/F/G)
    
    Feature flags (all default OFF for backward compatibility):
    - WS_ENABLED: Enable WebSocket market data
    - L2_ENABLED: Enable Level-2 orderbook
    - EXECUTION_ENABLED: Enable smart execution engine
    """
    
    def __init__(self):
        self.polymarket = Polymarket()
        self.gamma = Gamma()
        self.executor = EnhancedExecutor()
        self.risk = get_risk_manager()
        self.metrics = get_metrics_collector()
        
        # Feature flags
        self.ws_enabled = os.getenv("WS_ENABLED", "0") == "1"
        self.l2_enabled = os.getenv("L2_ENABLED", "0") == "1"
        self.execution_enabled = os.getenv("EXECUTION_ENABLED", "0") == "1"
        
        # Market data components (lazy init)
        self._ws_client = None
        self._orderbook_mgr = None
        self._execution_engine = None
        
        # Daily tracking
        self._daily_starting_equity: Optional[float] = None
        self._daily_pnl: float = 0.0
        self._last_date: Optional[str] = None
        
        # Initialize market data if enabled
        if self.ws_enabled:
            self._init_market_data()
    
    def _init_market_data(self):
        """Initialize market data components"""
        print(f"[MARKET_DATA] Initializing (WS={self.ws_enabled}, L2={self.l2_enabled}, EXEC={self.execution_enabled})")
        
        # Start WebSocket
        if self.ws_enabled:
            self._ws_client = get_ws_client()
            self._ws_client.start()
            
            # Start health server
            health_port = int(os.getenv("MARKET_DATA_HEALTH_PORT", "9091"))
            start_market_data_health_server(port=health_port)
            print(f"[MARKET_DATA] Health server on port {health_port}")
        
        # Initialize orderbook manager
        if self.l2_enabled:
            self._orderbook_mgr = get_orderbook_manager()
        
        # Initialize execution engine
        if self.execution_enabled:
            self._execution_engine = get_execution_engine()
    
    def pre_trade_logic(self) -> None:
        self.clear_local_dbs()
        self._check_new_trading_day()
    
    def clear_local_dbs(self) -> None:
        try:
            shutil.rmtree("local_db_events")
        except Exception:
            pass
        try:
            shutil.rmtree("local_db_markets")
        except Exception:
            pass
    
    def _check_new_trading_day(self) -> None:
        current_date = datetime.utcnow().strftime("%Y-%m-%d")
        
        if self._last_date != current_date:
            self._daily_starting_equity = self._get_current_equity()
            self._daily_pnl = 0.0
            self._last_date = current_date
            self.risk.reset_daily_stats(self._daily_starting_equity)
            print(f"[RISK] New trading day. Starting equity: ${self._daily_starting_equity:.2f}")
    
    def _get_current_equity(self) -> float:
        try:
            return self.polymarket.get_usdc_balance()
        except Exception as e:
            print(f"[RISK] Warning: Could not fetch equity: {e}")
            return 0.0
    
    def _get_portfolio_state(self) -> PortfolioState:
        equity = self._get_current_equity()
        positions = self._fetch_open_positions()
        
        return PortfolioState(
            equity=equity,
            positions=positions,
            daily_pnl=self._daily_pnl,
            daily_starting_equity=self._daily_starting_equity or equity
        )
    
    def _fetch_open_positions(self) -> list:
        positions = []
        try:
            raw_positions = self.polymarket.get_open_positions()
            for pos in raw_positions:
                positions.append(Position(
                    market_id=pos.get("market_id", ""),
                    token_id=pos.get("token_id", ""),
                    side=pos.get("side", "yes"),
                    entry_price=pos.get("entry_price", 0.0),
                    size=pos.get("size", 0.0)
                ))
        except Exception as e:
            print(f"[RISK] Warning: Could not fetch positions: {e}")
        return positions
    
    def _subscribe_to_market(self, market_id: str):
        """Subscribe to market via WebSocket if enabled"""
        if self.ws_enabled and self._ws_client:
            self._ws_client.subscribe(market_id)
            print(f"[WS] Subscribed to {market_id}")
    
    def _get_market_data(self, market_id: str):
        """Get market data (WS or HTTP fallback)"""
        if self.l2_enabled and self._orderbook_mgr:
            # Try orderbook first
            orderbook = self._orderbook_mgr.get_orderbook(market_id)
            if orderbook:
                return {
                    "best_bid": orderbook.best_bid,
                    "best_ask": orderbook.best_ask,
                    "mid": orderbook.mid,
                    "spread_bps": orderbook.spread_bps,
                    "source": "orderbook"
                }
        
        if self.ws_enabled and self._ws_client:
            # Try WebSocket quote
            quote = self._ws_client.get_latest_quote(market_id)
            if quote:
                return {
                    "best_bid": quote.best_bid,
                    "best_ask": quote.best_ask,
                    "mid": quote.mid,
                    "spread_bps": (quote.spread / quote.mid * 10000) if quote.mid else None,
                    "source": "websocket"
                }
        
        # Fallback to HTTP/Gamma
        return None
    
    def one_best_trade(self) -> None:
        """Main trading cycle with optional market data"""
        cycle_start = time.time()
        cycle = CycleMetrics()
        
        try:
            self.pre_trade_logic()
            
            portfolio = self._get_portfolio_state()
            print(f"[RISK] Equity: ${portfolio.equity:.2f}, Exposure: {portfolio.exposure_pct:.1f}%, Positions: {portfolio.concurrent_positions}")
            
            # Stage 1-4: Same as before (event/market filtering)
            stage_start = time.time()
            events = self.polymarket.get_all_tradeable_events()
            cycle.time_fetch_events_ms = (time.time() - stage_start) * 1000
            cycle.events_found = len(events)
            print(f"1. FOUND {len(events)} EVENTS")
            
            stage_start = time.time()
            filtered_events = self.executor.filter_events_with_rag(events)
            cycle.time_filter_events_ms = (time.time() - stage_start) * 1000
            cycle.events_filtered = len(filtered_events)
            print(f"2. FILTERED {len(filtered_events)} EVENTS")
            
            stage_start = time.time()
            markets = self.executor.map_filtered_events_to_markets(filtered_events)
            cycle.time_fetch_markets_ms = (time.time() - stage_start) * 1000
            cycle.markets_found = len(markets)
            print(f"3. FOUND {len(markets)} MARKETS")
            
            stage_start = time.time()
            filtered_markets = self.executor.filter_markets(markets)
            cycle.time_filter_markets_ms = (time.time() - stage_start) * 1000
            cycle.markets_filtered = len(filtered_markets)
            print(f"4. FILTERED {len(filtered_markets)} MARKETS")
            
            if not filtered_markets:
                print("[RISK] No markets passed filtering. Skipping.")
                cycle.trade_blocked = True
                cycle.block_reason = "no_markets_after_filter"
                return
            
            market = filtered_markets[0]
            market_id = str(market[0].dict().get("metadata", {}).get("market_id", "")) if hasattr(market[0], 'dict') else str(market)
            
            # Subscribe to market data if WS enabled
            self._subscribe_to_market(market_id)
            
            # Get market data
            market_data = self._get_market_data(market_id)
            if market_data:
                print(f"[MARKET_DATA] Using {market_data['source']}: spread={market_data['spread_bps']:.1f}bps")
            
            # Stage 5: Analyze
            stage_start = time.time()
            best_trade = self.executor.source_best_trade(market)
            cycle.time_analyze_ms = (time.time() - stage_start) * 1000
            print(f"5. CALCULATED TRADE {best_trade}")
            
            # Stage 6: Execute
            stage_start = time.time()
            
            raw_amount = self._parse_trade_amount(best_trade)
            confidence = 0.7
            edge = 50
            
            sized_amount = self.risk.calculate_position_size(portfolio, confidence, edge)
            amount = min(raw_amount, sized_amount)
            
            # Get prices for risk check
            if market_data:
                best_ask = market_data.get("best_ask", 0.5)
                best_bid = market_data.get("best_bid", 0.5)
                entry_price = market_data.get("mid", 0.5)
            else:
                best_ask = best_bid = entry_price = 0.5
            
            # RISK GATE
            allowed, msg = self.executor.check_risk_before_trade(
                portfolio, amount, entry_price, best_ask, best_bid
            )
            
            if not allowed:
                print(f"[RISK] Trade BLOCKED: {msg}")
                cycle.trade_blocked = True
                cycle.block_reason = msg
                self.executor.record_trade_attempt(market_id, amount, "blocked", block_reason=msg)
                return
            
            # EXECUTION
            if self.execution_enabled and self._execution_engine:
                # Use smart execution engine
                print(f"[EXECUTION] Using ExecutionEngine: {side} ${amount:.2f}")
                
                result = self._execution_engine.execute(
                    market_id=market_id,
                    side="buy",  # Determine from trade analysis
                    size=amount,
                    portfolio=portfolio
                )
                
                if result.success:
                    print(f"[EXECUTION] Success: filled=${result.filled_size:.2f} @ ${result.avg_price:.4f}")
                    print(f"[EXECUTION] Slippage: {result.slippage_bps:.1f}bps, Latency: {result.latency_ms:.0f}ms")
                    cycle.trade_executed = True
                else:
                    print(f"[EXECUTION] Failed: {result.error}")
                    cycle.trade_blocked = True
                    cycle.block_reason = result.error
            else:
                # Legacy execution (commented for TOS)
                print(f"[RISK] Trade APPROVED: ${amount:.2f}")
                print(f"6. TRADE EXECUTED (simulated): ${amount:.2f}")
                self.executor.record_trade_attempt(market_id, amount, "success")
                cycle.trade_executed = True
            
            cycle.time_execute_ms = (time.time() - stage_start) * 1000
            
        except Exception as e:
            print(f"Error {e}")
            self.executor.record_trade_attempt("", 0, "failed", error=str(e))
            raise
        
        finally:
            cycle.total_latency_ms = (time.time() - cycle_start) * 1000
            self.metrics.record_cycle(cycle)
    
    def _parse_trade_amount(self, best_trade: str) -> float:
        """Parse amount from trade string"""
        import re
        try:
            size = re.findall(r"\d+\.?\d*", best_trade.split(",")[1])[0]
            usdc_balance = self.polymarket.get_usdc_balance()
            return float(size) * usdc_balance
        except Exception:
            return 100.0
    
    def get_metrics(self) -> dict:
        """Get current metrics"""
        return self.executor.get_metrics_summary()


# Backwards compatibility - default Trader (market data OFF)
class Trader(MarketDataEnhancedTrader):
    """Default trader with market data features disabled"""
    pass


if __name__ == "__main__":
    trader = MarketDataEnhancedTrader()
    trader.one_best_trade()
