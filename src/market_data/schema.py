from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import time


@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBookSnapshot:
    token_id: str
    timestamp: float
    best_bid: Optional[float]
    best_ask: Optional[float]
    best_bid_size: Optional[float]
    best_ask_size: Optional[float]
    spread: Optional[float]
    spread_pct: Optional[float]
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]
    source: str = "unknown"

    @classmethod
    def from_raw(cls, token_id: str, raw: Dict[str, Any], source: str = "ws") -> "OrderBookSnapshot":
        # raw expected to contain bids/asks lists of {price,size} or similar
        bids_raw = raw.get("bids") or raw.get("buys") or []
        asks_raw = raw.get("asks") or raw.get("sells") or []

        def parse_levels(arr):
            levels = []
            for lvl in arr:
                try:
                    price = float(lvl.get("price") if isinstance(lvl, dict) else lvl[0])
                    size = float(lvl.get("size") if isinstance(lvl, dict) else lvl[1])
                except Exception:
                    continue
                levels.append(OrderBookLevel(price=price, size=size))
            return levels

        bids = parse_levels(bids_raw)
        asks = parse_levels(asks_raw)

        best_bid = bids[0].price if bids else None
        best_bid_size = bids[0].size if bids else None
        best_ask = asks[0].price if asks else None
        best_ask_size = asks[0].size if asks else None

        spread = None
        spread_pct = None
        if best_bid is not None and best_ask is not None:
            spread = abs(best_ask - best_bid)
            try:
                spread_pct = spread / best_ask if best_ask != 0 else None
            except Exception:
                spread_pct = None

        return cls(
            token_id=token_id,
            timestamp=float(time.time()),
            best_bid=best_bid,
            best_ask=best_ask,
            best_bid_size=best_bid_size,
            best_ask_size=best_ask_size,
            spread=spread,
            spread_pct=spread_pct,
            bids=bids,
            asks=asks,
            source=source,
        )


@dataclass
class MarketEvent:
    ts: float
    type: str
    token_id: str
    best_bid: Optional[float]
    best_ask: Optional[float]
    spread_pct: Optional[float]
    data: Dict[str, Any]

