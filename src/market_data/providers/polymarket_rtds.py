from __future__ import annotations
import asyncio
import json
import logging
from typing import List, Optional

import websockets
import time

from ..schema import MarketEvent
from .base import AbstractMarketDataProvider
from ..telemetry import telemetry

logger = logging.getLogger(__name__)


class PolymarketRTDSProvider(AbstractMarketDataProvider):
    """
    RTDS-like provider for Polymarket real-time data streams.
    This provider connects to an RTDS websocket, sends a subscribe message,
    normalizes incoming messages into MarketEvent and calls on_event.
    """

    def __init__(self, url: str, ping_interval: int = 20, pong_timeout: int = 20) -> None:
        super().__init__()
        self.url = url
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._subs: List[str] = []
        self._ws = None
        self._ping_interval = ping_interval
        self._pong_timeout = pong_timeout

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def subscribe(self, token_ids: List[str]) -> None:
        for t in token_ids:
            if t not in self._subs:
                self._subs.append(t)
        # send subscribe if connected (best-effort, compatible with multiple websockets versions)
        try:
            if self._ws and _ws_is_open(self._ws):
                await self._send_subscribe(self._subs)
        except Exception:
            logger.debug("RTDS subscribe skipped (ws not open or send failed)")

    async def unsubscribe(self, token_ids: List[str]) -> None:
        for t in token_ids:
            try:
                self._subs.remove(t)
            except ValueError:
                pass
        try:
            if self._ws and _ws_is_open(self._ws):
                await self._send_subscribe(self._subs)
        except Exception:
            logger.debug("RTDS unsubscribe skipped (ws not open or send failed)")

    async def _send_subscribe(self, subs: List[str]) -> None:
        if not subs:
            return
        msg = {"action": "subscribe", "subscriptions": [{"topic": "crypto_prices", "type": "update", "filters": ",".join(subs)}]}
        try:
            await self._ws.send(json.dumps(msg))
        except Exception:
            logger.debug("RTDS subscribe failed")

    async def _run_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                async with websockets.connect(self.url, ping_interval=self._ping_interval, ping_timeout=self._pong_timeout) as ws:
                    self._ws = ws
                    telemetry.set_gauge("market_data_ws_connected", 1.0)
                    backoff = 1.0
                    if self._subs:
                        await self._send_subscribe(self._subs)
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        telemetry.set_last_msg_ts(time.time())
                        # normalize minimally: expect msg to contain topic/type and payload
                        topic = msg.get("topic") or msg.get("type")
                        payload = msg.get("payload") or msg
                        # Example: payload may include token and price info
                        token = payload.get("token") or payload.get("asset") or payload.get("symbol")
                        if not token:
                            continue
                        ev = MarketEvent(ts=time.time(), type="price_change", token_id=str(token), best_bid=payload.get("best_bid"), best_ask=payload.get("best_ask"), spread_pct=None, data=payload)
                        if self.on_event:
                            try:
                                self.on_event(ev)
                            except Exception:
                                logger.exception("on_event handler failed")
                        telemetry.incr("market_data_messages_total", 1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("RTDS connection error: %s", e)
                telemetry.incr("market_data_reconnect_total", 1)
                telemetry.set_gauge("market_data_ws_connected", 0.0)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
        logger.info("PolymarketRTDSProvider stopped")

    @staticmethod
    def parse_raw_message(msg: dict) -> List[MarketEvent]:
        events: List[MarketEvent] = []
        payload = msg.get("payload") or msg
        token = payload.get("token") or payload.get("asset") or payload.get("symbol")
        if token:
            ev = MarketEvent(
                ts=time.time(),
                type="price_change",
                token_id=str(token),
                best_bid=payload.get("best_bid"),
                best_ask=payload.get("best_ask"),
                spread_pct=None,
                data=payload,
            )
            events.append(ev)
        return events


def _ws_is_open(ws: object) -> bool:
    """
    Compatibility helper for websockets client connection open state.
    Works across versions where .open/.closed or .state exist.
    """
    if ws is None:
        return False
    # EAFP: try legacy .open first
    try:
        return bool(getattr(ws, "open"))
    except Exception:
        pass
    # try .closed attribute (return inverse)
    try:
        closed = getattr(ws, "closed", None)
        if closed is not None:
            return not bool(closed)
    except Exception:
        pass
    # try state.name == "OPEN"
    try:
        state = getattr(ws, "state", None)
        if state is not None:
            name = getattr(state, "name", None)
            return name == "OPEN"
    except Exception:
        pass
    return False


