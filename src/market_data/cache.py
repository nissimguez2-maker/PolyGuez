from __future__ import annotations
from threading import Lock
from typing import Optional
import time

from .schema import OrderBookSnapshot


class OrderBookCache:
    def __init__(self) -> None:
        self._cache: dict[str, OrderBookSnapshot] = {}
        self._lock = Lock()

    def update(self, snapshot: OrderBookSnapshot) -> None:
        with self._lock:
            self._cache[snapshot.token_id] = snapshot

    def get(self, token_id: str) -> Optional[OrderBookSnapshot]:
        with self._lock:
            return self._cache.get(token_id)

    def get_age(self, token_id: str) -> Optional[float]:
        with self._lock:
            s = self._cache.get(token_id)
            if not s:
                return None
            return time.time() - s.timestamp

    def remove(self, token_id: str) -> None:
        with self._lock:
            self._cache.pop(token_id, None)

