from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class QualityResult:
    is_healthy: bool
    reason: str
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    spread_pct: Optional[float] = None


class MarketQualityGate:
    def __init__(self, require_best_ask: bool = True, min_ask_size: float | None = None, max_spread: float | None = None):
        self.require_best_ask = require_best_ask
        self.min_ask_size = min_ask_size
        self.max_spread = max_spread

    def _extract_best(self, orderbook: Any) -> tuple[Optional[float], Optional[float], Optional[float]]:
        best_bid = None
        best_ask = None
        best_ask_size = None
        bids = getattr(orderbook, "bids", None) or orderbook.get("bids", []) if isinstance(orderbook, dict) else []
        asks = getattr(orderbook, "asks", None) or orderbook.get("asks", []) if isinstance(orderbook, dict) else []
        if bids:
            b0 = bids[0]
            best_bid = float(getattr(b0, "price", None) or b0.get("price"))
        if asks:
            a0 = asks[0]
            best_ask = float(getattr(a0, "price", None) or a0.get("price"))
            best_ask_size = float(getattr(a0, "size", None) or a0.get("size", 0.0))
        return best_bid, best_ask, best_ask_size

    def check(self, orderbook: Any, token_id: str) -> QualityResult:
        best_bid, best_ask, best_ask_size = self._extract_best(orderbook)
        if self.require_best_ask and not best_ask:
            return QualityResult(False, "missing_best_ask", best_bid, best_ask, None)
        if self.min_ask_size is not None and best_ask_size is not None and best_ask_size < self.min_ask_size:
            return QualityResult(False, "min_ask_size", best_bid, best_ask, None)
        spread_pct = None
        if best_bid and best_ask and best_bid > 0:
            spread_pct = (best_ask - best_bid) / best_bid
            if self.max_spread is not None and spread_pct > self.max_spread:
                return QualityResult(False, "max_spread", best_bid, best_ask, spread_pct)
        return QualityResult(True, "ok", best_bid, best_ask, spread_pct)

