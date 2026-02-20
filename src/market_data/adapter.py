from __future__ import annotations
import asyncio
import logging
from typing import Optional, Set, List

from .schema import OrderBookSnapshot, MarketEvent
from .event_bus import AsyncEventBus
from .cache import OrderBookCache
from .providers.polymarket_ws import PolymarketWSProvider
from .providers.polymarket_rtds import PolymarketRTDSProvider

from src.config.settings import get_settings

logger = logging.getLogger(__name__)


class MarketDataAdapter:
    def __init__(self, provider: Optional[object] = None) -> None:
        settings = get_settings()
        url = getattr(settings, "MARKET_DATA_WS_URL", "wss://ws-subscriptions-clob.polymarket.com")
        ping = getattr(settings, "MARKET_DATA_WS_PING_INTERVAL", 10)
        pong = getattr(settings, "MARKET_DATA_WS_PONG_TIMEOUT", 30)
        self.event_bus = AsyncEventBus(queue_maxsize=getattr(settings, "MARKET_DATA_BUS_QUEUE_SIZE", 1000))
        self.cache = OrderBookCache()
        self.provider = provider or PolymarketWSProvider(url, channel="market", ping_interval=ping, pong_timeout=pong)
        self.provider.on_event = self._on_provider_event
        # Optional RTDS provider (config gated)
        self.rtds_provider = None
        if getattr(settings, "MARKET_DATA_RTDS_ENABLED", False):
            rtds_url = getattr(settings, "MARKET_DATA_RTDS_URL", "")
            try:
                self.rtds_provider = PolymarketRTDSProvider(rtds_url)
                self.rtds_provider.on_event = self._on_provider_event
            except Exception:
                logger.exception("Failed to init RTDS provider")
        self._subs: Set[str] = set()
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        await self.provider.start()
        if self.rtds_provider:
            await self.rtds_provider.start()
        logger.info("MarketDataAdapter started")

    async def stop(self) -> None:
        await self.provider.stop()
        if self.rtds_provider:
            await self.rtds_provider.stop()
        self._started = False
        logger.info("MarketDataAdapter stopped")

    async def subscribe(self, token_id: str) -> None:
        if token_id in self._subs:
            return
        self._subs.add(token_id)
        logger.info("MarketDataAdapter: subscribing to token %s", token_id)
        await self.provider.subscribe([token_id])
        logger.info("MarketDataAdapter: subscribed to token %s (provider notified)", token_id)
        try:
            from .telemetry import telemetry
            telemetry.set_gauge("market_data_active_subscriptions", float(len(self._subs)))
        except Exception:
            logger.debug("Failed to set telemetry gauge for active_subscriptions")
        # RTDS provider uses topic-based subscriptions; forward token if present
        if self.rtds_provider:
            try:
                await self.rtds_provider.subscribe([token_id])
            except Exception:
                logger.exception("RTDS subscribe failed")

    async def unsubscribe(self, token_id: str) -> None:
        if token_id not in self._subs:
            return
        self._subs.discard(token_id)
        try:
            await self.provider.unsubscribe([token_id])
        except Exception:
            logger.warning("Provider unsubscribe failed for %s (best-effort)", token_id)
            try:
                from .telemetry import telemetry
                telemetry.incr("market_data_unsubscribe_failed_total", 1)
            except Exception:
                pass
        if self.rtds_provider:
            try:
                await self.rtds_provider.unsubscribe([token_id])
            except Exception:
                logger.warning("RTDS unsubscribe failed for %s (best-effort)", token_id)
                try:
                    from .telemetry import telemetry
                    telemetry.incr("market_data_unsubscribe_failed_total", 1)
                except Exception:
                    pass
        try:
            from .telemetry import telemetry
            telemetry.set_gauge("market_data_active_subscriptions", float(len(self._subs)))
        except Exception:
            logger.debug("Failed to set telemetry gauge for active_subscriptions")

    def get_orderbook(self, token_id: str) -> OrderBookSnapshot | None:
        snap = self.cache.get(token_id)
        return snap

    def get_debug_samples(self) -> dict:
        """Return debug samples from the underlying provider (best-effort)."""
        try:
            if getattr(self.provider, "get_debug_samples", None):
                return self.provider.get_debug_samples()
            # fallback to individual getters
            return {
                "unknown_sample": getattr(self.provider, "get_unknown_sample", lambda: None)(),
                "raw_sample": getattr(self.provider, "get_last_raw_sample", lambda: None)(),
                "parse_error_sample": getattr(self.provider, "get_last_parse_error_sample", lambda: None)(),
            }
        except Exception:
            return {"unknown_sample": None, "raw_sample": None, "parse_error_sample": None}

    def _on_provider_event(self, ev: MarketEvent) -> None:
        # called in provider's event loop; schedule cache update + bus publish
        try:
            # Prefer scheduling on existing running loop (thread-safe)
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(asyncio.create_task, self._handle_event(ev))
            except RuntimeError:
                # No running loop in this thread - run synchronously (blocking) to support tests
                asyncio.run(self._handle_event(ev))
        except Exception:
            # fallback: schedule with ensure_future
            try:
                asyncio.ensure_future(self._handle_event(ev))
            except Exception:
                logger.exception("failed to schedule event handling")

    async def _handle_event(self, ev: MarketEvent) -> None:
        # update cache for book/quote/trade if applicable
        try:
            if ev.type == "book":
                raw = ev.data or {}
                snapshot = OrderBookSnapshot.from_raw(ev.token_id, raw, source="ws_book")
                self.cache.update(snapshot)

            elif ev.type == "quote":
                # quote/price_change has best_bid/best_ask -> store in cache as top-of-book snapshot
                raw = ev.data or {}
                raw_ob = {
                    "bids": [],
                    "asks": [],
                    "best_bid": ev.best_bid,
                    "best_ask": ev.best_ask,
                    "best_bid_size": getattr(ev, "best_bid_size", None),
                    "best_ask_size": getattr(ev, "best_ask_size", None),
                    "timestamp": (raw.get("timestamp") if isinstance(raw, dict) else None),
                }
                snapshot = OrderBookSnapshot.from_raw(ev.token_id, raw_ob, source="ws_quote")
                self.cache.update(snapshot)

            await self.event_bus.publish(ev)
        except Exception:
            logger.exception("error handling provider event")
