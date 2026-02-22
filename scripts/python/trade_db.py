"""
Trade Database Module - SQLite Persistence & Analytics

Tracks every trade, position update, and strategy performance.
Provides auto-learning data for the trading engine.

Tables:
- trades: Every buy/sell order with strategy attribution
- position_snapshots: Periodic P&L snapshots for positions
- strategy_stats: Aggregated win/loss/PnL per strategy (auto-updated)
- cycles: Summary of each trading cycle
"""

import os
import sqlite3
import json
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "polymarket_trades.db")


class TradeDB:
    """SQLite database for trade persistence and analytics."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()
        logger.info(f"TradeDB initialized at {self.db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,          -- BUY or SELL
                    token_id TEXT NOT NULL,
                    market TEXT DEFAULT '',
                    strategy TEXT DEFAULT 'MANUAL', -- LATENCY_ARB, PARITY_ARB, NO_BIAS, etc.
                    amount REAL DEFAULT 0,          -- USDC spent/received
                    price REAL DEFAULT 0,           -- price per share
                    size REAL DEFAULT 0,            -- number of shares
                    result TEXT DEFAULT '',         -- execution result
                    status TEXT DEFAULT 'EXECUTED', -- EXECUTED, FAILED, SIMULATED
                    pnl REAL DEFAULT 0,             -- realized P&L (filled after close)
                    is_exit INTEGER DEFAULT 0,      -- 1 if this trade closes a position
                    exit_reason TEXT DEFAULT '',    -- STOP_LOSS, TAKE_PROFIT, TIME_EXIT, LLM, MANUAL
                    entry_trade_id INTEGER DEFAULT 0, -- links exit to entry
                    confidence REAL DEFAULT 0,      -- strategy confidence at time of trade
                    cycle_id INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS position_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    market TEXT DEFAULT '',
                    size REAL DEFAULT 0,
                    entry_price REAL DEFAULT 0,
                    current_price REAL DEFAULT 0,
                    unrealized_pnl REAL DEFAULT 0,
                    percent_pnl REAL DEFAULT 0,
                    peak_pnl REAL DEFAULT 0       -- highest P&L seen (for trailing stop)
                );

                CREATE TABLE IF NOT EXISTS strategy_stats (
                    strategy TEXT PRIMARY KEY,
                    total_trades INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    avg_return REAL DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    weight REAL DEFAULT 1.0,        -- dynamic weight for auto-learning
                    last_updated TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS cycles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    cycle_type TEXT DEFAULT 'DEEP', -- FAST or DEEP
                    signals_found INTEGER DEFAULT 0,
                    trades_executed INTEGER DEFAULT 0,
                    trades_auto INTEGER DEFAULT 0,   -- trades without LLM
                    trades_llm INTEGER DEFAULT 0,    -- trades via LLM
                    cycle_pnl REAL DEFAULT 0,
                    positions_exited INTEGER DEFAULT 0,
                    duration_ms INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
                CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
                CREATE INDEX IF NOT EXISTS idx_trades_token_id ON trades(token_id);
                CREATE INDEX IF NOT EXISTS idx_position_snapshots_token ON position_snapshots(token_id);
            """)
            conn.commit()

            # Initialize strategy stats if empty
            strategies = ["LATENCY_ARB", "PARITY_ARB", "NO_BIAS", "HIGH_PROB", "LONGSHOT", "VALUE", "STOP_LOSS", "TAKE_PROFIT"]
            for s in strategies:
                conn.execute(
                    "INSERT OR IGNORE INTO strategy_stats (strategy, last_updated) VALUES (?, ?)",
                    (s, datetime.now(timezone.utc).isoformat())
                )
            conn.commit()
        finally:
            conn.close()

    # ─── Trade Recording ───

    def record_trade(
        self,
        action: str,
        token_id: str,
        market: str = "",
        strategy: str = "MANUAL",
        amount: float = 0,
        price: float = 0,
        size: float = 0,
        result: str = "",
        status: str = "EXECUTED",
        is_exit: bool = False,
        exit_reason: str = "",
        entry_trade_id: int = 0,
        confidence: float = 0,
        cycle_id: int = 0,
    ) -> int:
        """Record a trade and return its ID."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """INSERT INTO trades
                   (timestamp, action, token_id, market, strategy, amount, price, size,
                    result, status, is_exit, exit_reason, entry_trade_id, confidence, cycle_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, action.upper(), token_id, market, strategy.upper(), amount, price, size,
                 result, status, 1 if is_exit else 0, exit_reason, entry_trade_id, confidence, cycle_id)
            )
            trade_id = cursor.lastrowid
            conn.commit()

            # If it's an exit trade with P&L, update strategy stats
            if is_exit and status == "EXECUTED":
                self._update_strategy_stats_on_exit(conn, strategy, amount, price, entry_trade_id)

            logger.info(f"TradeDB: Recorded {action} #{trade_id} ({strategy}) ${amount:.2f}")
            return trade_id
        finally:
            conn.close()

    def _update_strategy_stats_on_exit(self, conn, strategy: str, exit_amount: float, exit_price: float, entry_trade_id: int):
        """Update strategy stats when a position is closed."""
        try:
            # Get the entry trade to calculate P&L
            entry = conn.execute("SELECT * FROM trades WHERE id = ?", (entry_trade_id,)).fetchone()
            if entry:
                entry_cost = float(entry["amount"])
                # For a BUY→SELL, profit = sell_proceeds - buy_cost
                pnl = exit_amount - entry_cost
                is_win = pnl > 0

                conn.execute("""
                    UPDATE strategy_stats SET
                        total_trades = total_trades + 1,
                        wins = wins + ?,
                        losses = losses + ?,
                        total_pnl = total_pnl + ?,
                        avg_return = CASE WHEN total_trades > 0
                            THEN (total_pnl + ?) / (total_trades + 1) ELSE ?
                        END,
                        win_rate = CASE WHEN (total_trades + 1) > 0
                            THEN CAST((wins + ?) AS REAL) / (total_trades + 1) ELSE 0
                        END,
                        last_updated = ?
                    WHERE strategy = ?
                """, (
                    1 if is_win else 0,
                    0 if is_win else 1,
                    pnl, pnl, pnl,
                    1 if is_win else 0,
                    datetime.now(timezone.utc).isoformat(),
                    strategy.upper(),
                ))

                # Update the exit trade with realized P&L
                conn.execute("UPDATE trades SET pnl = ? WHERE id = (SELECT MAX(id) FROM trades WHERE token_id = ? AND is_exit = 1)", (pnl, entry["token_id"]))
                conn.commit()

                # Auto-adjust weight based on win/loss
                self._adjust_strategy_weight(conn, strategy.upper(), is_win)
        except Exception as e:
            logger.error(f"Error updating strategy stats: {e}")

    def _adjust_strategy_weight(self, conn, strategy: str, is_win: bool):
        """Auto-learning: adjust strategy weight based on outcome."""
        try:
            row = conn.execute("SELECT weight FROM strategy_stats WHERE strategy = ?", (strategy,)).fetchone()
            if row:
                current_weight = float(row["weight"])
                if is_win:
                    new_weight = min(current_weight * 1.1, 3.0)  # Max 3x weight
                else:
                    new_weight = max(current_weight * 0.85, 0.2)  # Min 0.2x weight
                conn.execute("UPDATE strategy_stats SET weight = ? WHERE strategy = ?", (new_weight, strategy))
                conn.commit()
                logger.info(f"Strategy {strategy} weight: {current_weight:.2f} → {new_weight:.2f} ({'WIN' if is_win else 'LOSS'})")
        except Exception as e:
            logger.error(f"Error adjusting weight: {e}")

    # ─── Position Tracking ───

    def record_position_snapshot(
        self,
        token_id: str,
        market: str = "",
        size: float = 0,
        entry_price: float = 0,
        current_price: float = 0,
        unrealized_pnl: float = 0,
        percent_pnl: float = 0,
    ):
        """Record a position snapshot for tracking peak P&L (trailing stop)."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            # Get previous peak
            prev = conn.execute(
                "SELECT MAX(peak_pnl) as peak FROM position_snapshots WHERE token_id = ?",
                (token_id,)
            ).fetchone()
            peak = max(unrealized_pnl, float(prev["peak"] or 0)) if prev else unrealized_pnl

            conn.execute(
                """INSERT INTO position_snapshots
                   (timestamp, token_id, market, size, entry_price, current_price,
                    unrealized_pnl, percent_pnl, peak_pnl)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, token_id, market, size, entry_price, current_price,
                 unrealized_pnl, percent_pnl, peak)
            )
            conn.commit()
        finally:
            conn.close()

    def get_position_peak_pnl(self, token_id: str) -> float:
        """Get the highest P&L ever recorded for a position (for trailing stop)."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT MAX(peak_pnl) as peak FROM position_snapshots WHERE token_id = ?",
                (token_id,)
            ).fetchone()
            return float(row["peak"] or 0) if row else 0
        finally:
            conn.close()

    # ─── Cycle Recording ───

    def record_cycle(
        self,
        cycle_type: str = "DEEP",
        signals_found: int = 0,
        trades_executed: int = 0,
        trades_auto: int = 0,
        trades_llm: int = 0,
        cycle_pnl: float = 0,
        positions_exited: int = 0,
        duration_ms: int = 0,
    ) -> int:
        """Record a trading cycle summary."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """INSERT INTO cycles
                   (timestamp, cycle_type, signals_found, trades_executed, trades_auto,
                    trades_llm, cycle_pnl, positions_exited, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, cycle_type, signals_found, trades_executed, trades_auto,
                 trades_llm, cycle_pnl, positions_exited, duration_ms)
            )
            cycle_id = cursor.lastrowid
            conn.commit()
            return cycle_id
        finally:
            conn.close()

    # ─── Strategy Analytics ───

    def get_strategy_performance(self) -> list:
        """Get performance stats for all strategies, sorted by win rate."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM strategy_stats WHERE total_trades > 0 ORDER BY win_rate DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_strategy_weights(self) -> dict:
        """Get current dynamic weights for all strategies."""
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT strategy, weight FROM strategy_stats").fetchall()
            return {r["strategy"]: float(r["weight"]) for r in rows}
        finally:
            conn.close()

    def get_strategy_report_for_llm(self) -> str:
        """Generate a concise strategy report for the LLM prompt."""
        stats = self.get_strategy_performance()
        if not stats:
            return "Sem dados de performance ainda (primeiros trades)."

        lines = ["PERFORMANCE DAS ESTRATEGIAS (auto-learning):"]
        for s in stats:
            emoji = "🟢" if s["win_rate"] > 0.6 else "🔴" if s["win_rate"] < 0.4 else "🟡"
            lines.append(
                f"  {emoji} {s['strategy']}: {s['win_rate']*100:.0f}% win rate "
                f"({s['wins']}W/{s['losses']}L) | PnL: ${s['total_pnl']:.2f} | "
                f"Weight: {s['weight']:.2f}x"
            )

        # Add recommendations
        best = [s for s in stats if s["win_rate"] > 0.6 and s["total_trades"] >= 3]
        worst = [s for s in stats if s["win_rate"] < 0.4 and s["total_trades"] >= 3]

        if best:
            names = ", ".join(s["strategy"] for s in best)
            lines.append(f"\n  PRIORIZAR: {names} (win rate > 60%)")
        if worst:
            names = ", ".join(s["strategy"] for s in worst)
            lines.append(f"  EVITAR: {names} (win rate < 40%)")

        return "\n".join(lines)

    # ─── Portfolio Analytics ───

    def get_portfolio_stats(self) -> dict:
        """Get overall portfolio statistics."""
        conn = self._get_conn()
        try:
            # Total trades
            total = conn.execute("SELECT COUNT(*) as cnt FROM trades WHERE status = 'EXECUTED'").fetchone()
            total_trades = total["cnt"] if total else 0

            # Today's trades
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM trades WHERE status = 'EXECUTED' AND timestamp LIKE ?",
                (f"{today}%",)
            ).fetchone()
            today_trades = today_row["cnt"] if today_row else 0

            # Realized P&L
            pnl_row = conn.execute(
                "SELECT SUM(pnl) as total_pnl FROM trades WHERE is_exit = 1 AND status = 'EXECUTED'"
            ).fetchone()
            total_pnl = float(pnl_row["total_pnl"] or 0)

            # Win/Loss
            wins = conn.execute(
                "SELECT COUNT(*) as cnt FROM trades WHERE is_exit = 1 AND status = 'EXECUTED' AND pnl > 0"
            ).fetchone()
            losses = conn.execute(
                "SELECT COUNT(*) as cnt FROM trades WHERE is_exit = 1 AND status = 'EXECUTED' AND pnl <= 0"
            ).fetchone()
            n_wins = wins["cnt"] if wins else 0
            n_losses = losses["cnt"] if losses else 0
            win_rate = n_wins / (n_wins + n_losses) if (n_wins + n_losses) > 0 else 0

            # Total volume
            vol_row = conn.execute(
                "SELECT SUM(amount) as vol FROM trades WHERE status = 'EXECUTED'"
            ).fetchone()
            total_volume = float(vol_row["vol"] or 0)

            # Cycles today
            cycles_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM cycles WHERE timestamp LIKE ?",
                (f"{today}%",)
            ).fetchone()
            today_cycles = cycles_row["cnt"] if cycles_row else 0

            # Sharpe ratio approximation (if enough data)
            sharpe = 0.0
            pnl_rows = conn.execute(
                "SELECT pnl FROM trades WHERE is_exit = 1 AND status = 'EXECUTED' AND pnl != 0"
            ).fetchall()
            if len(pnl_rows) >= 5:
                pnls = [float(r["pnl"]) for r in pnl_rows]
                mean_pnl = sum(pnls) / len(pnls)
                std_pnl = math.sqrt(sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls))
                if std_pnl > 0:
                    sharpe = mean_pnl / std_pnl

            # Max drawdown
            max_dd = 0.0
            cum_pnl_rows = conn.execute(
                "SELECT pnl FROM trades WHERE is_exit = 1 AND status = 'EXECUTED' ORDER BY timestamp"
            ).fetchall()
            if cum_pnl_rows:
                cumulative = 0
                peak = 0
                for r in cum_pnl_rows:
                    cumulative += float(r["pnl"])
                    if cumulative > peak:
                        peak = cumulative
                    dd = peak - cumulative
                    if dd > max_dd:
                        max_dd = dd

            return {
                "total_trades": total_trades,
                "today_trades": today_trades,
                "total_pnl": round(total_pnl, 4),
                "win_rate": round(win_rate, 4),
                "wins": n_wins,
                "losses": n_losses,
                "total_volume": round(total_volume, 2),
                "today_cycles": today_cycles,
                "sharpe_ratio": round(sharpe, 3),
                "max_drawdown": round(max_dd, 4),
            }
        finally:
            conn.close()

    # ─── Trade History ───

    def get_recent_trades(self, limit: int = 10) -> list:
        """Get most recent trades."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_recent_winning_trades(self, limit: int = 5) -> list:
        """Get recent winning trades for few-shot LLM learning."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT action, market_question as market, price as entry_price,
                          pnl, strategy, timestamp
                   FROM trades
                   WHERE is_exit = 1 AND status = 'EXECUTED' AND pnl > 0
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_entry_trade_for_token(self, token_id: str) -> Optional[dict]:
        """Get the most recent BUY entry for a token (for matching exits)."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                """SELECT * FROM trades
                   WHERE token_id = ? AND action = 'BUY' AND is_exit = 0 AND status = 'EXECUTED'
                   ORDER BY id DESC LIMIT 1""",
                (token_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_open_trade_ids(self) -> list:
        """Get entry trades that haven't been matched with an exit."""
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT t.* FROM trades t
                WHERE t.action = 'BUY' AND t.is_exit = 0 AND t.status = 'EXECUTED'
                AND t.id NOT IN (
                    SELECT entry_trade_id FROM trades WHERE is_exit = 1 AND entry_trade_id > 0
                )
                ORDER BY t.id DESC
            """).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ─── Utility ───

    def force_update_strategy_stats(self, strategy: str, is_win: bool, pnl: float):
        """Manually update strategy stats (for when we can't match entry/exit)."""
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO strategy_stats (strategy, total_trades, wins, losses, total_pnl, weight, last_updated)
                VALUES (?, 1, ?, ?, ?, 1.0, ?)
                ON CONFLICT(strategy) DO UPDATE SET
                    total_trades = total_trades + 1,
                    wins = wins + ?,
                    losses = losses + ?,
                    total_pnl = total_pnl + ?,
                    win_rate = CAST((wins + ?) AS REAL) / (total_trades + 1),
                    avg_return = (total_pnl + ?) / (total_trades + 1),
                    last_updated = ?
            """, (
                strategy.upper(),
                1 if is_win else 0, 0 if is_win else 1, pnl,
                datetime.now(timezone.utc).isoformat(),
                1 if is_win else 0, 0 if is_win else 1, pnl,
                1 if is_win else 0, pnl,
                datetime.now(timezone.utc).isoformat(),
            ))
            conn.commit()
            self._adjust_strategy_weight(conn, strategy.upper(), is_win)
        finally:
            conn.close()

    def get_stats_summary(self) -> str:
        """Get a formatted summary string for Telegram."""
        stats = self.get_portfolio_stats()
        strat_stats = self.get_strategy_performance()

        lines = [
            "📊 PERFORMANCE DO BOT",
            f"",
            f"📈 P&L Total: ${stats['total_pnl']:+.4f}",
            f"🎯 Win Rate: {stats['win_rate']*100:.1f}% ({stats['wins']}W / {stats['losses']}L)",
            f"📉 Max Drawdown: ${stats['max_drawdown']:.4f}",
            f"📏 Sharpe Ratio: {stats['sharpe_ratio']:.3f}",
            f"",
            f"🔢 Total Trades: {stats['total_trades']}",
            f"📅 Hoje: {stats['today_trades']} trades, {stats['today_cycles']} ciclos",
            f"💰 Volume Total: ${stats['total_volume']:.2f}",
        ]

        if strat_stats:
            lines.append(f"\n📋 ESTRATÉGIAS:")
            for s in strat_stats:
                emoji = "🟢" if s["win_rate"] > 0.6 else "🔴" if s["win_rate"] < 0.4 else "🟡"
                lines.append(
                    f"  {emoji} {s['strategy']}: {s['win_rate']*100:.0f}% "
                    f"({s['wins']}W/{s['losses']}L) ${s['total_pnl']:+.2f} "
                    f"[{s['weight']:.1f}x]"
                )

        return "\n".join(lines)
