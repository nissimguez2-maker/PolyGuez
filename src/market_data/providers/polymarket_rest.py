from __future__ import annotations
import asyncio
import logging
from typing import List, Optional

from ..schema import MarketEvent, OrderBookSnapshot
from .base import AbstractMarketDataProvider

logger = logging.getLogger(__name__)


class PolymarketRESTProvider(AbstractMarketDataProvider):
    """
    Simple REST fallback provider that uses agents.polymarket.Polymarket.get_orderbook()
    to fetch a snapshot on demand. start()/stop() are no-ops. subscribe() stores
    requested tokens so adapter can trigger a refresh when needed.
    """

    def __init__(self) -> None:
        super().__init__()
        self._subs: set[str] = set()
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def subscribe(self, token_ids: List[str]) -> None:
        for t in token_ids:
            self._subs.add(t)

    async def unsubscribe(self, token_ids: List[str]) -> None:
        for t in token_ids:
            self._subs.discard(t)

    async def refresh(self, token_id: str) -> Optional[MarketEvent]:
        """
        Fetch a fresh orderbook for token_id and return a MarketEvent (book) or None.
        This is sync I/O wrapped for convenience; adapter may call it via run_in_executor.
        """
        try:
            # import here to avoid top-level heavy deps in tests
            from agents.polymarket.polymarket import Polymarket
            p = Polymarket()
            ob = p.get_orderbook(token_id)
            # build raw dict that OrderBookSnapshot can consume
            raw = {"bids": [{"price": x.price, "size": x.size} for x in getattr(ob, "bids", [])],
                   "asks": [{"price": x.price, "size": x.size} for x in getattr(ob, "asks", [])],
                   "timestamp": getattr(ob, "timestamp", None)}
            snapshot = OrderBookSnapshot.from_raw(token_id, raw, source="rest")
            ev = MarketEvent(ts=snapshot.timestamp or 0.0, type="book", token_id=token_id, best_bid=snapshot.best_bid, best_ask=snapshot.best_ask, spread_pct=snapshot.spread_pct, data=raw)
            if self.on_event:
                try:
                    self.on_event(ev)
                except Exception:
                    logger.exception("on_event handler failed in REST refresh")
            return ev
        except Exception:
            logger.exception("REST refresh failed for %s", token_id)
            return None

