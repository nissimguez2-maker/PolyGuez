from __future__ import annotations
import asyncio
import json
import logging
from typing import List, Optional

import websockets
import time

from ..schema import MarketEvent, OrderBookSnapshot
from .base import AbstractMarketDataProvider
from ..telemetry import telemetry
from src.config.settings import get_settings

logger = logging.getLogger(__name__)


class PolymarketWSProvider(AbstractMarketDataProvider):
    def __init__(self, url: str, channel: str = "market", ping_interval: int = 10, pong_timeout: int = 30) -> None:
        super().__init__()
        self.url = url.rstrip("/") + f"/ws/{channel}"
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._subs: set[str] = set()
        self._ws = None
        # whether we've logged an unknown sample for current connection
        self._unknown_sample_logged: bool = False
        # store one unknown sample per-connection for debugging
        self._unknown_sample: dict | None = None
        # last raw sample (truncated) and parse-error sample
        self._last_raw_sample: str | None = None
        self._raw_sample_logged: bool = False
        self._last_parse_error_sample: str | None = None
        self._parse_error_logged: bool = False
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
        # close websocket if open
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def subscribe(self, token_ids: List[str]) -> None:
        for t in token_ids:
            self._subs.add(t)
        # If websocket connected, send subscription (safe check to avoid AttributeError)
        try:
            ws = self._ws
            connected = False
            if ws is not None:
                # Prefer explicit closed flag (works for multiple libs); fall back to library-specific attrs
                if hasattr(ws, "closed"):
                    connected = not bool(getattr(ws, "closed"))
                elif hasattr(ws, "state"):
                    try:
                        connected = getattr(ws, "state").name == "OPEN"
                    except Exception:
                        connected = False
                elif hasattr(ws, "open"):
                    connected = bool(getattr(ws, "open"))
            if connected:
                # send operation-based subscribe when already connected
                await self._send_subscribe_op(list(token_ids))
            else:
                logger.debug("subscribe: websocket not connected, queued tokens (no send)")
        except Exception:
            # Never raise out of subscribe - queue tokens for later when WS connects
            logger.exception("subscribe: unexpected error while attempting to send subscribe")

    async def unsubscribe(self, token_ids: List[str]) -> None:
        for t in token_ids:
            self._subs.discard(t)
        try:
            ws = self._ws
            connected = False
            if ws is not None:
                if hasattr(ws, "closed"):
                    connected = not bool(getattr(ws, "closed"))
                elif hasattr(ws, "state"):
                    try:
                        connected = getattr(ws, "state").name == "OPEN"
                    except Exception:
                        connected = False
                elif hasattr(ws, "open"):
                    connected = bool(getattr(ws, "open"))
            if connected:
                await self._send_unsubscribe(list(token_ids))
            else:
                logger.debug("unsubscribe: websocket not connected, removal queued")
        except Exception:
            logger.exception("unsubscribe: unexpected error while attempting to send unsubscribe")

    async def _send_subscribe(self, token_ids: List[str]) -> None:
        # legacy handshake (used on initial connect)
        if not token_ids:
            return
        settings = get_settings()
        custom = bool(getattr(settings, "MARKET_DATA_CUSTOM_FEATURE_ENABLED", True))
        msg = {"assets_ids": token_ids, "type": "market", "custom_feature_enabled": custom}
        try:
            logger.debug("WS send handshake: count=%d sample=%s", len(token_ids), ",".join(str(x) for x in list(token_ids)[:3]))
            await self._ws.send(json.dumps(msg))
        except Exception as e:
            logger.debug("handshake send failed: %s", e)

    async def _send_subscribe_op(self, token_ids: List[str]) -> None:
        # operation-based subscribe (used after connect)
        if not token_ids:
            return
        settings = get_settings()
        custom = bool(getattr(settings, "MARKET_DATA_CUSTOM_FEATURE_ENABLED", True))
        msg = {"assets_ids": token_ids, "operation": "subscribe", "custom_feature_enabled": custom}
        try:
            logger.debug("WS send subscribe_op: count=%d sample=%s", len(token_ids), ",".join(str(x) for x in list(token_ids)[:3]))
            await self._ws.send(json.dumps(msg))
            try:
                telemetry.incr("market_data_subscribe_sent_total", 1)
            except Exception:
                pass
        except Exception as e:
            logger.debug("subscribe_op send failed: %s", e)

    async def _send_unsubscribe(self, token_ids: List[str]) -> None:
        if not token_ids:
            return
        settings = get_settings()
        custom = bool(getattr(settings, "MARKET_DATA_CUSTOM_FEATURE_ENABLED", True))
        msg = {"assets_ids": token_ids, "operation": "unsubscribe", "custom_feature_enabled": custom}
        try:
            logger.debug("WS send unsubscribe_op: count=%d sample=%s", len(token_ids), ",".join(str(x) for x in list(token_ids)[:3]))
            await self._ws.send(json.dumps(msg))
            try:
                telemetry.incr("market_data_unsubscribe_sent_total", 1)
            except Exception:
                pass
        except Exception as e:
            logger.debug("unsubscribe_op send failed: %s", e)

    def _safe_emit(self, ev: MarketEvent) -> bool:
        """Call on_event safely; return True if handler executed without raising."""
        if not self.on_event:
            return False
        try:
            self.on_event(ev)
            try:
                telemetry.incr("market_data_events_emitted_total", 1)
            except Exception:
                pass
            return True
        except Exception:
            logger.exception("on_event handler failed")
            return False

    def get_unknown_sample(self) -> dict | None:
        """Return a captured unknown sample for debugging (or None)."""
        return self._unknown_sample

    def get_last_raw_sample(self) -> str | None:
        """Return the last raw frame sample (truncated) or None."""
        return self._last_raw_sample

    def get_last_parse_error_sample(self) -> str | None:
        """Return the last parse-error raw sample (truncated) or None."""
        return self._last_parse_error_sample

    # Backwards/alternative attribute names requested by consumers
    @property
    def raw_sample(self) -> str | None:
        return self._last_raw_sample

    @property
    def parse_error_sample(self) -> str | None:
        return self._last_parse_error_sample

    @property
    def unknown_sample(self) -> dict | None:
        return self._unknown_sample

    def get_debug_samples(self) -> dict:
        """Return all debug samples in a simple dict."""
        return {
            "unknown_sample": self.unknown_sample,
            "raw_sample": self.raw_sample,
            "parse_error_sample": self.parse_error_sample,
        }

    async def process_raw(self, raw: bytes | str) -> object | None:
        """
        Process a raw WS frame: decode, store a raw sample, try to json.loads and
        return the parsed object (dict/list) or None on parse error.
        This encapsulates the decoding + parse-error telemetry and sample capture.
        """
        # decode raw
        try:
            if isinstance(raw, (bytes, bytearray)):
                raw_s = raw.decode("utf-8", errors="ignore")
            else:
                raw_s = str(raw)
        except Exception:
            raw_s = str(raw)

        # store truncated raw sample (one per connection logged)
        try:
            self._last_raw_sample = (raw_s[:800]) if raw_s is not None else None
            if not getattr(self, "_raw_sample_logged", False):
                logger.warning("WS raw sample: %s", (self._last_raw_sample or "")[:400])
                self._raw_sample_logged = True
        except Exception:
            pass

        # try parse
        try:
            parsed = json.loads(raw_s)
            return parsed
        except Exception:
            try:
                telemetry.incr("market_data_parse_errors_total", 1)
            except Exception:
                pass
            try:
                self._last_parse_error_sample = (raw_s[:800]) if raw_s is not None else None
                if not getattr(self, "_parse_error_logged", False):
                    logger.warning("WS json parse error sample: %s", (self._last_parse_error_sample or "")[:400])
                    self._parse_error_logged = True
            except Exception:
                pass
            return None

    async def _handle_dict_msg(self, m: dict) -> None:
        """Normalize and dispatch a single message dict (book / price_change / trade / best_bid_ask)."""
        # count every parsed dict for visibility
        try:
            telemetry.incr("market_data_parsed_dict_total", 1)
        except Exception:
            pass

        # support wrapped payloads: many messages use {"data": {...}} or {"payload": {...}}
        payload = m
        if isinstance(m.get("data"), dict):
            payload = m["data"]
        elif isinstance(m.get("payload"), dict):
            payload = m["payload"]

        etype = (payload.get("event_type") if isinstance(payload, dict) else None) or \
                (payload.get("eventType") if isinstance(payload, dict) else None) or \
                (payload.get("type") if isinstance(payload, dict) else None) or \
                (payload.get("topic") if isinstance(payload, dict) else None) or \
                (payload.get("event") if isinstance(payload, dict) else None)
        token = (payload.get("asset_id") if isinstance(payload, dict) else None) or \
                (payload.get("assetId") if isinstance(payload, dict) else None) or \
                m.get("asset_id") or m.get("assetId") or m.get("market") or m.get("asset")

        # update last-msg timestamp for telemetry (use wall clock)
        try:
            telemetry.set_last_msg_ts(time.time())
        except Exception:
            pass

        # Heuristics: treat payloads with bids/asks as book even if etype missing
        if not isinstance(payload, dict):
            # payload is not a dict -- treat as unknown
            detected_type = None
        else:
            detected_type = etype
            if detected_type is None:
                if ("bids" in payload and "asks" in payload):
                    detected_type = "book"
                elif ("price_changes" in payload) or ("priceChanges" in payload):
                    detected_type = "price_change"
                elif ("last_trade_price" in payload) or ("lastTradePrice" in payload):
                    detected_type = "last_trade_price"

        # Dispatch known event types
        if detected_type == "book":
            try:
                bids = payload.get("bids") or payload.get("buys") or []
                asks = payload.get("asks") or payload.get("sells") or []
                raw_ob = {"bids": bids, "asks": asks}
                snapshot = OrderBookSnapshot.from_raw(str(payload.get("asset_id") or token), raw_ob, source="ws")
                ev = MarketEvent(
                    ts=float(payload.get("timestamp") or m.get("timestamp") or 0) / 1000.0 if (payload.get("timestamp") or m.get("timestamp")) else float(asyncio.get_event_loop().time()),
                    type="book",
                    token_id=snapshot.token_id,
                    best_bid=snapshot.best_bid,
                    best_ask=snapshot.best_ask,
                    spread_pct=snapshot.spread_pct,
                    data=m,
                )
                try:
                    telemetry.incr("market_data_messages_total", 1)
                    telemetry.set_gauge("market_data_active_subscriptions", float(len(self._subs)))
                except Exception:
                    pass
                self._safe_emit(ev)
            except Exception:
                logger.exception("failed to process book message")

        elif detected_type == "best_bid_ask" or detected_type == "best_bid_ask_update":
            # Polymarket custom quote updates: treat as lightweight book/quote
            try:
                token_id = str(payload.get("asset_id") or payload.get("assetId") or token)
                # parse numeric fields
                try:
                    best_bid_f = float(payload.get("best_bid") or payload.get("bestBid")) if (payload.get("best_bid") or payload.get("bestBid")) is not None else None
                except Exception:
                    best_bid_f = None
                try:
                    best_ask_f = float(payload.get("best_ask") or payload.get("bestAsk")) if (payload.get("best_ask") or payload.get("bestAsk")) is not None else None
                except Exception:
                    best_ask_f = None
                # spread absolute
                spread_abs = None
                try:
                    if payload.get("spread") is not None:
                        spread_abs = float(payload.get("spread"))
                    elif best_bid_f is not None and best_ask_f is not None:
                        spread_abs = float(best_ask_f) - float(best_bid_f)
                except Exception:
                    spread_abs = None
                # spread pct (relative)
                spread_pct = None
                try:
                    if spread_abs is not None and best_bid_f is not None and best_ask_f is not None:
                        mid = (best_bid_f + best_ask_f) / 2.0
                        if mid:
                            spread_pct = spread_abs / mid
                except Exception:
                    spread_pct = None
                # timestamp handling (ms vs s)
                ts_val = None
                try:
                    raw_ts = payload.get("timestamp") or m.get("timestamp")
                    if raw_ts is not None:
                        raw_ts_f = float(raw_ts)
                        if raw_ts_f > 1e12:
                            ts_val = raw_ts_f / 1000.0
                        elif raw_ts_f > 1e9:
                            ts_val = raw_ts_f
                        else:
                            ts_val = time.time()
                    else:
                        ts_val = time.time()
                except Exception:
                    ts_val = time.time()

                # Emit as a lightweight quote update so consumers can use top-of-book quickly
                ev = MarketEvent(
                    ts=float(ts_val),
                    type="quote",
                    token_id=token_id,
                    best_bid=best_bid_f,
                    best_ask=best_ask_f,
                    spread_pct=spread_pct,
                    data=m,
                )
                try:
                    telemetry.incr("market_data_messages_total", 1)
                    telemetry.set_gauge("market_data_active_subscriptions", float(len(self._subs)))
                except Exception:
                    pass
                self._safe_emit(ev)
            except Exception:
                logger.exception("failed to process best_bid_ask message")

        elif detected_type == "price_change":
            try:
                changes = payload.get("price_changes") or payload.get("priceChanges") or []
                for pc in changes:
                    token_id = str(pc.get("asset_id") or pc.get("assetId") or token)
                    # parse numeric fields from price_change -> treat as quote

                    def _f(v):

                        try:

                            return float(v) if v is not None and v != "" else None

                        except Exception:

                            return None

                    best_bid_f = _f(pc.get("best_bid") or pc.get("bestBid"))

                    best_ask_f = _f(pc.get("best_ask") or pc.get("bestAsk"))

                    spread_pct = None

                    try:

                        if best_bid_f is not None and best_ask_f is not None and best_ask_f > 0:

                            spread_pct = (best_ask_f - best_bid_f) / best_ask_f

                    except Exception:

                        spread_pct = None

                    ev = MarketEvent(
                        ts=float(payload.get("timestamp") or m.get("timestamp") or 0) / 1000.0 if (payload.get("timestamp") or m.get("timestamp")) else float(asyncio.get_event_loop().time()),
                        type="quote",
                        token_id=token_id,
                        best_bid=best_bid_f,
                        best_ask=best_ask_f,
                        spread_pct=spread_pct,
                        data=pc,
                    )
                    try:
                        telemetry.incr("market_data_messages_total", 1)
                        telemetry.set_gauge("market_data_active_subscriptions", float(len(self._subs)))
                    except Exception:
                        pass
                    self._safe_emit(ev)
            except Exception:
                logger.exception("failed to process price_change message")

        elif detected_type in ("last_trade_price", "trade", "lastTradePrice"):
            try:
                token_id = str(payload.get("asset_id") or payload.get("assetId") or token)
                ev = MarketEvent(
                    ts=float(payload.get("timestamp") or m.get("timestamp") or 0) / 1000.0 if (payload.get("timestamp") or m.get("timestamp")) else float(asyncio.get_event_loop().time()),
                    type="trade",
                    token_id=token_id,
                    best_bid=None,
                    best_ask=None,
                    spread_pct=None,
                    data=m,
                )
                try:
                    telemetry.incr("market_data_messages_total", 1)
                    telemetry.set_gauge("market_data_active_subscriptions", float(len(self._subs)))
                except Exception:
                    pass
                self._safe_emit(ev)
            except Exception:
                logger.exception("failed to process trade message")

        else:
            # unknown event type: sample once per connection and increment counter
            try:
                telemetry.incr("market_data_unknown_etype_total", 1)
            except Exception:
                pass
            try:
                if not getattr(self, "_unknown_sample_logged", False):
                    self._unknown_sample_logged = True
                    payload_keys = sorted(list(payload.keys()))[:40] if isinstance(payload, dict) else [str(type(payload))]
                    self._unknown_sample = {
                        "keys": sorted(list(m.keys()))[:40],
                        "etype_guess": etype,
                        "payload_keys": payload_keys,
                        "trunc": (json.dumps(m, default=str)[:800] if isinstance(m, (dict, list)) else str(m))[:800],
                    }
                    logger.warning("WS unknown message sample: etype=%s keys=%s payload_keys=%s trunc=%s",
                                   etype, self._unknown_sample["keys"], self._unknown_sample["payload_keys"], self._unknown_sample["trunc"])
            except Exception:
                pass
            return

    async def _run_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                logger.info("Connecting to Polymarket WS %s", self.url)
                async with websockets.connect(self.url, ping_interval=self._ping_interval, ping_timeout=self._pong_timeout) as ws:
                    self._ws = ws
                    # reset per-connection diagnostics
                    try:
                        self._unknown_sample_logged = False
                        self._unknown_sample = None
                        self._last_raw_sample = None
                        self._raw_sample_logged = False
                        self._last_parse_error_sample = None
                        self._parse_error_logged = False
                    except Exception:
                        pass
                    telemetry.set_gauge("market_data_ws_connected", 1.0)
                    backoff = 1.0
                    # initial handshake subscribe if any (type=market)
                    if self._subs:
                        await self._send_subscribe(list(self._subs))
                        # After handshake, attempt to flush pending subscribe operations as well
                        try:
                            await self._send_subscribe_op(list(self._subs))
                            try:
                                telemetry.incr("market_data_subscribe_sent_total", 1)
                            except Exception:
                                pass
                        except Exception:
                            logger.debug("failed to flush subscribe_op after handshake")

                    async for raw in ws:
                        # count raw messages immediately for diagnostics
                        try:
                            telemetry.incr("market_data_raw_messages_total", 1)
                        except Exception:
                            pass
                        # raw may be bytes or str
                        try:
                            if isinstance(raw, (bytes, bytearray)):
                                raw_s = raw.decode("utf-8", errors="ignore")
                            else:
                                raw_s = str(raw)
                        except Exception:
                            raw_s = str(raw)
                        # process raw frame (decoding + parse + samples)
                        parsed = await self.process_raw(raw)
                        if parsed is None:
                            # parse error already recorded inside process_raw
                            continue

                        # helper to process dict messages moved into class method _handle_dict_msg

                        # msg may be a list (batch) or a single dict
                        if isinstance(parsed, list):
                            for item in parsed:
                                if isinstance(item, dict):
                                    await self._handle_dict_msg(item)
                                else:
                                    try:
                                        telemetry.incr("market_data_parse_errors_total", 1)
                                    except Exception:
                                        pass
                            continue

                        if not isinstance(parsed, dict):
                            try:
                                telemetry.incr("market_data_parse_errors_total", 1)
                            except Exception:
                                pass
                            continue

                        await self._handle_dict_msg(parsed)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("WebSocket connection error: %s", e)
                telemetry.incr("market_data_reconnect_total", 1)
                telemetry.set_gauge("market_data_ws_connected", 0.0)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
        logger.info("PolymarketWSProvider stopped")

    @staticmethod
    def parse_raw_message(msg: dict):
        # Parse raw Polymarket WS message dict into list of MarketEvent instances.
        events = []
        etype = msg.get("event_type") or msg.get("type") or msg.get("topic")
        if etype == "book":
            token = str(msg.get("asset_id") or msg.get("assetId") or msg.get("market") or "")
            ev = MarketEvent(ts=float(msg.get("timestamp") or 0)/1000.0 if msg.get("timestamp") else time.time(), type="book", token_id=token, best_bid=None, best_ask=None, spread_pct=None, data=msg)
            events.append(ev)
        elif etype == "price_change":
            changes = msg.get("price_changes") or msg.get("priceChanges") or []
            for pc in changes:
                token_id = str(pc.get("asset_id") or pc.get("assetId") or "")
                ev = MarketEvent(ts=float(msg.get("timestamp") or 0)/1000.0 if msg.get("timestamp") else time.time(), type="quote", token_id=token_id, best_bid=(float(pc.get("best_bid")) if pc.get("best_bid") is not None else None), best_ask=(float(pc.get("best_ask")) if pc.get("best_ask") is not None else None), spread_pct=None, data=pc)
                events.append(ev)
        elif etype == "last_trade_price":
            token_id = str(msg.get("asset_id") or "")
            ev = MarketEvent(ts=float(msg.get("timestamp") or 0)/1000.0 if msg.get("timestamp") else time.time(), type="trade", token_id=token_id, best_bid=None, best_ask=None, spread_pct=None, data=msg)
            events.append(ev)
        return events



