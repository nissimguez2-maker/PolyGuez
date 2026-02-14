from __future__ import annotations
import asyncio
from typing import Dict, Any, Callable, Optional
import logging

from .schema import MarketEvent

logger = logging.getLogger(__name__)
from .telemetry import telemetry


class AsyncEventBus:
    def __init__(self, queue_maxsize: int = 1000) -> None:
        self._subs: Dict[str, asyncio.Queue] = {}
        self._maxsize = queue_maxsize

    def subscribe(self, name: str) -> asyncio.Queue:
        if name in self._subs:
            return self._subs[name]
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subs[name] = q
        logger.info("EventBus: subscriber registered %s", name)
        return q

    def unsubscribe(self, name: str) -> None:
        q = self._subs.pop(name, None)
        if q:
            logger.info("EventBus: subscriber removed %s", name)

    async def publish(self, event: MarketEvent) -> None:
        # Fan-out to subscribers; on full queue drop oldest item then enqueue
        for name, q in list(self._subs.items()):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    _ = q.get_nowait()  # drop oldest
                except Exception:
                    pass
                try:
                    q.put_nowait(event)
                except Exception:
                    logger.warning("EventBus: failed to enqueue for %s", name)
                # track drop
                telemetry.incr("market_data_eventbus_dropped_total", 1)

