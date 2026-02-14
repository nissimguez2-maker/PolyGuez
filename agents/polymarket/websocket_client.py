from dataclasses import dataclass
from typing import Optional


@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBookUpdate:
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]


class PolymarketWebSocketClient:
    """Placeholder WebSocket client. Not implemented in this repo."""

    def __init__(self, *args, **kwargs) -> None:
        self.connected = False

    def connect(self) -> None:
        raise NotImplementedError("WebSocket client not implemented")

    def close(self) -> None:
        self.connected = False
