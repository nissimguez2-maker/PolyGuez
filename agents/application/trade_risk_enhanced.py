"""
Enhanced Trader with Risk Management Integration
Block A - Step 2: Integration
"""

import os
import shutil
from typing import Optional, Tuple
from datetime import datetime

from agents.application.executor import Executor as Agent
from agents.polymarket.gamma import GammaMarketClient as Gamma
from agents.polymarket.polymarket import Polymarket
from agents.risk import RiskManager, PortfolioState, Position, RiskBlockReason


class Trader:
    def __init__(self):
        self.polymarket = Polymarket()
        self.gamma = Gamma()
        self.agent = Agent()
        self.risk = RiskManager()
        
        # Track daily stats
        self._daily_starting_equity: Optional[float] = None
        self._daily_pnl: float = 0.0
        self._last_date: Optional[str] = None

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
        """Reset daily stats if new trading day"""
        current_date = datetime.utcnow().strftime("%Y-%m-%d")
        
        if self._last_date != current_date:
            # New day - reset stats
            self._daily_starting_equity = self._get_current_equity()
            self._daily_pnl = 0.0
            self._last_date = current_date
            self.risk.reset_daily_stats(self._daily_starting_equity)
            print(f"[RISK] New trading day. Starting equity: ${self._daily_starting_equity:.2f}")

    def _get_current_equity(self) -> float:
        """Get current USDC balance"""
        try:
            return self.polymarket.get_usdc_balance()
        except Exception as e:
            print(f"[RISK] Warning: Could not fetch equity: {e}")
            return 0.0

    def _get_portfolio_state(self) -> PortfolioState:
        """Build current portfolio state for risk checks"""
        equity = self._get_current_equity()
        
        # Get open positions from Polymarket
        positions = self._fetch_open_positions()
        
        return PortfolioState(
            equity=equity,
            positions=positions,
            daily_pnl=self._daily_pnl,
            daily_starting_equity=self._daily_starting_equity or equity
        )

    def _fetch_open_positions(self) -> list:
        """Fetch open positions from Polymarket"""
        positions = []
        try:
            # This would need to be implemented in Polymarket class
            # For now, return empty list as placeholder
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
        """Get best ask/bid from market orderbook"""
        try:
            # Extract orderbook data from market object
            market_data = market[0].dict() if hasattr(market[0], 'dict') else {}
            metadata = market_data.get("metadata", {})
            
            # Parse outcome prices
            import ast
            outcome_prices = ast.literal_eval(metadata.get("outcome_prices", "[0, 0]"))
            
            # Simple approximation: use outcome prices as mid
            if len(outcome_prices) >= 2:
                best_ask = max(outcome_prices)
                best_bid = min(outcome_prices)
                return best_ask, best_bid
        except Exception as e:
            print(f"[RISK] Warning: Could not parse orderbook: {e}")
        
        return 0.0, 0.0

    def one_best_trade(self) -> None:
        """
        one_best_trade with risk management integration
        """
        try:
            self.pre_trade_logic()

            # Get portfolio state for risk checks
            portfolio = self._get_portfolio_state()
            print(f"[RISK] Equity: ${portfolio.equity:.2f}, Exposure: {portfolio.exposure_pct:.1f}%, Positions: {portfolio.concurrent_positions}")

            events = self.polymarket.get_all_tradeable_events()
            print(f"1. FOUND {len(events)} EVENTS")

            filtered_events = self.agent.filter_events_with_rag(events)
            print(f"2. FILTERED {len(filtered_events)} EVENTS")

            markets = self.agent.map_filtered_events_to_markets(filtered_events)
            print()
            print(f"3. FOUND {len(markets)} MARKETS")

            print()
            filtered_markets = self.agent.filter_markets(markets)
            print(f"4. FILTERED {len(filtered_markets)} MARKETS")

            if not filtered_markets:
                print("[RISK] No markets passed filtering. Skipping.")
                return

            market = filtered_markets[0]
            
            # Get orderbook for spread check
            best_ask, best_bid = self._get_market_orderbook(market)
            
            best_trade = self.agent.source_best_trade(market)
            print(f"5. CALCULATED TRADE {best_trade}")

            # Get raw amount from agent
            raw_amount = self.agent.format_trade_prompt_for_execution(best_trade)
            
            # Apply risk-based position sizing
            # Extract confidence and edge from trade analysis (simplified)
            confidence = 0.7  # Would come from LLM analysis
            edge = 50  # bps, would come from analysis
            
            sized_amount = self.risk.calculate_position_size(portfolio, confidence, edge)
            print(f"[RISK] Raw amount: ${raw_amount:.2f}, Risk-sized: ${sized_amount:.2f}")
            
            # Use the smaller of the two
            amount = min(raw_amount, sized_amount)
            
            # Final risk check before execution
            entry_price = (best_ask + best_bid) / 2 if best_ask > 0 and best_bid > 0 else 0.5
            
            allowed, reason, msg = self.risk.check_trade_allowed(
                portfolio, amount, entry_price, best_ask, best_bid
            )
            
            if not allowed:
                print(f"[RISK] Trade BLOCKED: {msg}")
                return
            
            print(f"[RISK] Trade APPROVED: ${amount:.2f}")

            # Please refer to TOS before uncommenting: polymarket.com/tos
            # trade = self.polymarket.execute_market_order(market, amount)
            # print(f"6. TRADED {trade}")
            
            # Update PnL tracking (would be done after trade confirmation)
            # self._daily_pnl += calculated_pnl

        except Exception as e:
            print(f"Error {e}")
            # Limit retries - max 3 attempts
            raise  # Re-raise instead of infinite recursion

    def maintain_positions(self):
        """Check existing positions for exit signals"""
        try:
            portfolio = self._get_portfolio_state()
            
            for position in portfolio.positions:
                # Get current market data
                market_data = self.gamma.get_market(position.market_id)
                
                # Extract current prices (simplified)
                import ast
                outcome_prices = ast.literal_eval(market_data.get("outcomePrices", "[0, 0]"))
                current_mid = sum(outcome_prices) / len(outcome_prices) if outcome_prices else 0.5
                best_ask = max(outcome_prices) if outcome_prices else 0
                best_bid = min(outcome_prices) if outcome_prices else 0
                
                # Check if exit needed
                should_exit, reason = self.risk.check_exit_needed(
                    position, current_mid, best_ask, best_bid
                )
                
                if should_exit:
                    print(f"[RISK] EXIT SIGNAL for {position.market_id}: {reason}")
                    # Execute exit (uncomment when ready)
                    # self.polymarket.exit_position(position)
        
        except Exception as e:
            print(f"[RISK] Error in maintain_positions: {e}")

    def incentive_farm(self):
        pass


if __name__ == "__main__":
    t = Trader()
    t.one_best_trade()
