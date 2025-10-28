"""Calibration tracker for forecast performance monitoring"""

import sqlite3
import os
from datetime import datetime
from typing import Optional
import json


class CalibrationTracker:
    """Track forecast accuracy and calibration over time"""

    def __init__(self, db_path: str = "data/calibration.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Forecasts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS forecasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                market_question TEXT,
                outcome TEXT,
                forecast_probability REAL NOT NULL,
                market_price REAL,
                timestamp TEXT NOT NULL,
                resolution_date TEXT,
                actual_outcome INTEGER,
                model_used TEXT,
                category TEXT,
                confidence_score REAL,
                metadata TEXT
            )
        """)

        # Trades table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                forecast_id INTEGER,
                market_id TEXT NOT NULL,
                side TEXT NOT NULL,
                size REAL NOT NULL,
                price REAL NOT NULL,
                timestamp TEXT NOT NULL,
                exit_price REAL,
                exit_timestamp TEXT,
                pnl REAL,
                reason TEXT,
                FOREIGN KEY (forecast_id) REFERENCES forecasts (id)
            )
        """)

        conn.commit()
        conn.close()

    def log_forecast(self,
                     market_id: str,
                     market_question: str,
                     outcome: str,
                     forecast_probability: float,
                     market_price: Optional[float] = None,
                     resolution_date: Optional[str] = None,
                     model_used: str = "gpt-3.5-turbo-16k",
                     category: Optional[str] = None,
                     confidence_score: Optional[float] = None,
                     metadata: Optional[dict] = None) -> int:
        """Log a forecast for later calibration analysis"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO forecasts (
                market_id, market_question, outcome, forecast_probability,
                market_price, timestamp, resolution_date, model_used,
                category, confidence_score, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            market_id, market_question, outcome, forecast_probability,
            market_price, datetime.now().isoformat(), resolution_date,
            model_used, category, confidence_score,
            json.dumps(metadata) if metadata else None
        ))

        forecast_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return forecast_id

    def log_trade(self,
                  forecast_id: int,
                  market_id: str,
                  side: str,
                  size: float,
                  price: float) -> int:
        """Log a trade execution"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO trades (
                forecast_id, market_id, side, size, price, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            forecast_id, market_id, side, size, price,
            datetime.now().isoformat()
        ))

        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return trade_id

    def update_resolution(self, market_id: str, actual_outcome: int):
        """Update forecast with actual outcome (1 = correct, 0 = incorrect)"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE forecasts
            SET actual_outcome = ?
            WHERE market_id = ?
        """, (actual_outcome, market_id))

        conn.commit()
        conn.close()

    def update_trade_exit(self, trade_id: int, exit_price: float, reason: str = "manual"):
        """Update trade with exit information"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get entry price and size
        cursor.execute("SELECT price, size, side FROM trades WHERE id = ?", (trade_id,))
        result = cursor.fetchone()
        if not result:
            conn.close()
            return

        entry_price, size, side = result

        # Calculate PnL
        if side == "BUY":
            pnl = (exit_price - entry_price) * size
        else:  # SELL
            pnl = (entry_price - exit_price) * size

        cursor.execute("""
            UPDATE trades
            SET exit_price = ?, exit_timestamp = ?, pnl = ?, reason = ?
            WHERE id = ?
        """, (exit_price, datetime.now().isoformat(), pnl, reason, trade_id))

        conn.commit()
        conn.close()

    def get_brier_score(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> float:
        """Calculate Brier score for resolved forecasts (lower is better, <0.10 is elite)"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = """
            SELECT forecast_probability, actual_outcome
            FROM forecasts
            WHERE actual_outcome IS NOT NULL
        """
        params = []

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)

        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()

        if not results:
            return None

        # Brier score = average of (forecast - outcome)^2
        brier_sum = sum((forecast - outcome) ** 2 for forecast, outcome in results)
        return brier_sum / len(results)

    def get_calibration_curve(self, num_bins: int = 10):
        """Get calibration data for plotting"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT forecast_probability, actual_outcome
            FROM forecasts
            WHERE actual_outcome IS NOT NULL
        """)
        results = cursor.fetchall()
        conn.close()

        if not results:
            return None

        # Group forecasts into bins
        bins = {}
        for i in range(num_bins):
            bins[i] = {'forecasts': [], 'outcomes': []}

        for forecast, outcome in results:
            bin_idx = min(int(forecast * num_bins), num_bins - 1)
            bins[bin_idx]['forecasts'].append(forecast)
            bins[bin_idx]['outcomes'].append(outcome)

        # Calculate average forecast vs actual rate per bin
        calibration_data = []
        for bin_idx in range(num_bins):
            if bins[bin_idx]['forecasts']:
                avg_forecast = sum(bins[bin_idx]['forecasts']) / len(bins[bin_idx]['forecasts'])
                actual_rate = sum(bins[bin_idx]['outcomes']) / len(bins[bin_idx]['outcomes'])
                count = len(bins[bin_idx]['forecasts'])
                calibration_data.append({
                    'bin': bin_idx,
                    'avg_forecast': avg_forecast,
                    'actual_rate': actual_rate,
                    'count': count
                })

        return calibration_data

    def get_performance_summary(self):
        """Get overall performance metrics"""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Total forecasts
        cursor.execute("SELECT COUNT(*) FROM forecasts")
        total_forecasts = cursor.fetchone()[0]

        # Resolved forecasts
        cursor.execute("SELECT COUNT(*) FROM forecasts WHERE actual_outcome IS NOT NULL")
        resolved_forecasts = cursor.fetchone()[0]

        # Win rate
        cursor.execute("SELECT COUNT(*) FROM forecasts WHERE actual_outcome = 1")
        correct_forecasts = cursor.fetchone()[0]

        # Brier score
        brier_score = self.get_brier_score()

        # Trading performance
        cursor.execute("SELECT SUM(pnl) FROM trades WHERE pnl IS NOT NULL")
        result = cursor.fetchone()
        total_pnl = result[0] if result[0] else 0

        cursor.execute("SELECT COUNT(*) FROM trades WHERE pnl > 0")
        winning_trades = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM trades WHERE pnl IS NOT NULL")
        total_trades = cursor.fetchone()[0]

        conn.close()

        return {
            'total_forecasts': total_forecasts,
            'resolved_forecasts': resolved_forecasts,
            'correct_forecasts': correct_forecasts,
            'win_rate': correct_forecasts / resolved_forecasts if resolved_forecasts > 0 else 0,
            'brier_score': brier_score,
            'total_pnl': total_pnl,
            'winning_trades': winning_trades,
            'total_trades': total_trades,
            'trade_win_rate': winning_trades / total_trades if total_trades > 0 else 0
        }

    def print_performance_report(self):
        """Print formatted performance report"""

        summary = self.get_performance_summary()

        print("\n" + "="*70)
        print("FORECAST CALIBRATION & PERFORMANCE REPORT")
        print("="*70 + "\n")

        print("FORECASTING PERFORMANCE:")
        print(f"  Total Forecasts:      {summary['total_forecasts']}")
        print(f"  Resolved Forecasts:   {summary['resolved_forecasts']}")
        print(f"  Correct Forecasts:    {summary['correct_forecasts']}")
        print(f"  Win Rate:             {summary['win_rate']:.1%}")
        if summary['brier_score']:
            print(f"  Brier Score:          {summary['brier_score']:.4f}", end="")
            if summary['brier_score'] < 0.10:
                print(" (ELITE)")
            elif summary['brier_score'] < 0.15:
                print(" (GOOD)")
            elif summary['brier_score'] < 0.20:
                print(" (AVERAGE)")
            else:
                print(" (NEEDS IMPROVEMENT)")
        else:
            print(f"  Brier Score:          N/A (no resolved forecasts)")

        print(f"\nTRADING PERFORMANCE:")
        print(f"  Total Trades:         {summary['total_trades']}")
        print(f"  Winning Trades:       {summary['winning_trades']}")
        print(f"  Trade Win Rate:       {summary['trade_win_rate']:.1%}")
        print(f"  Total P&L:            ${summary['total_pnl']:,.2f}")

        print("\n" + "="*70 + "\n")
