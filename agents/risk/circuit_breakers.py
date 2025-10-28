"""Circuit breakers and risk controls to prevent catastrophic losses"""

from datetime import datetime, timedelta
from typing import Optional
import sqlite3
import os


class TradingHalted(Exception):
    """Exception raised when circuit breaker trips"""
    pass


class CircuitBreaker:
    """
    Safety controls to halt trading under adverse conditions
    """

    def __init__(self, db_path: str = "data/circuit_breaker.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

        # Risk limits
        self.max_daily_loss_pct = 0.05      # 5% daily loss limit
        self.max_weekly_loss_pct = 0.10     # 10% weekly loss limit
        self.max_consecutive_losses = 5     # Halt after 5 losses in a row
        self.max_position_size = 0.15       # 15% max per position
        self.max_portfolio_risk = 0.40      # 40% max total exposure

    def _init_db(self):
        """Initialize circuit breaker tracking database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_pnl (
                date TEXT PRIMARY KEY,
                pnl REAL NOT NULL,
                starting_capital REAL NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                market_id TEXT,
                pnl REAL NOT NULL,
                is_win INTEGER NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS halts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                reason TEXT NOT NULL,
                resume_timestamp TEXT
            )
        """)

        conn.commit()
        conn.close()

    def log_trade_result(self, market_id: str, pnl: float):
        """Log a trade result for tracking"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        is_win = 1 if pnl > 0 else 0

        cursor.execute("""
            INSERT INTO trade_results (timestamp, market_id, pnl, is_win)
            VALUES (?, ?, ?, ?)
        """, (datetime.now().isoformat(), market_id, pnl, is_win))

        conn.commit()
        conn.close()

    def log_daily_pnl(self, date: str, pnl: float, starting_capital: float):
        """Log daily P&L"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO daily_pnl (date, pnl, starting_capital)
            VALUES (?, ?, ?)
        """, (date, pnl, starting_capital))

        conn.commit()
        conn.close()

    def get_daily_pnl(self, date: Optional[str] = None) -> float:
        """Get P&L for specific date (default today)"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT pnl, starting_capital FROM daily_pnl WHERE date = ?
        """, (date,))

        result = cursor.fetchone()
        conn.close()

        if result:
            pnl, starting_capital = result
            return pnl / starting_capital if starting_capital > 0 else 0.0
        return 0.0

    def get_weekly_pnl(self) -> float:
        """Get P&L for last 7 days"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

        cursor.execute("""
            SELECT SUM(pnl), AVG(starting_capital)
            FROM daily_pnl
            WHERE date >= ?
        """, (week_ago,))

        result = cursor.fetchone()
        conn.close()

        if result and result[0] and result[1]:
            total_pnl, avg_capital = result
            return total_pnl / avg_capital if avg_capital > 0 else 0.0
        return 0.0

    def get_consecutive_losses(self) -> int:
        """Get current streak of consecutive losses"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT is_win FROM trade_results
            ORDER BY timestamp DESC
            LIMIT 20
        """)

        results = cursor.fetchall()
        conn.close()

        consecutive = 0
        for (is_win,) in results:
            if is_win == 0:
                consecutive += 1
            else:
                break

        return consecutive

    def check_halt_conditions(self, portfolio_manager=None) -> None:
        """
        Check all circuit breaker conditions and raise TradingHalted if triggered

        Args:
            portfolio_manager: Optional PortfolioManager instance for exposure checks

        Raises:
            TradingHalted: If any circuit breaker condition is met
        """

        # Check daily loss limit
        daily_pnl_pct = self.get_daily_pnl()
        if daily_pnl_pct < -self.max_daily_loss_pct:
            self._log_halt(f"Daily loss limit exceeded: {daily_pnl_pct:.1%}")
            raise TradingHalted(
                f"Circuit breaker: Daily loss limit ({self.max_daily_loss_pct:.1%}) exceeded. "
                f"Current loss: {daily_pnl_pct:.1%}"
            )

        # Check weekly loss limit
        weekly_pnl_pct = self.get_weekly_pnl()
        if weekly_pnl_pct < -self.max_weekly_loss_pct:
            self._log_halt(f"Weekly loss limit exceeded: {weekly_pnl_pct:.1%}")
            raise TradingHalted(
                f"Circuit breaker: Weekly loss limit ({self.max_weekly_loss_pct:.1%}) exceeded. "
                f"Current loss: {weekly_pnl_pct:.1%}"
            )

        # Check consecutive losses
        consecutive_losses = self.get_consecutive_losses()
        if consecutive_losses >= self.max_consecutive_losses:
            self._log_halt(f"Consecutive loss streak: {consecutive_losses}")
            raise TradingHalted(
                f"Circuit breaker: {consecutive_losses} consecutive losses. "
                f"Review strategy before resuming."
            )

        # Check portfolio exposure if manager provided
        if portfolio_manager:
            total_exposure = portfolio_manager.get_total_exposure()
            if total_exposure > self.max_portfolio_risk:
                self._log_halt(f"Portfolio risk limit exceeded: {total_exposure:.1%}")
                raise TradingHalted(
                    f"Circuit breaker: Portfolio exposure ({total_exposure:.1%}) "
                    f"exceeds limit ({self.max_portfolio_risk:.1%})"
                )

    def check_position_size(self, position_size: float) -> None:
        """
        Check if proposed position size exceeds limits

        Args:
            position_size: Proposed position size as fraction

        Raises:
            TradingHalted: If position size too large
        """
        if position_size > self.max_position_size:
            raise TradingHalted(
                f"Position size ({position_size:.1%}) exceeds maximum ({self.max_position_size:.1%})"
            )

    def _log_halt(self, reason: str):
        """Log circuit breaker activation"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO halts (timestamp, reason)
            VALUES (?, ?)
        """, (datetime.now().isoformat(), reason))

        conn.commit()
        conn.close()

    def reset_halts(self):
        """Reset all halts (manual override)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE halts SET resume_timestamp = ?
            WHERE resume_timestamp IS NULL
        """, (datetime.now().isoformat(),))

        conn.commit()
        conn.close()

    def get_halt_status(self) -> Optional[dict]:
        """Get current halt status if any"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT timestamp, reason FROM halts
            WHERE resume_timestamp IS NULL
            ORDER BY timestamp DESC
            LIMIT 1
        """)

        result = cursor.fetchone()
        conn.close()

        if result:
            return {
                'timestamp': result[0],
                'reason': result[1]
            }
        return None
