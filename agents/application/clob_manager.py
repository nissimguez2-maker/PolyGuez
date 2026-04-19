"""CLOB WebSocket + REST price polling — extracted from PolyGuezRunner.

CLOBMixin adds CLOB-related methods to PolyGuezRunner via multiple inheritance.
All self.* attributes are initialised in PolyGuezRunner.__init__; this class
has no __init__ of its own.
"""

import asyncio
import json
import time

import aiohttp
import websockets

from agents.strategies.strategy_core import compute_clob_depth
from agents.utils.logger import get_logger, log_event

logger = get_logger("polyguez.clob")


class CLOBMixin:
    """CLOB WebSocket and REST price polling methods."""

    _CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    async def _clob_ws_loop(self):
        """Persistent CLOB WS connection. Reconnects on failure."""
        log_event(logger, "clob_ws_started", "[CLOB/WS] Loop started")
        _ws_headers = {
            "Origin": "https://polymarket.com",
            "User-Agent": "Mozilla/5.0",
        }
        while not self._killed:
            try:
                self._clob_ws = await asyncio.wait_for(
                    websockets.connect(
                        self._CLOB_WS_URL,
                        ping_interval=10, ping_timeout=20,
                        extra_headers=_ws_headers,
                    ),
                    timeout=10.0,
                )
                self._clob_ws_connected = True
                # COR-06: the just-reconnected socket hasn't delivered a
                # book message yet, so prices are stale. The flag flips back
                # to True in `_handle_clob_ws_msg` once both YES and NO
                # prices are populated.
                self._clob_ws_prices_valid = False
                log_event(logger, "clob_ws_connected", "[CLOB/WS] Connected")

                # Start application-level ping keep-alive
                if self._clob_ws_ping_task:
                    self._clob_ws_ping_task.cancel()
                self._clob_ws_ping_task = self._spawn(self._clob_ws_ping_loop(), "clob_ws_ping_loop")

                # Re-subscribe if we already have tokens
                yes_tok, no_tok = self._clob_ws_tokens
                if yes_tok and no_tok:
                    sub = json.dumps({
                        "auth": {},
                        "id": "1",
                        "type": "subscribe",
                        "channel": "market",
                        "markets": [yes_tok, no_tok],
                    })
                    await self._clob_ws.send(sub)
                    log_event(logger, "clob_ws_resubscribed",
                              f"[CLOB/WS] Re-subscribed: yes={yes_tok[:16]}..., no={no_tok[:16]}...")

                async for raw in self._clob_ws:
                    if self._killed:
                        break
                    self._clob_ws_last_msg = time.time()
                    # Reset backoff after first successful message
                    if self._clob_ws_reconnect_count > 0:
                        log_event(logger, "clob_ws_stable", f"[CLOB/WS] Stable — resetting backoff (was {self._clob_ws_reconnect_count})")
                        self._clob_ws_reconnect_count = 0
                    try:
                        msg = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    self._handle_clob_ws_msg(msg)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._clob_ws_connected = False
                # COR-06: invalidate cached prices on disconnect so the
                # main cycle refuses to consume stale zero/old values
                # until the socket is back and has delivered a fresh book.
                self._clob_ws_prices_valid = False
                log_event(logger, "clob_ws_error",
                          f"[CLOB/WS] Error: {type(exc).__name__}: {exc}", level=30)
            # Cancel ping task on disconnect
            if self._clob_ws_ping_task:
                self._clob_ws_ping_task.cancel()
                self._clob_ws_ping_task = None
            # Exponential backoff on reconnect (cap 30s)
            self._clob_ws_connected = False
            self._clob_ws_prices_valid = False
            delay = min(2 ** self._clob_ws_reconnect_count, 30)
            self._clob_ws_reconnect_count += 1
            log_event(logger, "clob_ws_backoff", f"[CLOB/WS] Reconnecting in {delay}s (attempt {self._clob_ws_reconnect_count})")
            await asyncio.sleep(delay)

    def _handle_clob_ws_msg(self, msg):
        """Parse CLOB WS messages and update cached prices."""
        msg_type = msg.get("type", "")
        yes_tok, no_tok = self._clob_ws_tokens

        if msg_type == "book":
            # Full orderbook snapshot — extract best bid/ask mid
            market = msg.get("market", "")
            bids = msg.get("bids", [])
            asks = msg.get("asks", [])
            mid = 0.0
            if bids and asks:
                best_bid = float(bids[0].get("price", 0))
                best_ask = float(asks[0].get("price", 0))
                if best_bid > 0 and best_ask > 0:
                    mid = (best_bid + best_ask) / 2.0
            elif msg.get("mid"):
                mid = float(msg["mid"])
            if mid > 0:
                if market == yes_tok:
                    self._clob_ws_yes = mid
                elif market == no_tok:
                    self._clob_ws_no = mid
                if self._clob_ws_yes > 0 and self._clob_ws_no > 0:
                    # COR-06: we now have a fresh book for BOTH legs, so
                    # main-cycle reads are safe again.
                    if not self._clob_ws_prices_valid:
                        log_event(logger, "clob_ws_prices_valid",
                                  "[CLOB/WS] First fresh book post-connect — prices now valid")
                    self._clob_ws_prices_valid = True
                    log_event(logger, "clob_ws_book",
                              f"[CLOB/WS] UP={self._clob_ws_yes:.4f} DOWN={self._clob_ws_no:.4f}")

        elif msg_type in ("price_change", "last_trade_price"):
            market = msg.get("market", "") or msg.get("asset_id", "")
            price = 0.0
            # Try various price field names
            for key in ("price", "mid", "last_trade_price", "new_price"):
                if key in msg:
                    try:
                        price = float(msg[key])
                        break
                    except (ValueError, TypeError):
                        continue
            if price > 0:
                if market == yes_tok:
                    self._clob_ws_yes = price
                elif market == no_tok:
                    self._clob_ws_no = price
                if self._clob_ws_yes > 0 and self._clob_ws_no > 0:
                    if not self._clob_ws_prices_valid:
                        log_event(logger, "clob_ws_prices_valid",
                                  "[CLOB/WS] First fresh price post-connect — prices now valid")
                    self._clob_ws_prices_valid = True
                    log_event(logger, "clob_ws_price",
                              f"[CLOB/WS] UP={self._clob_ws_yes:.4f} DOWN={self._clob_ws_no:.4f}")

    async def _clob_ws_ping_loop(self):
        """Application-level ping to keep the CLOB WS connection alive."""
        try:
            while self._clob_ws_connected and not self._killed:
                await asyncio.sleep(10)
                try:
                    if self._clob_ws:
                        await self._clob_ws.ping()
                except Exception as ping_exc:
                    log_event(logger, "clob_ws_ping_failed",
                        f"[CLOB/WS] Ping failed — exiting ping loop: {type(ping_exc).__name__}: {ping_exc}",
                        level=30)
                    break
        except asyncio.CancelledError:
            pass

    async def _subscribe_clob_ws(self, yes_token, no_token):
        """Subscribe to new market tokens on the CLOB WS."""
        if not self.config.clob_ws_enabled:
            self._clob_ws_tokens = (yes_token, no_token)
            return

        if (yes_token, no_token) == self._clob_ws_tokens:
            return  # Already subscribed to these tokens

        # Reset cached prices for new market
        self._clob_ws_yes = 0.0
        self._clob_ws_no = 0.0
        self._clob_ws_tokens = (yes_token, no_token)

        if self._clob_ws and self._clob_ws_connected:
            try:
                sub = json.dumps({
                    "auth": {},
                    "id": "1",
                    "type": "subscribe",
                    "channel": "market",
                    "markets": [yes_token, no_token],
                })
                await self._clob_ws.send(sub)
                log_event(logger, "clob_ws_subscribed",
                          f"[CLOB/WS] Subscribed: yes={yes_token[:16]}..., no={no_token[:16]}...")
            except Exception as exc:
                log_event(logger, "clob_ws_subscribe_error",
                          f"[CLOB/WS] Subscribe failed: {exc}", level=30)
        else:
            log_event(logger, "clob_ws_pending",
                      "[CLOB/WS] Not connected, will subscribe on reconnect")

    async def _poll_clob(self, yes_token, no_token):
        """Get CLOB prices: prefer WS cache, fall back to REST, then Gamma."""
        # COR-06: ws_fresh now additionally requires `_clob_ws_prices_valid`.
        # Between a disconnect and the first post-reconnect book message,
        # the cached yes/no prices may be stale (or the disconnect set them
        # to zero) — the flag guarantees we only trust the cache once a
        # fresh book has arrived. Functionally equivalent to the existing
        # "`> 0`" checks for the common case, plus explicit protection
        # against any future code path that leaves stale non-zero prices.
        ws_fresh = (
            self._clob_ws_connected
            and self._clob_ws_prices_valid
            and self._clob_ws_last_msg > 0
            and time.time() - self._clob_ws_last_msg < 30.0
            and self._clob_ws_yes > 0
            and self._clob_ws_no > 0
        )
        if ws_fresh:
            yes_price = self._clob_ws_yes
            no_price = self._clob_ws_no
            spread = abs(1.0 - yes_price - no_price)
            self._clob_ok = True
            self._clob_last_poll_ok_ts = time.time()
            return (yes_price, no_price, spread)

        # WS stale or not connected — fall back to REST
        if self._clob_ws_connected and self._clob_ws_last_msg > 0:
            age = time.time() - self._clob_ws_last_msg
            if age > 30.0:
                log_event(logger, "clob_ws_stale", f"CLOB WS data is {age:.0f}s old — falling back to REST")
        elif self._clob_ws_connected and not self._clob_ws_prices_valid:
            log_event(logger, "clob_ws_stale_skip",
                f"[CLOB/WS] connected but prices not yet valid post-reconnect — falling back to REST")

        return await self._poll_clob_rest(yes_token, no_token)

    async def _poll_clob_rest(self, yes_token, no_token):
        """REST fallback for CLOB prices — single combined midpoints call."""
        try:
            # Try combined midpoints endpoint (1 call instead of 2)
            if self._clob_http_session:
                result = await self._try_midpoints_combined(yes_token, no_token)
                if result:
                    return result

            # Fallback: individual midpoint calls via py_clob_client
            if self._polymarket:
                loop = asyncio.get_event_loop()
                yes_future = loop.run_in_executor(None, self._get_clob_price_with_log, yes_token, "UP")
                no_future = loop.run_in_executor(None, self._get_clob_price_with_log, no_token, "DOWN")
                try:
                    yes_price, no_price = await asyncio.wait_for(
                        asyncio.gather(yes_future, no_future), timeout=2.0,
                    )
                except asyncio.TimeoutError:
                    self._clob_ok = False
                    log_event(logger, "clob_rest_timeout",
                              "[CLOB/REST] Individual midpoint calls exceeded 2s — giving up", level=30)
                    return (0.0, 0.0, 1.0)
                log_event(logger, "clob_rest_individual",
                          f"[CLOB/REST] Individual: UP={yes_price:.4f} DOWN={no_price:.4f}")
                spread = abs(1.0 - yes_price - no_price)
                self._clob_ok = True
                self._clob_last_poll_ok_ts = time.time()
                return (yes_price, no_price, spread)

            # Last fallback: Gamma outcomePrices
            yes_price = 0.50
            no_price = 0.50
            market_data = self._current_market
            if market_data:
                prices = market_data.get("outcomePrices", "")
                log_event(logger, "clob_fallback", f"No wallet, using outcomePrices: {prices}")
                if isinstance(prices, str):
                    try:
                        prices = json.loads(prices)
                    except (json.JSONDecodeError, TypeError):
                        prices = []
                if isinstance(prices, list) and len(prices) >= 2:
                    yes_price = float(prices[0])
                    no_price = float(prices[1])

            spread = abs(1.0 - yes_price - no_price)
            self._clob_ok = True
            return (yes_price, no_price, spread)
        except Exception as exc:
            self._clob_ok = False
            log_event(logger, "clob_error", f"CLOB poll failed: {exc}", level=40)
            return (0.0, 0.0, 1.0)

    async def _try_midpoints_combined(self, yes_token, no_token):
        """Fetch midpoints for both tokens in parallel via /midpoint endpoint."""
        base = "https://clob.polymarket.com/midpoint"
        try:
            async def _fetch_one(token_id, label):
                url = f"{base}?token_id={token_id}"
                try:
                    async with self._clob_http_session.get(
                        url, timeout=aiohttp.ClientTimeout(total=1.5),
                    ) as resp:
                        if resp.status != 200:
                            log_event(logger, "clob_rest_http",
                                      f"[CLOB/REST] midpoint HTTP {resp.status} for {label} {token_id[:16]}...", level=30)
                            return 0.0
                        data = await resp.json(content_type=None)
                        log_event(logger, "clob_rest_raw",
                                  f"[CLOB/REST] midpoint {label} raw: {data}", level=10)
                        if isinstance(data, dict):
                            val = data.get("mid") or data.get("price") or data.get("midpoint")
                            try:
                                return float(val) if val is not None else 0.0
                            except (TypeError, ValueError):
                                return 0.0
                        elif isinstance(data, (str, int, float)):
                            try:
                                return float(data)
                            except (TypeError, ValueError):
                                return 0.0
                        return 0.0
                except asyncio.TimeoutError:
                    log_event(logger, "clob_rest_timeout",
                              f"[CLOB/REST] midpoint timeout for {label} {token_id[:16]}...", level=30)
                    return 0.0

            yes_price, no_price = await asyncio.gather(
                _fetch_one(yes_token, "UP"),
                _fetch_one(no_token, "DOWN"),
            )
            if yes_price > 0 and no_price > 0:
                log_event(logger, "clob_rest_prices",
                          f"[CLOB/REST] UP={yes_price:.4f} DOWN={no_price:.4f}")
                spread = abs(1.0 - yes_price - no_price)
                self._clob_ok = True
                self._clob_last_poll_ok_ts = time.time()
                return (yes_price, no_price, spread)
            log_event(logger, "clob_rest_bad",
                      f"[CLOB/REST] Partial midpoint: UP={yes_price} DOWN={no_price}", level=30)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log_event(logger, "clob_rest_error",
                      f"[CLOB/REST] midpoint failed: {e}", level=30)
        return None

    @staticmethod
    def _parse_midpoints(data, yes_token, no_token):
        """Parse midpoints response — handles multiple known formats."""
        yes_price = 0.0
        no_price = 0.0
        try:
            for token, label in [(yes_token, "yes"), (no_token, "no")]:
                raw = data.get(token)
                if raw is None:
                    continue
                if isinstance(raw, dict):
                    val = raw.get("mid") or raw.get("price") or raw.get("midpoint")
                    price = float(val) if val is not None else 0.0
                elif isinstance(raw, (str, int, float)):
                    price = float(raw)
                else:
                    price = 0.0
                if label == "yes":
                    yes_price = price
                else:
                    no_price = price
        except (ValueError, TypeError, KeyError):
            pass
        return yes_price, no_price

    def _get_clob_price_with_log(self, token_id, label):
        """Fetch CLOB midpoint price for a token and log the raw response."""
        try:
            raw_mid = self._polymarket.client.get_midpoint(token_id)
            log_event(logger, "clob_raw", f"CLOB {label} raw response: {raw_mid} (type={type(raw_mid).__name__})")
            if isinstance(raw_mid, dict):
                price = float(raw_mid.get('mid') or raw_mid.get('price') or raw_mid.get('midpoint') or 0)
            else:
                price = float(raw_mid)
            return price
        except Exception as exc:
            log_event(logger, "clob_price_error", f"CLOB {label} midpoint failed: {exc}")
            return 0.0

    async def _fetch_depth(self, token_id):
        """FIX 2: Fetch CLOB depth for deterministic gate.

        Returns -1.0 when depth cannot be measured (no wallet, API error)
        so the signal evaluator can skip the depth gate instead of blocking.
        Results are cached for 4s — CLOB depth changes on the order of
        seconds so this eliminates ~9 of every 10 get_order_book calls
        during the 100ms-tick entry window.
        """
        if not self._polymarket:
            return -1.0
        cached = self._depth_cache.get(token_id)
        if cached and (time.time() - cached["ts"]) < 4.0:
            return cached["depth"]
        loop = asyncio.get_event_loop()
        book = None
        try:
            book = await loop.run_in_executor(
                None, self._polymarket.client.get_order_book, token_id,
            )
            depth = compute_clob_depth(book, "buy")
            self._depth_cache[token_id] = {"depth": depth, "ts": time.time()}
            log_event(logger, "clob_depth_fetched", f"Depth for {token_id[:16]}...: {depth:.1f}")
            return depth
        except Exception as exc:
            book_info = f"type={type(book).__name__}, attrs={[a for a in dir(book) if not a.startswith('_')]}" if book else "None"
            log_event(logger, "clob_depth_error", f"Depth fetch failed: {exc} | book: {book_info}", level=30)
            return -1.0

    async def _get_clob_depth(self, token_id):
        """Get CLOB depth summary: top-of-book + depth within $0.05 per side."""
        if not self._polymarket:
            return ""
        loop = asyncio.get_event_loop()
        try:
            book = await loop.run_in_executor(
                None, self._polymarket.client.get_order_book, token_id,
            )
            # Support both OrderBookSummary (attribute) and dict access
            bids = book.bids if hasattr(book, 'bids') else book.get("bids", [])
            asks = book.asks if hasattr(book, 'asks') else book.get("asks", [])

            def _price(entry):
                return float(entry.price if hasattr(entry, 'price') else entry["price"])

            def _size(entry):
                return float(entry.size if hasattr(entry, 'size') else entry["size"])

            best_bid = _price(bids[0]) if bids else 0.0
            best_bid_size = _size(bids[0]) if bids else 0.0
            best_ask = _price(asks[0]) if asks else 0.0
            best_ask_size = _size(asks[0]) if asks else 0.0

            bid_depth = sum(_size(b) for b in bids if best_bid - _price(b) <= 0.05)
            ask_depth = sum(_size(a) for a in asks if _price(a) - best_ask <= 0.05)

            return (
                f"Best bid: {best_bid:.4f} (size {best_bid_size:.1f}) | "
                f"Best ask: {best_ask:.4f} (size {best_ask_size:.1f})\n"
                f"Bid depth (within $0.05): {bid_depth:.1f} | "
                f"Ask depth (within $0.05): {ask_depth:.1f}"
            )
        except Exception as exc:
            log_event(logger, "clob_depth_error", f"Depth summary failed: {exc} | book type={type(book).__name__}, attrs={dir(book)[:10]}", level=30)
            return ""
