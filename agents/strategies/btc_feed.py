"""Price feed manager — direct Binance + RTDS Chainlink + on-chain fallback."""

import asyncio
import json
import time
from collections import deque

import websockets

from agents.utils.logger import get_logger, log_event

logger = get_logger("polyguez.price_feed")

_RTDS_PING_INTERVAL = 5.0

_RTDS_SUBSCRIBE_CHAINLINK = json.dumps({
    "action": "subscribe",
    "subscriptions": [{"topic": "crypto_prices_chainlink", "type": "*", "filters": json.dumps({"symbol": "btc/usd"})}],
})

_RTDS_SUBSCRIBE_BINANCE_FALLBACK = json.dumps({
    "action": "subscribe",
    "subscriptions": [{"topic": "crypto_prices", "type": "*", "filters": json.dumps({"symbol": "btcusdt"})}],
})


class PriceFeedManager:
    def __init__(self, config):
        self._config = config
        self._binance_buffer = deque(maxlen=3000)
        self._chainlink_buffer = deque(maxlen=3000)
        self._gap_buffer = deque(maxlen=60)
        self._binance_ws = None
        self._rtds_ws = None
        self._binance_connected = False
        self._rtds_connected = False
        self._binance_source = ""
        self._chainlink_source = ""
        self._binance_task = None
        self._rtds_task = None
        self._rtds_ping_task = None
        self._chainlink_onchain_task = None
        self._stop = asyncio.Event()
        self._reconnect_delay_binance = 1.0
        self._reconnect_delay_rtds = 1.0
        self._last_binance_buffer_ts = 0.0
        self._binance_msg_count = 0
        self._chainlink_msg_count = 0
        self._last_binance_msg_time = 0.0
        self._last_chainlink_msg_time = 0.0
        self._last_rtds_msg_time = 0.0
        self._last_stats_log = 0.0
        self._binance_msg_count_window = 0
        self._chainlink_msg_count_window = 0
        self._stats_window_start = 0.0
        self._onchain_feed = None
        self._onchain_active = False

    @property
    def is_connected(self):
        return self._binance_connected or self._rtds_connected

    @property
    def source(self):
        return self._binance_source or ("rtds" if self._rtds_connected else "")

    @property
    def chainlink_source(self):
        return self._chainlink_source

    @property
    def rtds_msg_age(self):
        """Seconds since last RTDS message, or -1 if never received."""
        if self._last_rtds_msg_time <= 0:
            return -1.0
        return time.time() - self._last_rtds_msg_time

    @property
    def binance_msg_age(self):
        """Seconds since last Binance message, or -1 if never received."""
        if self._last_binance_msg_time <= 0:
            return -1.0
        return time.time() - self._last_binance_msg_time

    def is_ready(self):
        if len(self._binance_buffer) < 2:
            return False
        return (self._binance_buffer[-1][0] - self._binance_buffer[0][0]) >= self._config.btc_buffer_min_seconds

    def get_price(self):
        return self._binance_buffer[-1][1] if self._binance_buffer else 0.0

    def get_velocity(self):
        vel, src = self._compute_velocity_with_source()
        self._velocity_source = src
        return vel

    @property
    def velocity_source(self):
        return getattr(self, '_velocity_source', 'none')

    def _compute_velocity_with_source(self):
        """Compute velocity from Binance buffer, falling back to Chainlink if stale."""
        now = time.time()
        # Try Binance first (primary, higher frequency)
        points = [(t, p) for t, p in self._binance_buffer if t >= now - 30.0]
        if len(points) >= 2:
            return self._linreg_velocity(points), "binance"
        # Fallback to Chainlink buffer if Binance is stale (>10s)
        if self._last_binance_msg_time > 0 and now - self._last_binance_msg_time > 10.0:
            cl_points = [(t, p) for t, p in self._chainlink_buffer if t >= now - 30.0]
            if len(cl_points) >= 2:
                return self._linreg_velocity(cl_points), "chainlink-fallback"
        return 0.0, "none"

    @staticmethod
    def _linreg_velocity(points):
        """Linear regression slope over (timestamp, price) points."""
        n = len(points)
        t0 = points[0][0]
        xs = [t - t0 for t, _ in points]
        ys = [p for _, p in points]
        sum_x, sum_y = sum(xs), sum(ys)
        sum_xy = sum(x * y for x, y in zip(xs, ys))
        sum_xx = sum(x * x for x in xs)
        denom = n * sum_xx - sum_x * sum_x
        if abs(denom) < 1e-12:
            return 0.0
        return (n * sum_xy - sum_x * sum_y) / denom

    def get_chainlink_price(self):
        return self._chainlink_buffer[-1][1] if self._chainlink_buffer else 0.0

    def get_chainlink_price_at(self, target_timestamp):
        """Look up the Chainlink price closest to a target timestamp.

        Searches the _chainlink_buffer for the entry closest to target_timestamp.
        Returns (price, actual_timestamp, offset_seconds) or (None, None, None) if buffer is empty.
        """
        if not self._chainlink_buffer:
            return (None, None, None)

        best_price = None
        best_ts = None
        best_offset = float('inf')

        for ts, price in self._chainlink_buffer:
            offset = abs(ts - target_timestamp)
            if offset < best_offset:
                best_offset = offset
                best_price = price
                best_ts = ts

        return (best_price, best_ts, best_offset)

    def is_chainlink_ready(self):
        return len(self._chainlink_buffer) > 0

    def get_binance_chainlink_gap(self):
        bp, cp = self.get_price(), self.get_chainlink_price()
        return bp - cp if bp and cp else 0.0

    def get_gap_direction(self):
        if len(self._gap_buffer) < 2:
            return "unknown"
        recent = list(self._gap_buffer)
        if len(recent) < 10:
            return "narrowing" if abs(recent[-1][1]) < abs(recent[0][1]) else "widening"
        old_avg = sum(abs(g) for _, g in recent[-10:-5]) / 5
        new_avg = sum(abs(g) for _, g in recent[-5:]) / 5
        return "narrowing" if new_avg < old_avg else "widening"

    async def start(self):
        self._stop.clear()
        self._stats_window_start = time.time()
        self._binance_task = asyncio.create_task(self._binance_loop())
        self._rtds_task = asyncio.create_task(self._rtds_loop())
        if self._config.chainlink_onchain_fallback:
            self._chainlink_onchain_task = asyncio.create_task(self._chainlink_onchain_loop())

    async def stop(self):
        self._stop.set()
        if self._rtds_ping_task:
            self._rtds_ping_task.cancel()
        for ws in (self._binance_ws, self._rtds_ws):
            if ws:
                try: await ws.close()
                except: pass
        for task in (self._binance_task, self._rtds_task, self._chainlink_onchain_task):
            if task:
                task.cancel()
                try: await task
                except asyncio.CancelledError: pass
        self._binance_connected = False
        self._rtds_connected = False
        self._onchain_active = False

    async def _binance_loop(self):
        while not self._stop.is_set():
            try:
                await self._connect_binance_direct()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._binance_connected = False
                log_event(logger, "binance_disconnect", f"Binance direct failed: {type(exc).__name__}: {exc}", level=40)
                try: await self._connect_binance_via_rtds()
                except Exception as fb_exc:
                    log_event(logger, "binance_fallback_fail", f"RTDS fallback failed: {fb_exc}", level=40)
                delay = min(self._reconnect_delay_binance, 30.0)
                await asyncio.sleep(delay)
                self._reconnect_delay_binance = min(self._reconnect_delay_binance * 2, 30.0)

    async def _connect_binance_direct(self):
        url = self._config.binance_ws_url
        self._binance_ws = await asyncio.wait_for(websockets.connect(url, ping_interval=5, ping_timeout=10), timeout=self._config.btc_feed_connect_timeout)
        self._binance_source = "binance-direct"
        self._binance_connected = True
        self._reconnect_delay_binance = 1.0
        log_event(logger, "binance_connected", f"Connected to direct Binance: {url}")
        async for raw in self._binance_ws:
            if self._stop.is_set(): break
            try:
                msg = json.loads(raw)
                price = float(msg["p"])
                ts = msg.get("T", time.time() * 1000) / 1000.0
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue
            self._binance_msg_count += 1
            self._binance_msg_count_window += 1
            self._last_binance_msg_time = time.time()
            if ts - self._last_binance_buffer_ts >= 0.1:
                self._binance_buffer.append((ts, price))
                self._last_binance_buffer_ts = ts
                self._update_gap()
            self._maybe_log_stats()

    async def _connect_binance_via_rtds(self):
        ws = await asyncio.wait_for(websockets.connect(self._config.rtds_ws_url, ping_interval=5, ping_timeout=10), timeout=self._config.btc_feed_connect_timeout)
        self._binance_source = "rtds-fallback"
        self._binance_connected = True
        log_event(logger, "binance_fallback", "Using RTDS for Binance prices")
        await ws.send(_RTDS_SUBSCRIBE_BINANCE_FALLBACK)
        async for raw in ws:
            if self._stop.is_set(): break
            if raw == "PONG": continue
            try: msg = json.loads(raw)
            except json.JSONDecodeError: continue
            payload = msg.get("payload")
            if not payload or not isinstance(payload, dict): continue
            if (payload.get("symbol") or "").lower() != "btcusdt": continue
            now = time.time()
            data_arr = payload.get("data")
            if isinstance(data_arr, list) and data_arr:
                for entry in data_arr:
                    try: price = float(entry["value"])
                    except (KeyError, ValueError, TypeError): continue
                    if price <= 0: continue
                    ts = entry.get("timestamp", now)
                    if isinstance(ts, (int, float)) and ts > 1e12: ts = ts / 1000.0
                    self._binance_buffer.append((ts, price))
                self._binance_msg_count += 1
                self._binance_msg_count_window += 1
                self._last_binance_msg_time = time.time()
                self._update_gap()
        await ws.close()

    async def _rtds_loop(self):
        while not self._stop.is_set():
            try:
                await self._connect_rtds_chainlink()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._rtds_connected = False
                if self._chainlink_source == "rtds":
                    self._chainlink_source = ""
                log_event(logger, "rtds_disconnect", f"RTDS Chainlink failed: {type(exc).__name__}: {exc}", level=40)
                delay = min(self._reconnect_delay_rtds, 30.0)
                await asyncio.sleep(delay)
                self._reconnect_delay_rtds = min(self._reconnect_delay_rtds * 2, 30.0)

    async def _connect_rtds_chainlink(self):
        self._rtds_ws = await asyncio.wait_for(
            websockets.connect(self._config.rtds_ws_url, ping_interval=5, ping_timeout=10),
            timeout=self._config.btc_feed_connect_timeout,
        )
        self._rtds_connected = True
        self._chainlink_source = "rtds"
        self._reconnect_delay_rtds = 1.0
        log_event(logger, "rtds_connected", "Connected to RTDS for Chainlink (ping_interval=5s)")
        await self._rtds_ws.send(_RTDS_SUBSCRIBE_CHAINLINK)
        self._rtds_ping_task = asyncio.create_task(self._rtds_ping_loop())
        async for raw in self._rtds_ws:
            if self._stop.is_set(): break
            self._last_rtds_msg_time = time.time()
            if raw == "PONG": continue
            try: msg = json.loads(raw)
            except json.JSONDecodeError: continue
            payload = msg.get("payload")
            if not payload or not isinstance(payload, dict): continue
            now = time.time()
            data_arr = payload.get("data")
            if isinstance(data_arr, list) and data_arr:
                for entry in data_arr:
                    try: price = float(entry["value"])
                    except (KeyError, ValueError, TypeError): continue
                    if price <= 0: continue
                    ts = entry.get("timestamp", now)
                    if isinstance(ts, (int, float)) and ts > 1e12: ts = ts / 1000.0
                    self._chainlink_buffer.append((ts, price))
                self._chainlink_msg_count += 1
                self._chainlink_msg_count_window += 1
                self._last_chainlink_msg_time = time.time()
                self._update_gap()
            else:
                for key in ("value", "price"):
                    if key in payload:
                        try:
                            price = float(payload[key])
                            ts = payload.get("timestamp", now)
                            if isinstance(ts, (int, float)) and ts > 1e12: ts = ts / 1000.0
                            self._chainlink_buffer.append((ts, price))
                            self._chainlink_msg_count += 1
                            self._chainlink_msg_count_window += 1
                            self._last_chainlink_msg_time = time.time()
                            self._update_gap()
                            break
                        except (ValueError, TypeError): continue

    async def _rtds_ping_loop(self):
        try:
            while not self._stop.is_set():
                await asyncio.sleep(_RTDS_PING_INTERVAL)
                if self._rtds_ws and self._rtds_ws.open:
                    await self._rtds_ws.send("PING")
                    if self._last_rtds_msg_time > 0 and time.time() - self._last_rtds_msg_time > 45.0:
                        log_event(logger, "rtds_stale", "No RTDS message for 45s — forcing reconnect", level=40)
                        await self._rtds_ws.close()
                        break
        except asyncio.CancelledError: pass

    async def _chainlink_onchain_loop(self):
        """FIX 4: Poll Chainlink on-chain when RTDS is down."""
        log_event(logger, "onchain_fallback_init", "On-chain fallback monitor started (dormant)")
        while not self._stop.is_set():
            try:
                if self._rtds_connected:
                    self._onchain_active = False
                    await asyncio.sleep(2.0)
                    continue
                if not self._onchain_active:
                    self._onchain_active = True
                    self._chainlink_source = "onchain"
                    log_event(logger, "onchain_fallback_active", "RTDS down — activating on-chain fallback")
                if self._onchain_feed is None:
                    try:
                        from agents.connectors.chainlink_feed import ChainlinkOnChainFeed
                        self._onchain_feed = ChainlinkOnChainFeed(rpc_url=self._config.chainlink_onchain_rpc_url)
                    except Exception as exc:
                        log_event(logger, "onchain_feed_init_error", f"Init failed: {exc}", level=40)
                        await asyncio.sleep(10.0)
                        continue
                loop = asyncio.get_event_loop()
                try:
                    price, updated_at = await loop.run_in_executor(None, self._onchain_feed.get_latest_price)
                except Exception as exc:
                    log_event(logger, "onchain_poll_error", f"Poll failed: {exc}")
                    await asyncio.sleep(self._config.chainlink_onchain_poll_interval)
                    continue
                if price is not None and price > 0:
                    now = time.time()
                    ts = float(updated_at) if updated_at else now
                    self._chainlink_buffer.append((ts, price))
                    self._chainlink_msg_count += 1
                    self._chainlink_msg_count_window += 1
                    self._last_chainlink_msg_time = now
                    self._update_gap()
                if self._rtds_connected:
                    self._onchain_active = False
                    self._chainlink_source = "rtds"
                    log_event(logger, "onchain_fallback_dormant", "RTDS reconnected — going dormant")
                    continue
                await asyncio.sleep(self._config.chainlink_onchain_poll_interval)
            except asyncio.CancelledError: break
            except Exception as exc:
                log_event(logger, "onchain_loop_error", f"Error: {exc}", level=40)
                await asyncio.sleep(5.0)
        self._onchain_active = False

    def _update_gap(self):
        gap = self.get_binance_chainlink_gap()
        if gap != 0.0:
            self._gap_buffer.append((time.time(), gap))

    def _maybe_log_stats(self):
        now = time.time()
        if now - self._last_stats_log < 10.0: return
        self._last_stats_log = now
        elapsed = max(now - self._stats_window_start, 1.0)
        b_rate = self._binance_msg_count_window / elapsed
        c_rate = self._chainlink_msg_count_window / elapsed
        b_ago = (now - self._last_binance_msg_time) * 1000 if self._last_binance_msg_time else -1
        c_ago = (now - self._last_chainlink_msg_time) * 1000 if self._last_chainlink_msg_time else -1
        gap = self.get_binance_chainlink_gap()
        log_event(logger, "feed_stats",
            f"Binance: {b_rate:.1f}/s last={b_ago:.0f}ms | "
            f"Chainlink({self._chainlink_source or 'none'}): {c_rate:.1f}/s last={c_ago:.0f}ms | "
            f"Gap: ${gap:.2f} | Buf: B={len(self._binance_buffer)} C={len(self._chainlink_buffer)} | Src: {self._binance_source}")
        self._binance_msg_count_window = 0
        self._chainlink_msg_count_window = 0
        self._stats_window_start = now
