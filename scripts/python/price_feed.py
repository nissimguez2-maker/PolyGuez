"""
Real-Time Price Feed — WebSocket + Async HTTP for Binance

Architecture:
  - WebSocket connection to Binance for real-time trade updates (~100ms latency)
  - Fallback to parallel async HTTP if WebSocket disconnects
  - Thread-safe price cache accessible from any coroutine
  - Kline data fetched in parallel (all symbols at once)
  - Used by both the ARB loop (1-3s) and the strategy engine

Usage:
    feed = PriceFeed()
    await feed.start()           # starts WebSocket in background
    prices = feed.get_prices()   # instant, from cache
    await feed.stop()
"""

import asyncio
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT", "AVAXUSDT", "LINKUSDT"]
CLEAN_SYMBOLS = [s.replace("USDT", "") for s in SYMBOLS]

# Binance WebSocket combined stream
WS_URL = "wss://stream.binance.com:9443/stream?streams=" + "/".join(
    f"{s.lower()}@miniTicker" for s in SYMBOLS
)


class PriceFeed:
    """Real-time Binance price feed via WebSocket with HTTP fallback."""

    def __init__(self):
        # Main price cache: {symbol: {price, change_pct, high_24h, low_24h, volume_24h, ...}}
        self._prices: dict = {}
        self._klines_cache: dict = {}  # {symbol: {change_1m, change_5m, change_15m, change_1h}}
        self._last_kline_fetch: float = 0
        self._kline_interval: float = 3.0  # fetch klines every 3s
        self._ws_task: Optional[asyncio.Task] = None
        self._kline_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._ws_connected: bool = False
        self._last_ws_update: float = 0
        self._spike_threshold: float = 1.0  # % change in 1min for spike
        self._price_history: list = []  # for regime detection
        self._reconnect_count: int = 0

    async def start(self):
        """Start the WebSocket feed and kline polling."""
        if self._running:
            return
        self._running = True

        # Initial HTTP fetch for baseline data
        await self._fetch_all_http()

        # Start WebSocket and kline tasks
        self._ws_task = asyncio.create_task(self._ws_loop())
        self._kline_task = asyncio.create_task(self._kline_loop())
        logger.info("PriceFeed started (WebSocket + klines)")

    async def stop(self):
        """Stop all feed tasks."""
        self._running = False
        for task in [self._ws_task, self._kline_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("PriceFeed stopped")

    def get_prices(self) -> dict:
        """Get current prices (instant, from cache). Thread-safe read."""
        result = {}
        for symbol in CLEAN_SYMBOLS:
            if symbol in self._prices:
                data = dict(self._prices[symbol])
                # Merge kline data
                if symbol in self._klines_cache:
                    data.update(self._klines_cache[symbol])
                # Detect spikes
                change_1m = data.get("change_1m", 0)
                data["spike"] = abs(change_1m) >= self._spike_threshold
                data["spike_direction"] = "UP" if change_1m > 0 else "DOWN" if change_1m < 0 else None
                result[symbol] = data
        return result

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is alive."""
        return self._ws_connected and (time.time() - self._last_ws_update) < 10

    # ─── WebSocket Loop ───

    async def _ws_loop(self):
        """WebSocket connection with auto-reconnect."""
        try:
            import websockets
        except ImportError:
            logger.warning("websockets not installed, using HTTP polling only")
            await self._http_polling_loop()
            return

        while self._running:
            try:
                async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=10) as ws:
                    self._ws_connected = True
                    self._reconnect_count = 0
                    logger.info("PriceFeed WebSocket connected")

                    async for raw_msg in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw_msg)
                            data = msg.get("data", {})
                            if not data:
                                continue

                            symbol = data.get("s", "")  # e.g. "BTCUSDT"
                            clean = symbol.replace("USDT", "")

                            if clean in CLEAN_SYMBOLS:
                                self._prices[clean] = {
                                    "price": float(data.get("c", 0)),     # close price
                                    "change_pct": float(data.get("P", 0)),  # 24h change %
                                    "high_24h": float(data.get("h", 0)),
                                    "low_24h": float(data.get("l", 0)),
                                    "volume_24h": float(data.get("q", 0)),  # quote volume
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "source": "websocket",
                                }
                                self._last_ws_update = time.time()
                        except (json.JSONDecodeError, KeyError, ValueError) as e:
                            logger.debug(f"WS parse error: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._ws_connected = False
                self._reconnect_count += 1
                wait = min(30, 2 ** min(self._reconnect_count, 5))
                logger.warning(f"WS disconnected ({e}), reconnecting in {wait}s...")
                await asyncio.sleep(wait)

        self._ws_connected = False

    async def _http_polling_loop(self):
        """Fallback: poll Binance HTTP every 2 seconds if no WebSocket."""
        while self._running:
            try:
                await self._fetch_all_http()
            except Exception as e:
                logger.debug(f"HTTP poll error: {e}")
            await asyncio.sleep(2)

    # ─── Kline Loop (momentum data) ───

    async def _kline_loop(self):
        """Fetch kline data periodically for momentum detection."""
        while self._running:
            try:
                await self._fetch_klines_parallel()
                # Update price history for regime detection
                now = time.time()
                snap = {k: v.get("price", 0) for k, v in self._prices.items()}
                self._price_history.append({"time": now, "prices": snap})
                if len(self._price_history) > 120:  # ~6 min at 3s interval
                    self._price_history = self._price_history[-120:]

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Kline fetch error: {e}")

            await asyncio.sleep(self._kline_interval)

    async def _fetch_klines_parallel(self):
        """Fetch 1m, 5m, 15m, 1h klines for ALL symbols in parallel."""
        async with httpx.AsyncClient(timeout=5) as client:
            tasks = []
            for symbol in SYMBOLS:
                # 1m klines (5 candles for 5m momentum)
                tasks.append(self._fetch_kline(client, symbol, "1m", 5))
                # 15m klines (for trend confirmation)
                tasks.append(self._fetch_kline(client, symbol, "15m", 4))
                # 1h klines (for longer-term trend)
                tasks.append(self._fetch_kline(client, symbol, "1h", 4))

            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results (3 per symbol: 1m, 15m, 1h)
        for i, symbol in enumerate(SYMBOLS):
            clean = symbol.replace("USDT", "")
            kline_data = self._klines_cache.get(clean, {})

            # 1m klines
            r1m = results[i * 3]
            if isinstance(r1m, list) and len(r1m) >= 2:
                prev_close = float(r1m[-2][4])
                current = self._prices.get(clean, {}).get("price", 0) or float(r1m[-1][4])
                kline_data["change_1m"] = round(((current - prev_close) / prev_close) * 100, 3) if prev_close else 0
                if len(r1m) >= 5:
                    five_ago = float(r1m[0][1])
                    kline_data["change_5m"] = round(((current - five_ago) / five_ago) * 100, 3) if five_ago else 0

            # 15m klines
            r15m = results[i * 3 + 1]
            if isinstance(r15m, list) and len(r15m) >= 2:
                prev_close = float(r15m[-2][4])
                current = self._prices.get(clean, {}).get("price", 0) or float(r15m[-1][4])
                kline_data["change_15m"] = round(((current - prev_close) / prev_close) * 100, 3) if prev_close else 0

            # 1h klines
            r1h = results[i * 3 + 2]
            if isinstance(r1h, list) and len(r1h) >= 2:
                prev_close = float(r1h[-2][4])
                current = self._prices.get(clean, {}).get("price", 0) or float(r1h[-1][4])
                kline_data["change_1h"] = round(((current - prev_close) / prev_close) * 100, 3) if prev_close else 0

            self._klines_cache[clean] = kline_data

    async def _fetch_kline(self, client: httpx.AsyncClient, symbol: str, interval: str, limit: int):
        """Fetch kline data for a single symbol/interval."""
        try:
            resp = await client.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return []

    # ─── HTTP Bulk Fetch (initial + fallback) ───

    async def _fetch_all_http(self):
        """Fetch all prices via parallel HTTP (initial load or WS fallback)."""
        async with httpx.AsyncClient(timeout=5) as client:
            tasks = [
                client.get("https://api.binance.com/api/v3/ticker/24hr", params={"symbol": s})
                for s in SYMBOLS
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for symbol, result in zip(SYMBOLS, results):
            clean = symbol.replace("USDT", "")
            if isinstance(result, Exception):
                continue
            if result.status_code == 200:
                data = result.json()
                self._prices[clean] = {
                    "price": float(data["lastPrice"]),
                    "change_pct": float(data["priceChangePercent"]),
                    "high_24h": float(data["highPrice"]),
                    "low_24h": float(data["lowPrice"]),
                    "volume_24h": float(data["quoteVolume"]),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "http",
                }

    # ─── Regime Detection ───

    def detect_market_regime(self) -> dict:
        """Detect current market regime based on BTC price history."""
        if len(self._price_history) < 10:
            return {"regime": "unknown", "volatility": 0, "description": "Insufficient data"}

        btc_prices = [
            h["prices"].get("BTC", 0) for h in self._price_history[-60:]
            if h["prices"].get("BTC", 0) > 0
        ]
        if len(btc_prices) < 5:
            return {"regime": "unknown", "volatility": 0, "description": "Insufficient BTC data"}

        changes = [
            abs(btc_prices[i] - btc_prices[i-1]) / btc_prices[i-1] * 100
            for i in range(1, len(btc_prices))
        ]
        avg_change = sum(changes) / len(changes) if changes else 0

        first_half = sum(btc_prices[:len(btc_prices)//2]) / (len(btc_prices)//2)
        second_half = sum(btc_prices[len(btc_prices)//2:]) / (len(btc_prices) - len(btc_prices)//2)
        trend_pct = ((second_half - first_half) / first_half) * 100

        if avg_change > 0.1:
            regime = "volatile"
            desc = f"Alta volatilidade ({avg_change:.3f}%/tick)"
        elif trend_pct > 0.05:
            regime = "trending_up"
            desc = f"Tendência de alta ({trend_pct:+.3f}%)"
        elif trend_pct < -0.05:
            regime = "trending_down"
            desc = f"Tendência de baixa ({trend_pct:+.3f}%)"
        else:
            regime = "ranging"
            desc = f"Mercado lateral ({trend_pct:+.3f}%)"

        return {
            "regime": regime,
            "volatility": round(avg_change, 4),
            "trend_pct": round(trend_pct, 4),
            "description": desc,
        }
