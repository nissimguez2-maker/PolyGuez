from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class TradeRecord:
    trade_id: str
    realized_pnl: float
    exit_reason: str
    mae: float = 0.0
    mfe: float = 0.0
    spread_entry: Optional[float] = None


class TradeMetricsTracker:
    """Minimal metrics tracker used by the webhook server."""

    def __init__(self, initial_equity: float):
        self.initial_equity = float(initial_equity)
        self.trades: List[TradeRecord] = []
        self.exposure_peak: float = 0.0
        self._equity_curve: List[float] = [self.initial_equity]

    def update_snapshot(self, unrealized_pnl: float, realized_pnl: float, exposure: float) -> None:
        self.exposure_peak = max(self.exposure_peak, float(exposure or 0.0))
        current_equity = self.initial_equity + float(realized_pnl or 0.0)
        self._equity_curve.append(current_equity)

    def complete_trade(
        self,
        trade_id: str,
        exit_price: float,
        realized_pnl: float,
        exit_reason: str,
        mae: float = 0.0,
        mfe: float = 0.0,
        spread_entry: Optional[float] = None,
    ) -> None:
        self.trades.append(
            TradeRecord(
                trade_id=trade_id,
                realized_pnl=float(realized_pnl or 0.0),
                exit_reason=str(exit_reason),
                mae=float(mae or 0.0),
                mfe=float(mfe or 0.0),
                spread_entry=spread_entry,
            )
        )

    def _drawdowns(self) -> Dict[str, float]:
        peak = self._equity_curve[0] if self._equity_curve else self.initial_equity
        max_dd = 0.0
        current_dd = 0.0
        for equity in self._equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity)
            max_dd = max(max_dd, dd)
            current_dd = dd
        return {"max_drawdown": max_dd, "current_drawdown": current_dd}

    def get_statistics(self) -> Dict[str, float]:
        total = len(self.trades)
        wins = [t for t in self.trades if t.realized_pnl > 0]
        losses = [t for t in self.trades if t.realized_pnl < 0]
        win_count = len(wins)
        loss_count = len(losses)
        avg_win = sum(t.realized_pnl for t in wins) / win_count if win_count else 0.0
        avg_loss = sum(t.realized_pnl for t in losses) / loss_count if loss_count else 0.0
        win_rate = win_count / total if total else 0.0
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
        profit_factor = (
            (sum(t.realized_pnl for t in wins) / abs(sum(t.realized_pnl for t in losses)))
            if losses else 0.0
        )
        dd = self._drawdowns()
        avg_mae = sum(t.mae for t in self.trades) / total if total else 0.0
        avg_mfe = sum(t.mfe for t in self.trades) / total if total else 0.0
        worst_mae = min((t.mae for t in self.trades), default=0.0)
        best_mfe = max((t.mfe for t in self.trades), default=0.0)
        avg_spread = (
            sum(t.spread_entry for t in self.trades if t.spread_entry is not None)
            / len([t for t in self.trades if t.spread_entry is not None])
            if any(t.spread_entry is not None for t in self.trades) else 0.0
        )

        return {
            "total_trades": total,
            "wins": win_count,
            "losses": loss_count,
            "win_rate": win_rate,
            "expectancy": expectancy,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_drawdown": dd["max_drawdown"],
            "current_drawdown": dd["current_drawdown"],
            "avg_time_in_trade_seconds": 0.0,
            "time_in_trade_p90_seconds": 0.0,
            "avg_mae": avg_mae,
            "worst_mae": worst_mae,
            "avg_mfe": avg_mfe,
            "best_mfe": best_mfe,
            "avg_spread_at_entry": avg_spread,
        }

    def get_sample_size_report(self) -> Dict[str, int]:
        # Placeholder: no confidence buckets tracked in this lightweight tracker
        return {
            "conf_4": 0,
            "conf_5": 0,
            "conf_other": 0,
        }
