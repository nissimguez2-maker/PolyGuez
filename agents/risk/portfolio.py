"""Portfolio management and position tracking"""

import sqlite3
import os
from datetime import datetime
from typing import List, Optional, Dict
import json


class PortfolioManager:
    """Manage multiple positions and portfolio-level risk"""

    def __init__(self, db_path: str = "data/portfolio.db", max_positions: int = 10):
        self.db_path = db_path
        self.max_positions = max_positions
        self.max_correlation = 0.60  # Max correlation between positions
        self.max_portfolio_risk = 0.40  # Max 40% of capital deployed
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize portfolio database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                market_question TEXT,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                current_price REAL,
                size_usd REAL NOT NULL,
                size_fraction REAL NOT NULL,
                category TEXT,
                entry_timestamp TEXT NOT NULL,
                exit_timestamp TEXT,
                exit_price REAL,
                pnl REAL,
                pnl_percent REAL,
                status TEXT DEFAULT 'OPEN',
                stop_loss REAL,
                take_profit REAL,
                metadata TEXT
            )
        """)

        conn.commit()
        conn.close()

    def add_position(self,
                     market_id: str,
                     market_question: str,
                     side: str,
                     entry_price: float,
                     size_usd: float,
                     size_fraction: float,
                     category: Optional[str] = None,
                     stop_loss: Optional[float] = None,
                     take_profit: Optional[float] = None,
                     metadata: Optional[dict] = None) -> int:
        """Add new position to portfolio"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO positions (
                market_id, market_question, side, entry_price, current_price,
                size_usd, size_fraction, category, entry_timestamp,
                stop_loss, take_profit, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            market_id, market_question, side, entry_price, entry_price,
            size_usd, size_fraction, category, datetime.now().isoformat(),
            stop_loss, take_profit, json.dumps(metadata) if metadata else None
        ))

        position_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return position_id

    def get_open_positions(self) -> List[Dict]:
        """Get all open positions"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM positions WHERE status = 'OPEN'
        """)

        columns = [desc[0] for desc in cursor.description]
        positions = []

        for row in cursor.fetchall():
            position = dict(zip(columns, row))
            positions.append(position)

        conn.close()
        return positions

    def update_position_price(self, position_id: int, current_price: float):
        """Update current price and calculate unrealized P&L"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get position details
        cursor.execute("""
            SELECT entry_price, size_usd, side
            FROM positions WHERE id = ?
        """, (position_id,))

        result = cursor.fetchone()
        if not result:
            conn.close()
            return

        entry_price, size_usd, side = result

        # Calculate P&L
        if side == "BUY":
            pnl = (current_price - entry_price) * size_usd / entry_price
            pnl_percent = (current_price - entry_price) / entry_price
        else:  # SELL
            pnl = (entry_price - current_price) * size_usd / entry_price
            pnl_percent = (entry_price - current_price) / entry_price

        cursor.execute("""
            UPDATE positions
            SET current_price = ?, pnl = ?, pnl_percent = ?
            WHERE id = ?
        """, (current_price, pnl, pnl_percent, position_id))

        conn.commit()
        conn.close()

    def close_position(self, position_id: int, exit_price: float, reason: str = "manual"):
        """Close a position"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get position details
        cursor.execute("""
            SELECT entry_price, size_usd, side
            FROM positions WHERE id = ?
        """, (position_id,))

        result = cursor.fetchone()
        if not result:
            conn.close()
            return

        entry_price, size_usd, side = result

        # Calculate final P&L
        if side == "BUY":
            pnl = (exit_price - entry_price) * size_usd / entry_price
            pnl_percent = (exit_price - entry_price) / entry_price
        else:  # SELL
            pnl = (entry_price - exit_price) * size_usd / entry_price
            pnl_percent = (entry_price - exit_price) / entry_price

        cursor.execute("""
            UPDATE positions
            SET status = 'CLOSED', exit_price = ?, exit_timestamp = ?,
                pnl = ?, pnl_percent = ?, current_price = ?
            WHERE id = ?
        """, (exit_price, datetime.now().isoformat(), pnl, pnl_percent, exit_price, position_id))

        conn.commit()
        conn.close()

        return pnl

    def get_total_exposure(self) -> float:
        """Get total capital deployed across open positions"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT SUM(size_fraction) FROM positions WHERE status = 'OPEN'
        """)

        result = cursor.fetchone()
        conn.close()

        return result[0] if result[0] else 0.0

    def get_category_exposure(self, category: str) -> float:
        """Get exposure to a specific category"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT SUM(size_fraction) FROM positions
            WHERE status = 'OPEN' AND category = ?
        """, (category,))

        result = cursor.fetchone()
        conn.close()

        return result[0] if result[0] else 0.0

    def should_add_position(self,
                           new_position_size: float,
                           category: Optional[str] = None,
                           max_category_exposure: float = 0.25) -> bool:
        """
        Check if new position would violate portfolio risk limits

        Args:
            new_position_size: Size fraction of new position
            category: Market category
            max_category_exposure: Max exposure to single category (default 25%)

        Returns:
            True if position is acceptable, False otherwise
        """

        # Check total exposure
        current_exposure = self.get_total_exposure()
        if current_exposure + new_position_size > self.max_portfolio_risk:
            return False

        # Check number of positions
        open_positions = self.get_open_positions()
        if len(open_positions) >= self.max_positions:
            return False

        # Check category concentration
        if category:
            category_exposure = self.get_category_exposure(category)
            if category_exposure + new_position_size > max_category_exposure:
                return False

        return True

    def get_portfolio_summary(self) -> Dict:
        """Get portfolio performance summary"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Open positions
        cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'OPEN'")
        open_positions = cursor.fetchone()[0]

        # Total exposure
        cursor.execute("SELECT SUM(size_fraction) FROM positions WHERE status = 'OPEN'")
        result = cursor.fetchone()
        total_exposure = result[0] if result[0] else 0.0

        # Unrealized P&L
        cursor.execute("SELECT SUM(pnl) FROM positions WHERE status = 'OPEN'")
        result = cursor.fetchone()
        unrealized_pnl = result[0] if result[0] else 0.0

        # Realized P&L
        cursor.execute("SELECT SUM(pnl) FROM positions WHERE status = 'CLOSED'")
        result = cursor.fetchone()
        realized_pnl = result[0] if result[0] else 0.0

        # Win rate
        cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'CLOSED' AND pnl > 0")
        winning_trades = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'CLOSED'")
        total_closed = cursor.fetchone()[0]

        conn.close()

        return {
            'open_positions': open_positions,
            'total_exposure': total_exposure,
            'unrealized_pnl': unrealized_pnl,
            'realized_pnl': realized_pnl,
            'total_pnl': unrealized_pnl + realized_pnl,
            'winning_trades': winning_trades,
            'total_closed': total_closed,
            'win_rate': winning_trades / total_closed if total_closed > 0 else 0
        }

    def print_portfolio_summary(self):
        """Print formatted portfolio summary"""

        summary = self.get_portfolio_summary()

        print("\n" + "="*70)
        print("PORTFOLIO SUMMARY")
        print("="*70 + "\n")

        print(f"Open Positions:       {summary['open_positions']}")
        print(f"Total Exposure:       {summary['total_exposure']:.1%}")
        print(f"Unrealized P&L:       ${summary['unrealized_pnl']:,.2f}")
        print(f"Realized P&L:         ${summary['realized_pnl']:,.2f}")
        print(f"Total P&L:            ${summary['total_pnl']:,.2f}")
        print(f"Closed Trades:        {summary['total_closed']}")
        print(f"Winning Trades:       {summary['winning_trades']}")
        print(f"Win Rate:             {summary['win_rate']:.1%}")

        print("\n" + "="*70 + "\n")
