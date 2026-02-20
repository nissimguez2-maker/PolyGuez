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

    # 1) normal orderbook levels
    bids = getattr(orderbook, "bids", None) or (orderbook.get("bids", []) if isinstance(orderbook, dict) else [])
    asks = getattr(orderbook, "asks", None) or (orderbook.get("asks", []) if isinstance(orderbook, dict) else [])

    if bids:
        b0 = bids[0]
        v = getattr(b0, "price", None) or (b0.get("price") if isinstance(b0, dict) else None)
        if v is not None:
            best_bid = float(v)

    if asks:
        a0 = asks[0]
        v = getattr(a0, "price", None) or (a0.get("price") if isinstance(a0, dict) else None)
        if v is not None:
            best_ask = float(v)

        sz = getattr(a0, "size", None) or (a0.get("size") if isinstance(a0, dict) else None)
        if sz is not None:
            best_ask_size = float(sz)

    # 2) fallback: top-of-book fields (from quote/price_change enrichment)
    if best_bid is None:
        v = getattr(orderbook, "best_bid", None)
        if v is None and isinstance(orderbook, dict):
            v = orderbook.get("best_bid")
        if v is not None:
            best_bid = float(v)

    if best_ask is None:
        v = getattr(orderbook, "best_ask", None)
        if v is None and isinstance(orderbook, dict):
            v = orderbook.get("best_ask")
        if v is not None:
            best_ask = float(v)

    if best_ask_size is None:
        v = getattr(orderbook, "best_ask_size", None)
        if v is None and isinstance(orderbook, dict):
            v = orderbook.get("best_ask_size")
        if v is not None:
            best_ask_size = float(v)

    return best_bid, best_ask, best_ask_size

    best_ask = None
    best_ask_size = None

    # 1) normal orderbook levels (bids/asks)
    bids = getattr(orderbook, "bids", None) or (orderbook.get("bids", []) if isinstance(orderbook, dict) else [])
    asks = getattr(orderbook, "asks", None) or (orderbook.get("asks", []) if isinstance(orderbook, dict) else [])

    if bids:
        b0 = bids[0]
        best_bid = float(getattr(b0, "price", None) or (b0.get("price") if isinstance(b0, dict) else None))

    if asks:
        a0 = asks[0]
        best_ask = float(getattr(a0, "price", None) or (a0.get("price") if isinstance(a0, dict) else None))
        best_ask_size = float(getattr(a0, "size", None) or (a0.get("size", 0.0) if isinstance(a0, dict) else 0.0))

    # 2) fallback: top-of-book fields (best_bid/best_ask)
    if best_bid is None:
        v = getattr(orderbook, "best_bid", None)
        if v is None and isinstance(orderbook, dict):
            v = orderbook.get("best_bid")
        if v is not None:
            best_bid = float(v)

    if best_ask is None:
        v = getattr(orderbook, "best_ask", None)
        if v is None and isinstance(orderbook, dict):
            v = orderbook.get("best_ask")
        if v is not None:
            best_ask = float(v)

    if best_ask_size is None:
        v = getattr(orderbook, "best_ask_size", None)
        if v is None and isinstance(orderbook, dict):
            v = orderbook.get("best_ask_size")
        if v is not None:
            best_ask_size = float(v)

    return best_bid, best_ask, best_ask_size