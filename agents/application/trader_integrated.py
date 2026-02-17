"""
Fully Integrated Trader with A-D
Uses EnhancedExecutor and adds full telemetry
"""

import os
import shutil
import time
from typing import Optional, Tuple
from datetime import datetime

from agents.application.executor_enhanced import EnhancedExecutor
from agents.polymarket.gamma import GammaMarketClient as Gamma
from agents.polymarket.polymarket import Polymarket
from agents.risk import get_risk_manager, PortfolioState, Position
from agents.telemetry import get_metrics_collector, CycleMetrics, start_metrics_server


class IntegratedTrader:
    """
    Fully integrated trader with:
    - Risk management (A)
    - Circuit breaker + retry (B)
    - Telemetry (C)
    - Model fallback (D)
    """
    
    def __init__(self):
        self.polymarket = Polymarket()
        self.gamma = Gamma()
        self.executor = EnhancedExecutor()
        self.risk = get_risk_manager()
        self.metrics = get_metrics_collector()
        
        # Daily tracking
        self._daily_starting_equity: Optional[float] = None
        self._daily_pnl: float = 0.0
        self._last_date: Optional[str] = None
        
        # Start metrics server if enabled
        if os.getenv("TELEMETRY_ENABLED", "1") == "1":
            metrics_port = int(os.getenv("METRICS_PORT", "9090"))
            start_metrics_server(port=metrics_port)
            print(f"[TELEMETRY] Metrics server started on port {metrics_port}")
    
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
    
    def _get_market_orderbook(self, market) -> Tuple[float, float]:
        try:
            import ast
            market_data = market[0].dict() if hasattr(market[0], 'dict') else {}
            metadata = market_data.get("metadata", {})
            outcome_prices = ast.literal_eval(metadata.get("outcome_prices", "[0, 0]"))
            
            if len(outcome_prices) >= 2:
                return max(outcome_prices), min(outcome_prices)
        except Exception as e:
            print(f"[RISK] Warning: Could not parse orderbook: {e}")
        
        return 0.0, 0.0
    
    def one_best_trade(self) -> None:
        """Main trading cycle with full integration"""
        cycle_start = time.time()
        cycle = CycleMetrics()
        
        try:
            self.pre_trade_logic()
            
            # Get portfolio state
            portfolio = self._get_portfolio_state()
            print(f"[RISK] Equity: ${portfolio.equity:.2f}, Exposure: {portfolio.exposure_pct:.1f}%, Positions: {portfolio.concurrent_positions}")
            
            # Stage 1: Fetch events
            stage_start = time.time()
            events = self.polymarket.get_all_tradeable_events()
            cycle.time_fetch_events_ms = (time.time() - stage_start) * 1000
            cycle.events_found = len(events)
            print(f"1. FOUND {len(events)} EVENTS")
            
            # Stage 2: Filter events
            stage_start = time.time()
            filtered_events = self.executor.filter_events_with_rag(events)
            cycle.time_filter_events_ms = (time.time() - stage_start) * 1000
            cycle.events_filtered = len(filtered_events)
            print(f"2. FILTERED {len(filtered_events)} EVENTS")
            
            # Stage 3: Map to markets
            stage_start = time.time()
            markets = self.executor.map_filtered_events_to_markets(filtered_events)
            cycle.time_fetch_markets_ms = (time.time() - stage_start) * 1000
            cycle.markets_found = len(markets)
            print(f"3. FOUND {len(markets)} MARKETS")
            
            # Stage 4: Filter markets
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
            best_ask, best_bid = self._get_market_orderbook(market)
            
            # Stage 5: Analyze
            stage_start = time.time()
            best_trade = self.executor.source_best_trade(market)
            cycle.time_analyze_ms = (time.time() - stage_start) * 1000
            print(f"5. CALCULATED TRADE {best_trade}")
            
            # Stage 6: Risk check + Execution
            stage_start = time.time()
            
            raw_amount = self._parse_trade_amount(best_trade)
            confidence = 0.7  # Would come from LLM
            edge = 50  # bps
            
            sized_amount = self.risk.calculate_position_size(portfolio, confidence, edge)
            amount = min(raw_amount, sized_amount)
            
            entry_price = (best_ask + best_bid) / 2 if best_ask > 0 and best_bid > 0 else 0.5
            
            # RISK GATE
            allowed, msg = self.executor.check_risk_before_trade(
                portfolio, amount, entry_price, best_ask, best_bid
            )
            
            if not allowed:
                print(f"[RISK] Trade BLOCKED: {msg}")
                cycle.trade_blocked = True
                cycle.block_reason = msg
                self.executor.record_trade_attempt(
                    market_id=str(market),
                    amount=amount,
                    status="blocked",
                    block_reason=msg
                )
                return
            
            print(f"[RISK] Trade APPROVED: ${amount:.2f}")
            
            # EXECUTE (commented for TOS)
            # trade = self.polymarket.execute_market_order(market, amount)
            print(f"6. TRADE EXECUTED (simulated): ${amount:.2f}")
            
            self.executor.record_trade_attempt(
                market_id=str(market),
                amount=amount,
                status="success"
            )
            
            cycle.trade_executed = True
            cycle.time_execute_ms = (time.time() - stage_start) * 1000
            
        except Exception as e:
            print(f"Error {e}")
            self.executor.record_trade_attempt(
                market_id="",
                amount=0,
                status="failed",
                error=str(e)
            )
            raise
        
        finally:
            # Record cycle metrics
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
            return 100.0  # Default
    
    def maintain_positions(self):
        """Check existing positions for exit signals"""
        try:
            portfolio = self._get_portfolio_state()
            
            for position in portfolio.positions:
                market_data = self.gamma.get_market(position.market_id)
                
                import ast
                outcome_prices = ast.literal_eval(market_data.get("outcomePrices", "[0, 0]"))
                current_mid = sum(outcome_prices) / len(outcome_prices) if outcome_prices else 0.5
                best_ask = max(outcome_prices) if outcome_prices else 0
                best_bid = min(outcome_prices) if outcome_prices else 0
                
                should_exit, reason = self.risk.check_exit_needed(
                    position, current_mid, best_ask, best_bid
                )
                
                if should_exit:
                    print(f"[RISK] EXIT SIGNAL for {position.market_id}: {reason}")
                    # self.polymarket.exit_position(position)
        
        except Exception as e:
            print(f"[RISK] Error in maintain_positions: {e}")
    
    def get_metrics(self) -> dict:
        """Get current metrics"""
        return self.executor.get_metrics_summary()


# Backwards compatibility
class Trader(IntegratedTrader):
    pass


if __name__ == "__main__":
    trader = IntegratedTrader()
    trader.one_best_trade()
