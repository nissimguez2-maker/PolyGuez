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
        bids_raw = raw.get("bids") or raw.get("buys") or []
        asks_raw = raw.get("asks") or raw.get("sells") or []

        def parse_levels(arr: Any) -> List[OrderBookLevel]:
            levels: List[OrderBookLevel] = []
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

        # 1) prefer explicit top-of-book fields if present
        def fget(key: str):
            try:
                v = raw.get(key)
                return None if v is None else float(v)
            except Exception:
                return None

        raw_best_bid = fget("best_bid")
        raw_best_ask = fget("best_ask")
        raw_best_bid_size = fget("best_bid_size")
        raw_best_ask_size = fget("best_ask_size")

        # 2) fallback to levels
        best_bid = raw_best_bid if raw_best_bid is not None else (bids[0].price if bids else None)
        best_ask = raw_best_ask if raw_best_ask is not None else (asks[0].price if asks else None)
        best_bid_size = raw_best_bid_size if raw_best_bid_size is not None else (bids[0].size if bids else None)
        best_ask_size = raw_best_ask_size if raw_best_ask_size is not None else (asks[0].size if asks else None)

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

