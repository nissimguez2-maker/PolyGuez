"""BTC price feed via WebSocket — Binance primary, Coinbase fallback."""

import asyncio
import json
import time
from collections import deque

import websockets

from agents.utils.logger import get_logger, log_event

logger = get_logger("polyguez.btc_feed")


class BTCPriceFeed:
    """Async BTC price streamer with 30-second rolling velocity."""

    def __init__(self, config):
        self._config = config
        # (timestamp, price) tuples
        self._buffer = deque(maxlen=3000)  # ~5 min at ~10 msgs/sec
        self._ws = None
        self._connected = False
        self._source = ""  # "binance" or "coinbase"
        self._task = None
        self._stop = asyncio.Event()
        self._reconnect_delay = 1.0

    # -- public API -----------------------------------------------------------

    @property
    def is_connected(self):
        return self._connected

    @property
    def source(self):
        return self._source

    def is_ready(self):
        """True when buffer spans at least btc_buffer_min_seconds."""
        if len(self._buffer) < 2:
            return False
        span = self._buffer[-1][0] - self._buffer[0][0]
        return span >= self._config.btc_buffer_min_seconds

    def get_price(self):
        """Latest BTC price or 0.0 if buffer empty."""
        if not self._buffer:
            return 0.0
        return self._buffer[-1][1]

    def get_velocity(self):
        """30-second rolling linear slope ($/sec) via least-squares."""
        now = time.time()
        cutoff = now - 30.0
        points = [(t, p) for t, p in self._buffer if t >= cutoff]
        if len(points) < 2:
            return 0.0
        n = len(points)
        t0 = points[0][0]
        xs = [t - t0 for t, _ in points]
        ys = [p for _, p in points]
        sum_x = sum(xs)
        sum_y = sum(ys)
        sum_xy = sum(x * y for x, y in zip(xs, ys))
        sum_xx = sum(x * x for x in xs)
        denom = n * sum_xx - sum_x * sum_x
        if abs(denom) < 1e-12:
            return 0.0
        slope = (n * sum_xy - sum_x * sum_y) / denom
        return slope

    # -- lifecycle ------------------------------------------------------------

    async def start(self):
        """Start streaming in the background."""
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        """Gracefully stop the feed."""
        self._stop.set()
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._connected = False

    # -- internal -------------------------------------------------------------

    async def _run_loop(self):
        while not self._stop.is_set():
            try:
                await self._connect_and_listen()
            except (
                websockets.ConnectionClosed,
                websockets.InvalidURI,
                OSError,
                asyncio.TimeoutError,
            ) as exc:
                self._connected = False
                log_event(logger, "btc_feed_disconnect", f"BTC feed disconnected: {exc}")
                await self._backoff_sleep()
            except asyncio.CancelledError:
                break

    async def _connect_and_listen(self):
        # Try Binance first
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self._config.binance_ws_url),
                timeout=self._config.btc_feed_connect_timeout,
            )
            self._source = "binance"
            self._connected = True
            self._reconnect_delay = 1.0
            log_event(logger, "btc_feed_connected", "Connected to Binance BTC feed")
            await self._listen_binance()
        except (OSError, asyncio.TimeoutError, websockets.InvalidURI) as exc:
            log_event(logger, "btc_feed_fallback", f"Binance failed ({exc}), trying Coinbase")
            await self._connect_coinbase()

    async def _connect_coinbase(self):
        self._ws = await asyncio.wait_for(
            websockets.connect(self._config.coinbase_ws_url),
            timeout=self._config.btc_feed_connect_timeout,
        )
        subscribe = json.dumps({
            "type": "subscribe",
            "channels": [{"name": "matches", "product_ids": ["BTC-USD"]}],
        })
        await self._ws.send(subscribe)
        self._source = "coinbase"
        self._connected = True
        self._reconnect_delay = 1.0
        log_event(logger, "btc_feed_connected", "Connected to Coinbase BTC feed")
        await self._listen_coinbase()

    async def _listen_binance(self):
        async for raw in self._ws:
            if self._stop.is_set():
                break
            try:
                msg = json.loads(raw)
                price = float(msg["p"])
                ts = msg.get("T", time.time() * 1000) / 1000.0
                self._buffer.append((ts, price))
            except (KeyError, ValueError, TypeError):
                continue

    async def _listen_coinbase(self):
        async for raw in self._ws:
            if self._stop.is_set():
                break
            try:
                msg = json.loads(raw)
                if msg.get("type") != "match":
                    continue
                price = float(msg["price"])
                self._buffer.append((time.time(), price))
            except (KeyError, ValueError, TypeError):
                continue

    async def _backoff_sleep(self):
        delay = min(self._reconnect_delay, 30.0)
        log_event(logger, "btc_feed_reconnect", f"Reconnecting in {delay:.1f}s")
        await asyncio.sleep(delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, 30.0)
