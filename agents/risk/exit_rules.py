"""Automated stop-loss and take-profit exit rules"""

from typing import List, Optional, Tuple


class ExitRules:
    """
    Automated exit logic for open positions
    """

    def __init__(self,
                 stop_loss_pct: float = 0.15,      # -15% stop loss
                 take_profit_pct: float = 0.25,     # +25% take profit
                 trailing_stop_pct: float = 0.10):  # 10% trailing stop
        """
        Initialize exit rules

        Args:
            stop_loss_pct: Maximum loss before auto-exit (0.15 = 15%)
            take_profit_pct: Target profit for auto-exit (0.25 = 25%)
            trailing_stop_pct: Trailing stop distance (0.10 = 10%)
        """
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct

    def calculate_stop_loss_price(self, entry_price: float, side: str) -> float:
        """Calculate stop loss price based on entry"""
        if side == "BUY":
            # Stop loss below entry for long positions
            return entry_price * (1 - self.stop_loss_pct)
        else:  # SELL
            # Stop loss above entry for short positions
            return entry_price * (1 + self.stop_loss_pct)

    def calculate_take_profit_price(self, entry_price: float, side: str) -> float:
        """Calculate take profit price based on entry"""
        if side == "BUY":
            # Take profit above entry for long positions
            return entry_price * (1 + self.take_profit_pct)
        else:  # SELL
            # Take profit below entry for short positions
            return entry_price * (1 - self.take_profit_pct)

    def should_exit(self,
                   entry_price: float,
                   current_price: float,
                   side: str,
                   high_water_mark: Optional[float] = None) -> Tuple[bool, str]:
        """
        Determine if position should be exited

        Args:
            entry_price: Entry price
            current_price: Current market price
            side: "BUY" or "SELL"
            high_water_mark: Highest favorable price reached (for trailing stop)

        Returns:
            (should_exit: bool, reason: str)
        """

        # Calculate P&L percentage
        if side == "BUY":
            pnl_pct = (current_price - entry_price) / entry_price
        else:  # SELL
            pnl_pct = (entry_price - current_price) / entry_price

        # Check stop loss
        if pnl_pct <= -self.stop_loss_pct:
            return (True, f"STOP_LOSS (P&L: {pnl_pct:.1%})")

        # Check take profit
        if pnl_pct >= self.take_profit_pct:
            return (True, f"TAKE_PROFIT (P&L: {pnl_pct:.1%})")

        # Check trailing stop if we have a high water mark
        if high_water_mark is not None:
            if side == "BUY":
                # For long positions, check if we've fallen from high water mark
                drawdown_from_peak = (current_price - high_water_mark) / high_water_mark
                if drawdown_from_peak <= -self.trailing_stop_pct:
                    return (True, f"TRAILING_STOP (Drawdown: {drawdown_from_peak:.1%})")
            else:  # SELL
                # For short positions, check if price has risen from low water mark
                rise_from_trough = (high_water_mark - current_price) / current_price
                if rise_from_trough <= -self.trailing_stop_pct:
                    return (True, f"TRAILING_STOP (Rise: {rise_from_trough:.1%})")

        return (False, "")

    def monitor_positions(self, portfolio_manager, polymarket) -> List[dict]:
        """
        Monitor all open positions and generate exit signals

        Args:
            portfolio_manager: PortfolioManager instance
            polymarket: Polymarket instance for price fetching

        Returns:
            List of positions to exit with reasons
        """
        open_positions = portfolio_manager.get_open_positions()
        exit_signals = []

        for position in open_positions:
            try:
                # Get current market price
                market_id = position['market_id']
                # Note: This would need actual implementation to fetch current price
                # current_price = polymarket.get_orderbook_price(market_id)
                current_price = position.get('current_price', position['entry_price'])

                # Check if should exit
                should_exit, reason = self.should_exit(
                    entry_price=position['entry_price'],
                    current_price=current_price,
                    side=position['side'],
                    high_water_mark=position.get('high_water_mark')
                )

                if should_exit:
                    exit_signals.append({
                        'position_id': position['id'],
                        'market_id': market_id,
                        'current_price': current_price,
                        'reason': reason,
                        'pnl': position.get('pnl', 0)
                    })

            except Exception as e:
                print(f"Error monitoring position {position.get('id')}: {e}")
                continue

        return exit_signals

    def execute_exits(self, exit_signals: List[dict], portfolio_manager, polymarket):
        """
        Execute exit orders for positions that hit exit criteria

        Args:
            exit_signals: List of exit signals from monitor_positions()
            portfolio_manager: PortfolioManager instance
            polymarket: Polymarket instance for order execution
        """
        for signal in exit_signals:
            try:
                print(f"\n{'='*70}")
                print(f"EXECUTING EXIT: {signal['reason']}")
                print(f"Market ID: {signal['market_id']}")
                print(f"Exit Price: {signal['current_price']:.4f}")
                print(f"P&L: ${signal['pnl']:,.2f}")
                print(f"{'='*70}\n")

                # Close position in portfolio tracker
                portfolio_manager.close_position(
                    position_id=signal['position_id'],
                    exit_price=signal['current_price'],
                    reason=signal['reason']
                )

                # Note: Actual market order execution would go here
                # polymarket.execute_market_order(...)

            except Exception as e:
                print(f"Error executing exit for position {signal['position_id']}: {e}")
                continue
