"""Price feed manager — direct Binance primary + RTDS Chainlink.

Two parallel WebSocket connections:
  1. Direct Binance: wss://stream.binance.com:9443/ws/btcusdt@trade
     Individual trade events, ~20-50/sec, parsed from {"p": "67329.99", "T": ms}.
     Downsampled to 1 entry per 100ms to keep buffer manageable.
  2. RTDS Chainlink only: wss://ws-live-data.polymarket.com
     Subscribes to crypto_prices_chainlink, ~1 update/sec.
     Payload: {"data": [{"timestamp": ms, "value": 67234.5}, ...], "symbol": "btc/usd"}

If direct Binance fails, falls back to RTDS Binance (crypto_prices topic).
"""

import asyncio
import json
import time
from collections import deque

import websockets

from agents.utils.logger import get_logger, log_event

logger = get_logger("polyguez.price_feed")

_BINANCE_DIRECT_URL = "wss://stream.binance.com:9443/ws/btcusdt@trade"

_RTDS_PING_INTERVAL = 5.0

# RTDS: Chainlink only
_RTDS_SUBSCRIBE_CHAINLINK = json.dumps({
    "action": "subscribe",
    "subscriptions": [{
        "topic": "crypto_prices_chainlink",
        "type": "*",
        "filters": json.dumps({"symbol": "btc/usd"}),
    }],
})

# RTDS: Binance fallback (only used if direct Binance fails)
_RTDS_SUBSCRIBE_BINANCE_FALLBACK = json.dumps({
    "action": "subscribe",
    "subscriptions": [{
        "topic": "crypto_prices",
        "type": "*",
        "filters": json.dumps({"symbol": "btcusdt"}),
    }],
})


class PriceFeedManager:
    """Async dual-price streamer: direct Binance + RTDS Chainlink."""

    def __init__(self, config):
        self._config = config
        # Binance buffer: (timestamp, price) — downsampled to ~10/sec
        self._binance_buffer = deque(maxlen=3000)
        # Chainlink buffer: (timestamp, price)
        self._chainlink_buffer = deque(maxlen=3000)
        # Gap tracking: (timestamp, gap) for narrowing/widening detection
        self._gap_buffer = deque(maxlen=60)

        self._binance_ws = None
        self._rtds_ws = None
        self._binance_connected = False
        self._rtds_connected = False
        self._binance_source = ""  # "binance-direct" or "rtds-fallback"
        self._binance_task = None
        self._rtds_task = None
        self._rtds_ping_task = None
        self._stop = asyncio.Event()
        self._reconnect_delay_binance = 1.0
        self._reconnect_delay_rtds = 1.0

        # Downsampling: only buffer 1 price per 100ms window
        self._last_binance_buffer_ts = 0.0

        # Feed stats for latency logging
        self._binance_msg_count = 0
        self._chainlink_msg_count = 0
        self._last_binance_msg_time = 0.0
        self._last_chainlink_msg_time = 0.0
        self._last_rtds_msg_time = 0.0
        self._last_stats_log = 0.0
        self._binance_msg_count_window = 0
        self._chainlink_msg_count_window = 0
        self._stats_window_start = 0.0

    # -- Public API: Binance -------------------------------------------------

    @property
    def is_connected(self):
        return self._binance_connected or self._rtds_connected

    @property
    def source(self):
        return self._binance_source or ("rtds" if self._rtds_connected else "")

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
        if len(recent) < 10:
            old_avg = abs(recent[0][1])
            new_avg = abs(recent[-1][1])
        else:
            old_avg = sum(abs(g) for _, g in recent[-10:-5]) / 5
            new_avg = sum(abs(g) for _, g in recent[-5:]) / 5
        return "narrowing" if new_avg < old_avg else "widening"

    # -- Lifecycle -----------------------------------------------------------

    async def start(self):
        """Start both feeds in parallel as separate tasks."""
        self._stop.clear()
        self._stats_window_start = time.time()
        self._binance_task = asyncio.create_task(self._binance_loop())
        self._rtds_task = asyncio.create_task(self._rtds_loop())

    async def stop(self):
        """Gracefully stop all feeds."""
        self._stop.set()
        if self._rtds_ping_task:
            self._rtds_ping_task.cancel()
        for ws in (self._binance_ws, self._rtds_ws):
            if ws:
                try:
                    await ws.close()
                except Exception:
                    pass
        for task in (self._binance_task, self._rtds_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._binance_connected = False
        self._rtds_connected = False

    # -- Internal: Direct Binance (primary) ---------------------------------

    async def _binance_loop(self):
        """Reconnect loop for direct Binance WebSocket."""
        while not self._stop.is_set():
            try:
                await self._connect_binance_direct()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._binance_connected = False
                log_event(logger, "binance_disconnect",
                    f"Binance direct failed: {type(exc).__name__}: {exc}",
                    level=40)
                # Fall back to RTDS Binance if direct fails
                try:
                    await self._connect_binance_via_rtds()
                except Exception as fb_exc:
                    log_event(logger, "binance_fallback_fail",
                        f"RTDS Binance fallback also failed: {type(fb_exc).__name__}: {fb_exc}",
                        level=40)
                delay = min(self._reconnect_delay_binance, 30.0)
                log_event(logger, "binance_reconnect", f"Reconnecting Binance in {delay:.1f}s")
                await asyncio.sleep(delay)
                self._reconnect_delay_binance = min(self._reconnect_delay_binance * 2, 30.0)

    async def _connect_binance_direct(self):
        """Connect directly to Binance trade stream."""
        url = self._config.binance_ws_url
        self._binance_ws = await asyncio.wait_for(
            websockets.connect(url),
            timeout=self._config.btc_feed_connect_timeout,
        )
        self._binance_source = "binance-direct"
        self._binance_connected = True
        self._reconnect_delay_binance = 1.0
        log_event(logger, "binance_connected", f"Connected to direct Binance: {url}")

        async for raw in self._binance_ws:
            if self._stop.is_set():
                break
            try:
                msg = json.loads(raw)
                price = float(msg["p"])
                ts = msg.get("T", time.time() * 1000) / 1000.0
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue

            self._binance_msg_count += 1
            self._binance_msg_count_window += 1
            self._last_binance_msg_time = time.time()

            # Downsample: only buffer 1 price per 100ms
            if ts - self._last_binance_buffer_ts >= 0.1:
                self._binance_buffer.append((ts, price))
                self._last_binance_buffer_ts = ts
                self._update_gap()

            self._maybe_log_stats()

    async def _connect_binance_via_rtds(self):
        """Fallback: get Binance prices from RTDS relay."""
        ws = await asyncio.wait_for(
            websockets.connect(self._config.rtds_ws_url),
            timeout=self._config.btc_feed_connect_timeout,
        )
        self._binance_source = "rtds-fallback"
        self._binance_connected = True
        log_event(logger, "binance_fallback", "Using RTDS for Binance prices (fallback)")

        await ws.send(_RTDS_SUBSCRIBE_BINANCE_FALLBACK)

        async for raw in ws:
            if self._stop.is_set():
                break
            if raw == "PONG":
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            payload = msg.get("payload")
            if not payload or not isinstance(payload, dict):
                continue

            symbol = (payload.get("symbol") or "").lower()
            if symbol != "btcusdt":
                continue

            now = time.time()
            data_arr = payload.get("data")
            if isinstance(data_arr, list) and data_arr:
                for entry in data_arr:
                    try:
                        price = float(entry["value"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    if price <= 0:
                        continue
                    ts = entry.get("timestamp", now)
                    if isinstance(ts, (int, float)) and ts > 1e12:
                        ts = ts / 1000.0
                    self._binance_buffer.append((ts, price))
                self._binance_msg_count += 1
                self._binance_msg_count_window += 1
                self._last_binance_msg_time = time.time()
                self._update_gap()
        await ws.close()

    # -- Internal: RTDS Chainlink -------------------------------------------

    async def _rtds_loop(self):
        """Reconnect loop for RTDS Chainlink WebSocket."""
        while not self._stop.is_set():
            try:
                await self._connect_rtds_chainlink()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._rtds_connected = False
                log_event(logger, "rtds_disconnect",
                    f"RTDS Chainlink failed: {type(exc).__name__}: {exc}",
                    level=40)
                delay = min(self._reconnect_delay_rtds, 30.0)
                log_event(logger, "rtds_reconnect", f"Reconnecting RTDS in {delay:.1f}s")
                await asyncio.sleep(delay)
                self._reconnect_delay_rtds = min(self._reconnect_delay_rtds * 2, 30.0)

    async def _connect_rtds_chainlink(self):
        """Connect to RTDS and subscribe to Chainlink only."""
        self._rtds_ws = await asyncio.wait_for(
            websockets.connect(self._config.rtds_ws_url),
            timeout=self._config.btc_feed_connect_timeout,
        )
        self._rtds_connected = True
        self._reconnect_delay_rtds = 1.0
        log_event(logger, "rtds_connected", "Connected to RTDS for Chainlink")

        await self._rtds_ws.send(_RTDS_SUBSCRIBE_CHAINLINK)
        log_event(logger, "rtds_subscribe", f"Chainlink sub: {_RTDS_SUBSCRIBE_CHAINLINK}")

        # Start keepalive ping
        self._rtds_ping_task = asyncio.create_task(self._rtds_ping_loop())

        async for raw in self._rtds_ws:
            if self._stop.is_set():
                break

            self._last_rtds_msg_time = time.time()

            if raw == "PONG":
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            payload = msg.get("payload")
            if not payload or not isinstance(payload, dict):
                continue

            now = time.time()
            data_arr = payload.get("data")
            if isinstance(data_arr, list) and data_arr:
                for entry in data_arr:
                    try:
                        price = float(entry["value"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    if price <= 0:
                        continue
                    ts = entry.get("timestamp", now)
                    if isinstance(ts, (int, float)) and ts > 1e12:
                        ts = ts / 1000.0
                    self._chainlink_buffer.append((ts, price))
                self._chainlink_msg_count += 1
                self._chainlink_msg_count_window += 1
                self._last_chainlink_msg_time = time.time()
                self._update_gap()
            else:
                # Flat payload fallback
                for key in ("value", "price"):
                    if key in payload:
                        try:
                            price = float(payload[key])
                            ts = payload.get("timestamp", now)
                            if isinstance(ts, (int, float)) and ts > 1e12:
                                ts = ts / 1000.0
                            self._chainlink_buffer.append((ts, price))
                            self._chainlink_msg_count += 1
                            self._chainlink_msg_count_window += 1
                            self._last_chainlink_msg_time = time.time()
                            self._update_gap()
                            break
                        except (ValueError, TypeError):
                            continue

    async def _rtds_ping_loop(self):
        """Send PING every 5 seconds and force reconnect if stale."""
        try:
            while not self._stop.is_set():
                await asyncio.sleep(_RTDS_PING_INTERVAL)
                if self._rtds_ws and self._rtds_ws.open:
                    await self._rtds_ws.send("PING")

                    # Force reconnect if no message in 15s
                    if self._last_rtds_msg_time > 0:
                        silence = time.time() - self._last_rtds_msg_time
                        if silence > 15.0:
                            log_event(logger, "rtds_stale",
                                f"No RTDS message for {silence:.1f}s — forcing reconnect",
                                level=40)
                            await self._rtds_ws.close()
                            break
        except asyncio.CancelledError:
            pass

    # -- Shared helpers -----------------------------------------------------

    def _update_gap(self):
        """Record the current Binance-Chainlink gap for trend tracking."""
        gap = self.get_binance_chainlink_gap()
        if gap != 0.0:
            self._gap_buffer.append((time.time(), gap))

    def _maybe_log_stats(self):
        """Log feed latency stats every 10 seconds."""
        now = time.time()
        if now - self._last_stats_log < 10.0:
            return
        self._last_stats_log = now

        elapsed = now - self._stats_window_start if self._stats_window_start else 1.0
        if elapsed < 1.0:
            elapsed = 1.0
        b_rate = self._binance_msg_count_window / elapsed
        c_rate = self._chainlink_msg_count_window / elapsed

        b_ago = (now - self._last_binance_msg_time) * 1000 if self._last_binance_msg_time else -1
        c_ago = (now - self._last_chainlink_msg_time) * 1000 if self._last_chainlink_msg_time else -1

        gap = self.get_binance_chainlink_gap()

        log_event(logger, "feed_stats", (
            f"Binance: {b_rate:.1f} msgs/sec, last={b_ago:.0f}ms ago | "
            f"Chainlink: {c_rate:.1f} msgs/sec, last={c_ago:.0f}ms ago | "
            f"Gap: ${gap:.2f} | "
            f"Buf: B={len(self._binance_buffer)} C={len(self._chainlink_buffer)} | "
            f"Src: {self._binance_source}"
        ))

        # Reset window
        self._binance_msg_count_window = 0
        self._chainlink_msg_count_window = 0
        self._stats_window_start = now
