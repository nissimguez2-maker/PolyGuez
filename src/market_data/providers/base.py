from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable, List

from ..schema import MarketEvent


class AbstractMarketDataProvider(ABC):
    def __init__(self) -> None:
        self.on_event: Callable[[MarketEvent], None] | None = None

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @abstractmethod
    async def subscribe(self, token_ids: List[str]) -> None:
        ...

    @abstractmethod
    async def unsubscribe(self, token_ids: List[str]) -> None:
        ...

