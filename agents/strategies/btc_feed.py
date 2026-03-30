"""Price feed manager — Polymarket RTDS primary, direct Binance fallback.

RTDS provides both Binance spot and Chainlink oracle prices via WebSocket.
Binance prices arrive on topic "crypto_prices", Chainlink on
"crypto_prices_chainlink".  Each message is a flat object:
  {"topic": ..., "type": "update", "timestamp": ...,
   "payload": {"symbol": "btcusdt", "timestamp": ..., "value": 67234.5}}
"""

import asyncio
import json
import time
from collections import deque

import websockets

from agents.utils.logger import get_logger, log_event

logger = get_logger("polyguez.price_feed")

# RTDS protocol constants
_RTDS_PING_INTERVAL = 5.0

# Binance: topic "crypto_prices", filters is a plain comma-separated string
_RTDS_SUBSCRIBE_BINANCE = json.dumps({
    "action": "subscribe",
    "subscriptions": [{
        "topic": "crypto_prices",
        "type": "update",
        "filters": "btcusdt",
    }],
})

# Chainlink: topic "crypto_prices_chainlink", filters is a JSON-encoded object
_RTDS_SUBSCRIBE_CHAINLINK = json.dumps({
    "action": "subscribe",
    "subscriptions": [{
        "topic": "crypto_prices_chainlink",
        "type": "*",
        "filters": json.dumps({"symbol": "btc/usd"}),
    }],
})


class PriceFeedManager:
    """Async dual-price streamer: Binance spot + Chainlink oracle via RTDS."""

    def __init__(self, config):
        self._config = config
        # Binance buffer: (timestamp, price)
        self._binance_buffer = deque(maxlen=3000)
        # Chainlink buffer: (timestamp, price)
        self._chainlink_buffer = deque(maxlen=3000)
        # Gap tracking: (timestamp, gap) for narrowing/widening detection
        self._gap_buffer = deque(maxlen=60)

        self._ws = None
        self._connected = False
        self._source = ""  # "rtds" or "binance-direct"
        self._task = None
        self._ping_task = None
        self._stop = asyncio.Event()
        self._reconnect_delay = 1.0
        self._rtds_msg_count = 0
        self._last_buffer_log = 0.0

    # -- Public API: Binance -------------------------------------------------

    @property
    def is_connected(self):
        return self._connected

    @property
    def source(self):
        return self._source

    def is_ready(self):
        """True when Binance buffer spans >= btc_buffer_min_seconds."""
        if len(self._binance_buffer) < 2:
            return False
        span = self._binance_buffer[-1][0] - self._binance_buffer[0][0]
        return span >= self._config.btc_buffer_min_seconds

    def get_price(self):
        """Latest Binance BTC price."""
        if not self._binance_buffer:
            return 0.0
        return self._binance_buffer[-1][1]

    def get_velocity(self):
        """30-second rolling linear slope ($/sec) of Binance prices."""
        now = time.time()
        cutoff = now - 30.0
        points = [(t, p) for t, p in self._binance_buffer if t >= cutoff]
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
        return (n * sum_xy - sum_x * sum_y) / denom

    # -- Public API: Chainlink -----------------------------------------------

    def get_chainlink_price(self):
        """Latest Chainlink oracle price."""
        if not self._chainlink_buffer:
            return 0.0
        return self._chainlink_buffer[-1][1]

    def is_chainlink_ready(self):
        """True when we have at least one Chainlink price."""
        return len(self._chainlink_buffer) > 0

    def get_binance_chainlink_gap(self):
        """Binance price minus Chainlink price (positive = Binance ahead)."""
        bp = self.get_price()
        cp = self.get_chainlink_price()
        if bp == 0.0 or cp == 0.0:
            return 0.0
        return bp - cp

    def get_gap_direction(self):
        """Whether the Binance-Chainlink gap is 'narrowing' or 'widening'."""
        if len(self._gap_buffer) < 2:
            return "unknown"
        recent = list(self._gap_buffer)
        # Compare last 5 gap values vs previous 5
        if len(recent) < 10:
            old_avg = abs(recent[0][1])
            new_avg = abs(recent[-1][1])
        else:
            old_avg = sum(abs(g) for _, g in recent[-10:-5]) / 5
            new_avg = sum(abs(g) for _, g in recent[-5:]) / 5
        return "narrowing" if new_avg < old_avg else "widening"

    # -- Lifecycle -----------------------------------------------------------

    async def start(self):
        """Start streaming in the background."""
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        """Gracefully stop all feeds."""
        self._stop.set()
        if self._ping_task:
            self._ping_task.cancel()
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._connected = False

    # -- Internal: RTDS (primary) -------------------------------------------

    async def _run_loop(self):
        while not self._stop.is_set():
            try:
                await self._connect_rtds()
            except (
                websockets.ConnectionClosed,
                websockets.InvalidURI,
                OSError,
                asyncio.TimeoutError,
            ) as exc:
                self._connected = False
                rtds_url = self._config.rtds_ws_url
                log_event(logger, "feed_disconnect",
                    f"RTDS connection failed: {type(exc).__name__}: {exc} "
                    f"(url={rtds_url}), trying Binance fallback",
                    level=40)
                try:
                    await self._connect_binance_direct()
                except Exception as fb_exc:
                    binance_url = self._config.binance_ws_url
                    log_event(logger, "feed_disconnect",
                        f"Binance fallback also failed: {type(fb_exc).__name__}: {fb_exc} "
                        f"(url={binance_url})",
                        level=40)
                    await self._backoff_sleep()
            except Exception as exc:
                self._connected = False
                log_event(logger, "feed_error",
                    f"Unexpected feed error: {type(exc).__name__}: {exc}",
                    level=40)
                await self._backoff_sleep()
            except asyncio.CancelledError:
                break

    async def _connect_rtds(self):
        """Connect to Polymarket RTDS and subscribe to both feeds."""
        self._ws = await asyncio.wait_for(
            websockets.connect(self._config.rtds_ws_url),
            timeout=self._config.btc_feed_connect_timeout,
        )
        self._source = "rtds"
        self._connected = True
        self._reconnect_delay = 1.0
        log_event(logger, "feed_connected", "Connected to Polymarket RTDS")

        # Subscribe: Binance on crypto_prices, Chainlink on crypto_prices_chainlink
        await self._ws.send(_RTDS_SUBSCRIBE_BINANCE)
        log_event(logger, "rtds_subscribe", f"Binance sub: {_RTDS_SUBSCRIBE_BINANCE}")
        await self._ws.send(_RTDS_SUBSCRIBE_CHAINLINK)
        log_event(logger, "rtds_subscribe", f"Chainlink sub: {_RTDS_SUBSCRIBE_CHAINLINK}")
        self._rtds_msg_count = 0

        # Start keepalive ping
        self._ping_task = asyncio.create_task(self._rtds_ping_loop())

        await self._listen_rtds()

    async def _rtds_ping_loop(self):
        """Send PING every 5 seconds to keep RTDS connection alive."""
        try:
            while not self._stop.is_set():
                await asyncio.sleep(_RTDS_PING_INTERVAL)
                if self._ws and self._ws.open:
                    await self._ws.send("PING")
        except asyncio.CancelledError:
            pass

    async def _listen_rtds(self):
        """Listen to RTDS messages and route to appropriate buffer.

        RTDS message format (per Polymarket docs):
          {
            "topic": "crypto_prices",
            "type": "update",
            "timestamp": 1753314088421,
            "payload": {"symbol": "btcusdt", "timestamp": 1753314088395, "value": 67234.50}
          }
        Chainlink uses topic "crypto_prices_chainlink" with same payload shape.
        """
        async for raw in self._ws:
            if self._stop.is_set():
                break
            if raw == "PONG":
                continue

            self._rtds_msg_count += 1

            # Log first 10 raw messages
            if self._rtds_msg_count <= 10:
                log_event(logger, "rtds_raw_msg", f"[MSG #{self._rtds_msg_count}] {raw[:500]}")

            # Periodic buffer status (every 10s)
            now = time.time()
            if now - self._last_buffer_log >= 10.0:
                self._last_buffer_log = now
                last5_b = [(round(p, 2),) for _, p in list(self._binance_buffer)[-5:]]
                last5_c = [(round(p, 2),) for _, p in list(self._chainlink_buffer)[-5:]]
                log_event(logger, "buffer_status", (
                    f"Binance={len(self._binance_buffer)} Chainlink={len(self._chainlink_buffer)} "
                    f"msgs={self._rtds_msg_count} vel={self.get_velocity():.6f}"
                ), {"binance_last5": last5_b, "chainlink_last5": last5_c})

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            topic = msg.get("topic", "")
            payload = msg.get("payload")

            # Payload can be a dict (single update) or potentially absent
            if not payload or not isinstance(payload, dict):
                # Some messages (ack, error, etc.) have no payload
                if self._rtds_msg_count <= 10:
                    log_event(logger, "rtds_no_payload", f"No payload in msg: {str(msg)[:300]}")
                continue

            symbol = (payload.get("symbol") or "").lower()
            price = None
            for key in ("value", "price", "p"):
                if key in payload:
                    try:
                        price = float(payload[key])
                        break
                    except (ValueError, TypeError):
                        continue

            if not price:
                if self._rtds_msg_count <= 10:
                    log_event(logger, "rtds_no_price", f"No price in payload: {payload}")
                continue

            ts = payload.get("timestamp") or now
            if isinstance(ts, (int, float)) and ts > 1e12:
                ts = ts / 1000.0  # milliseconds → seconds

            # Route by topic first, then symbol as fallback
            if topic == "crypto_prices_chainlink" or symbol in ("btc/usd", "btcusd"):
                self._chainlink_buffer.append((ts, price))
                self._update_gap()
            elif topic == "crypto_prices" or symbol == "btcusdt":
                self._binance_buffer.append((ts, price))
                self._update_gap()
            else:
                if self._rtds_msg_count <= 10:
                    log_event(logger, "rtds_unrouted", f"topic={topic} symbol={symbol}: {payload}")

    def _update_gap(self):
        """Record the current Binance-Chainlink gap for trend tracking."""
        gap = self.get_binance_chainlink_gap()
        if gap != 0.0:
            self._gap_buffer.append((time.time(), gap))

    # -- Internal: Direct Binance (fallback) --------------------------------

    async def _connect_binance_direct(self):
        """Fallback: connect directly to Binance WebSocket."""
        self._ws = await asyncio.wait_for(
            websockets.connect(self._config.binance_ws_url),
            timeout=self._config.btc_feed_connect_timeout,
        )
        self._source = "binance-direct"
        self._connected = True
        self._reconnect_delay = 1.0
        log_event(logger, "feed_connected", "Connected to Binance WS (fallback, no Chainlink)")
        await self._listen_binance()

    async def _listen_binance(self):
        """Listen to direct Binance trade stream."""
        async for raw in self._ws:
            if self._stop.is_set():
                break
            try:
                msg = json.loads(raw)
                price = float(msg["p"])
                ts = msg.get("T", time.time() * 1000) / 1000.0
                self._binance_buffer.append((ts, price))
            except (KeyError, ValueError, TypeError):
                continue

    # -- Shared helpers -----------------------------------------------------

    async def _backoff_sleep(self):
        delay = min(self._reconnect_delay, 30.0)
        log_event(logger, "feed_reconnect", f"Reconnecting in {delay:.1f}s")
        await asyncio.sleep(delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, 30.0)
