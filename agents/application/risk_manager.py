from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Tuple

from src.config.settings import get_settings
from agents.application.position_manager import TradeStatus
from src.market_data.telemetry import telemetry
import json
import time
from glob import glob
from pathlib import Path
import os
import tempfile


class ExitReason(str, Enum):
    SOFT_STOP = "soft_stop"
    TIME_STOP = "time_stop"


@dataclass
class ExitCheck:
    should_exit: bool
    reason: ExitReason | None = None


@dataclass
class ExposureCheck:
    allowed: bool
    reason: str
    current_exposure: float
    proposed_exposure: float
    max_exposure: float


class RiskManager:
    """Lightweight risk manager used by the webhook server."""

    def __init__(self, initial_equity: float, max_exposure_pct: float, base_risk_pct: float):
        self.initial_equity = float(initial_equity)
        self.current_equity = float(initial_equity)
        self.max_exposure_pct = float(max_exposure_pct)
        self.base_risk_pct = float(base_risk_pct)
        # Kill-switch persistent state
        self.kill_switch_until_ts: float | None = None
        self.kill_switch_reason: str | None = None
        self.kill_switch_last_trigger_ts: float | None = None
        # Load persisted state if available
        try:
            self._load_risk_state()
        except Exception:
            # Do not fail initialization on load errors
            pass

    def update_equity(self, realized_pnl: float) -> None:
        self.current_equity += float(realized_pnl or 0.0)

    def calculate_position_size(self, confidence: int | None, base_size: float | None) -> float:
        settings = get_settings()
        base = float(base_size if base_size is not None else settings.PAPER_USDC)
        if confidence is None:
            return max(0.01, base)
        # Aggressive confidence scaling: higher confidence = bigger size
        # conf 5: 1.0x, conf 6: 1.5x, conf 7: 2.0x, conf 8: 2.5x, conf 9+: 3.0x
        scale_map = {5: 1.0, 6: 1.5, 7: 2.0, 8: 2.5, 9: 3.0, 10: 3.0}
        scale = scale_map.get(confidence, 1.0 + max(0, confidence - settings.MIN_CONFIDENCE) * 0.5)
        return max(0.01, base * scale)

    def check_exposure(self, proposed_trade_size: float, active_trades: Dict[str, Any]) -> ExposureCheck:
        max_exposure = self.current_equity * self.max_exposure_pct
        current_exposure = 0.0
        for trade in active_trades.values():
            if getattr(trade, "status", None) in (
                TradeStatus.PENDING,
                TradeStatus.CONFIRMED,
                TradeStatus.ADDED,
                TradeStatus.HEDGED,
            ):
                current_exposure += float(getattr(trade, "total_size", 0.0) or 0.0)
        proposed_exposure = current_exposure + float(proposed_trade_size or 0.0)
        allowed = proposed_exposure <= max_exposure
        reason = "ok" if allowed else "max_exposure"
        return ExposureCheck(
            allowed=allowed,
            reason=reason,
            current_exposure=current_exposure,
            proposed_exposure=proposed_exposure,
            max_exposure=max_exposure,
        )

    def check_direction_limit(self, side: str, active_trades: Dict[str, Any]) -> Tuple[bool, str]:
        side = str(side).upper()
        for trade in active_trades.values():
            if getattr(trade, "status", None) in (
                TradeStatus.PENDING,
                TradeStatus.CONFIRMED,
                TradeStatus.ADDED,
                TradeStatus.HEDGED,
            ):
                if str(getattr(trade, "side", "")).upper() == side:
                    return False, f"existing_{side}_position"
        return True, "ok"

    def check_soft_stop(self, trade: Any, current_price: float) -> ExitCheck:
        settings = get_settings()
        entry_price = float(getattr(trade, "entry_price", 0.0) or 0.0)
        if entry_price <= 0 or current_price is None:
            return ExitCheck(False, None)
        threshold = float(settings.SOFT_STOP_ADVERSE_MOVE)
        side = str(getattr(trade, "side", "")).upper()
        # UP/BULL loses when price drops; DOWN/BEAR loses when price rises
        # Use absolute price move (not percentage of entry) for fairer stops
        # on binary markets where prices are bounded [0, 1]
        adverse_move = 0.0
        if side in ("UP", "BULL", "BUY_UP"):
            adverse_move = entry_price - current_price  # positive when price drops
        elif side in ("DOWN", "BEAR", "BUY_DOWN"):
            adverse_move = current_price - entry_price  # positive when price rises
        if adverse_move >= threshold:
            return ExitCheck(True, ExitReason.SOFT_STOP)
        return ExitCheck(False, None)

    def check_time_stop(self, trade: Any, current_price: float, bars_elapsed: int) -> ExitCheck:
        settings = get_settings()
        if bars_elapsed is None:
            return ExitCheck(False, None)
        if bars_elapsed >= int(settings.TIME_STOP_BARS):
            return ExitCheck(True, ExitReason.TIME_STOP)
        return ExitCheck(False, None)

    def _recent_closed_trades(self) -> list:
        """Load recent closed trades from paper log(s)."""
        settings = get_settings()
        paths = []
        # Prefer the primary PAPER_LOG_PATH if it exists and is non-empty
        ppath = Path(settings.PAPER_LOG_PATH)
        if ppath.exists() and ppath.stat().st_size > 0:
            paths.append(str(ppath))
        else:
            # include legacy files if primary missing/empty
            paths.extend(sorted(glob("paper_trades_legacy*.jsonl")))
        closed = []
        for p in paths:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        if "realized_pnl" in obj:
                            closed.append(obj)
            except FileNotFoundError:
                continue
        # sort by exit_time if available
        def key_fn(x):
            return x.get("exit_time_utc") or x.get("utc_time") or ""
        closed_sorted = sorted(closed, key=key_fn, reverse=True)
        return closed_sorted

    # ---------------------------
    # Risk state persistence
    # ---------------------------
    def _risk_state_path(self) -> Path:
        settings = get_settings()
        return Path(getattr(settings, "RISK_STATE_PATH", "data/risk_state.json"))

    def _load_risk_state(self) -> None:
        p = self._risk_state_path()
        if not p.exists():
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.kill_switch_until_ts = data.get("kill_switch_until_ts")
            self.kill_switch_reason = data.get("kill_switch_reason")
            self.kill_switch_last_trigger_ts = data.get("kill_switch_last_trigger_ts")
            # ensure telemetry reflects loaded state
            if self.kill_switch_until_ts and time.time() < float(self.kill_switch_until_ts):
                telemetry.set_gauge("market_data_kill_switch_active", 1)
            else:
                telemetry.set_gauge("market_data_kill_switch_active", 0)
        except Exception:
            # ignore load errors
            return

    def _save_risk_state_atomic(self) -> None:
        p = self._risk_state_path()
        d = {
            "kill_switch_until_ts": self.kill_switch_until_ts,
            "kill_switch_reason": self.kill_switch_reason,
            "kill_switch_last_trigger_ts": self.kill_switch_last_trigger_ts,
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".risk_state.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(d, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(p))
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _clear_risk_state(self) -> None:
        self.kill_switch_until_ts = None
        self.kill_switch_reason = None
        self.kill_switch_last_trigger_ts = None
        telemetry.set_gauge("market_data_kill_switch_active", 0)
        p = self._risk_state_path()
        try:
            if p.exists():
                os.remove(p)
        except Exception:
            pass

    def _check_kill_switch(self) -> tuple[bool, str]:
        settings = get_settings()
        if not settings.KILL_SWITCH_ENABLED:
            telemetry.set_gauge("market_data_kill_switch_active", 0)
            return False, "kill_switch_disabled"

        # If a cooldown is already set and active, report active (do not recompute)
        now = time.time()
        if self.kill_switch_until_ts and now < float(self.kill_switch_until_ts):
            telemetry.set_gauge("market_data_kill_switch_active", 1)
            return True, f"kill_switch_active(cooldown_until={self.kill_switch_until_ts})"

        # Otherwise compute from recent closed trades
        closed = self._recent_closed_trades()
        lookback = int(settings.KILL_SWITCH_LOOKBACK_CLOSED)
        recent = closed[:lookback]
        if not recent:
            telemetry.set_gauge("market_data_kill_switch_active", 0)
            return False, "no_recent_trades"
        pnls = [(t.get("realized_pnl") or 0) for t in recent]
        realized_sum = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        winrate = wins / len(pnls) if pnls else 0.0
        if realized_sum <= float(settings.KILL_SWITCH_MAX_REALIZED_LOSS) or winrate < float(settings.KILL_SWITCH_MIN_WINRATE):
            # trigger cooldown
            cooldown = int(settings.KILL_SWITCH_COOLDOWN_SECONDS)
            self.kill_switch_last_trigger_ts = now
            self.kill_switch_until_ts = now + float(cooldown)
            self.kill_switch_reason = "kill_switch_threshold"
            telemetry.set_gauge("market_data_kill_switch_active", 1)
            try:
                self._save_risk_state_atomic()
            except Exception:
                pass
            return True, f"kill_switch_active(sum={realized_sum},winrate={winrate:.2f})"

        telemetry.set_gauge("market_data_kill_switch_active", 0)
        # Clear any stale persisted state if present
        if self.kill_switch_until_ts and now >= float(self.kill_switch_until_ts):
            try:
                self._clear_risk_state()
            except Exception:
                pass
        return False, "ok"

    def check_entry_allowed(
        self,
        token_id: str,
        confidence: int | None,
        market_quality_healthy: bool | None = None,
        adapter: object | None = None,
        now_ts: float | None = None,
        proposed_size: float | None = None,
    ) -> tuple[bool, str, dict]:
        """
        Central gate for allowing new entries.
        Returns (allowed, reason, details)
        """
        settings = get_settings()
        details = {
            "token_id": token_id,
            "confidence": confidence,
            "checked_at": now_ts or time.time(),
        }

        # Kill-switch check
        # First: check cooldown/persistent kill-switch quickly
        settings = get_settings()
        now = now_ts or time.time()
        if getattr(settings, "KILL_SWITCH_ENABLED", False):
            if self.kill_switch_until_ts and now < float(self.kill_switch_until_ts):
                telemetry.set_gauge("market_data_kill_switch_active", 1)
                return False, "kill_switch_cooldown", {**details, "kill_switch_until": self.kill_switch_until_ts}
            # if cooldown expired, clear state
            if self.kill_switch_until_ts and now >= float(self.kill_switch_until_ts):
                try:
                    self._clear_risk_state()
                except Exception:
                    pass

        ks_active, ks_reason = self._check_kill_switch()
        if ks_active:
            # _check_kill_switch handles setting telemetry and persisting state
            return False, "kill_switch", {**details, "kill_switch": ks_reason}

        # Confidence guard
        if confidence is not None and settings.DISABLE_CONFIDENCE_GE and confidence >= int(settings.DISABLE_CONFIDENCE_GE):
            telemetry.incr("market_data_blocked_confidence_total", 1)
            return False, "confidence_disabled", details

        # Market quality flag from upstream (if required)
        if settings.REQUIRE_MARKET_QUALITY_HEALTHY and market_quality_healthy is False:
            telemetry.incr("market_data_blocked_quality_total", 1)
            return False, "market_quality_unhealthy", details

        # Book freshness & top-level checks
        if settings.ENTRY_REQUIRE_FRESH_BOOK:
            orderbook = None
            try:
                if adapter is not None and hasattr(adapter, "get_orderbook"):
                    orderbook = adapter.get_orderbook(token_id)
                else:
                    # try to use Polymarket REST method if adapter not provided
                    try:
                        from agents.polymarket.polymarket import Polymarket
                        pm = Polymarket()
                        orderbook = pm.get_orderbook(token_id)
                    except Exception:
                        orderbook = None
            except Exception:
                orderbook = None

            if not orderbook:
                telemetry.incr("market_data_blocked_stale_total", 1)
                return False, "no_orderbook", details

            # compute age if snapshot has timestamp or use provider stale seconds
            snapshot_ts = getattr(orderbook, "timestamp", None)
            if snapshot_ts:
                age = (time.time() - float(snapshot_ts))
            else:
                age = 0.0
            details["book_age_s"] = age
            if int(settings.ENTRY_MAX_BOOK_AGE_SECONDS) and age > float(settings.ENTRY_MAX_BOOK_AGE_SECONDS):
                telemetry.incr("market_data_blocked_stale_total", 1)
                return False, "stale_orderbook", details

            # top-level prices/sizes
            try:
                bids = getattr(orderbook, "bids", []) or []
                asks = getattr(orderbook, "asks", []) or []
                best_bid = float(bids[0].price) if bids else None
                best_ask = float(asks[0].price) if asks else None
                bid_size = float(bids[0].size) if bids else 0.0
                ask_size = float(asks[0].size) if asks else 0.0
            except Exception:
                best_bid = None
                best_ask = None
                bid_size = 0.0
                ask_size = 0.0

            details.update({"best_bid": best_bid, "best_ask": best_ask, "bid_size": bid_size, "ask_size": ask_size})

            if best_bid is None or best_ask is None:
                telemetry.incr("market_data_blocked_spread_total", 1)
                return False, "missing_top_of_book", details

            spread = best_ask - best_bid
            details["spread"] = spread
            if spread >= float(settings.HARD_REJECT_SPREAD):
                return False, "spread_hard_reject", details
            if spread > float(settings.MAX_ENTRY_SPREAD):
                telemetry.incr("market_data_blocked_spread_total", 1)
                return False, "spread_too_wide", details

            # optional top-level size gate
            if float(settings.MIN_TOP_LEVEL_SIZE) > 0.0:
                if bid_size < float(settings.MIN_TOP_LEVEL_SIZE) or ask_size < float(settings.MIN_TOP_LEVEL_SIZE):
                    telemetry.incr("market_data_blocked_min_size_total", 1)
                    return False, "top_level_size_too_small", details

        # Passed all gates
        return True, "ok", details
