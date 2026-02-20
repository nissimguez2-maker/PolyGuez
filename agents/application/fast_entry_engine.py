"""
Fast Entry Engine for Polymarket 15-minute crypto markets.

Low-latency dislocation detection and immediate entry execution.
Designed for millisecond-precision timing and minimal overhead.
"""
import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any, List
from datetime import datetime, timezone
import json
import httpx

from agents.polymarket.polymarket import Polymarket
from agents.application.position_manager import PositionManager, ActiveTrade, TradeAction
from agents.application.latency_stats import LatencyStats
from src.utils.logger import get_logger
from src.utils.exceptions import APIError, BotError
from src.config.settings import get_settings
from src.timeframes import floor_time, window_bounds, seconds_from_start, seconds_to_end

# Type hint for WebSocket update (avoid circular import)
if False:  # TYPE_CHECKING equivalent
    from agents.polymarket.websocket_client import OrderBookUpdate

logger = get_logger(__name__)
settings = get_settings()


@dataclass
class PriceSnapshot:
    """Price snapshot with millisecond timestamp."""
    timestamp_ms: int
    price: float
    best_bid: float
    best_ask: float
    mid_price: float


@dataclass
class DislocationSignal:
    """Detected dislocation signal."""
    timestamp_ms: int
    token_id: str
    side: str  # "UP" or "DOWN"
    price_drop_pct: float
    speed_ratio: float
    current_price: float
    baseline_price: float
    window_ms: int
    t_detect_ms: Optional[float] = None  # Monotonic timestamp when detected


@dataclass
class Leg1Entry:
    """Leg 1 entry execution record."""
    entry_id: str
    timestamp_ms: int
    token_id: str
    side: str
    size_usdc: float
    price: float
    order_id: Optional[str] = None
    status: str = "PENDING"  # PENDING, FILLED, FAILED
    # Latency timestamps (monotonic, milliseconds)
    t_detect_ms: Optional[float] = None  # Dislocation detected
    t_order_send_ms: Optional[float] = None  # Order sent
    t_order_ack_ms: Optional[float] = None  # Order acknowledged/filled
    # Market info
    market_id: Optional[str] = None


class FastEntryEngine:
    """
    Fast Entry Engine for detecting and executing on price dislocations.
    
    Architecture:
    - Async event-driven price monitoring
    - Sliding window dislocation detection
    - Immediate small-size entry (Leg 1)
    - Hooks for confirmation system integration
    """
    
    def __init__(
        self,
        polymarket: Polymarket,
        position_manager: Optional[PositionManager] = None,
        # Detection parameters
        window_ms: int = 2000,  # 2 second sliding window
        drop_threshold_pct: float = 2.0,  # 2% drop triggers
        speed_ratio_threshold: float = 1.5,  # Realized vs expected move
        # Execution parameters
        leg1_size_usdc: float = 1.0,  # Small initial size
        poll_interval_ms: int = 100,  # 100ms polling (10 Hz) - fallback if WebSocket not used
        # Market filter
        market_prefix: str = "btc-updown-15m",
        # Confirmation timeout
        confirmation_timeout_seconds: int = 30,
        # WebSocket (optional, for lower latency)
        use_websocket: bool = False,  # Enable WebSocket for real-time updates
    ):
        self.polymarket = polymarket
        # Use CONFIRM_TTL_SECONDS from settings if not provided
        timeout = confirmation_timeout_seconds or settings.CONFIRM_TTL_SECONDS
        self.position_manager = position_manager or PositionManager(
            default_timeout_seconds=timeout
        )
        self.window_ms = window_ms
        self.drop_threshold_pct = drop_threshold_pct
        self.speed_ratio_threshold = speed_ratio_threshold
        self.leg1_size_usdc = leg1_size_usdc
        self.poll_interval_ms = poll_interval_ms
        # Determine timeframe from settings (default 15)
        tf = getattr(settings, "BTC_UPDOWN_TIMEFRAME_MINUTES", 15)
        if tf == 5 and not getattr(settings, "BTC_UPDOWN_ENABLE_5M", True):
            logger.warning("5m timeframe disabled via settings; falling back to 15m")
            tf = 15
        self.timeframe_min = int(tf)
        self.market_prefix = f"btc-updown-{self.timeframe_min}m"
        self.confirmation_timeout_seconds = confirmation_timeout_seconds
        self.use_websocket = use_websocket
        
        # WebSocket client (optional)
        self.ws_client = None
        if self.use_websocket:
            try:
                from agents.polymarket.websocket_client import PolymarketWebSocketClient, WEBSOCKETS_AVAILABLE
                if WEBSOCKETS_AVAILABLE:
                    self.ws_client = PolymarketWebSocketClient()
                else:
                    logger.warning("websockets library not available, falling back to REST polling")
                    self.use_websocket = False
            except ImportError as e:
                logger.warning(f"WebSocket client not available ({e}), falling back to REST polling")
                self.use_websocket = False
        
        # State
        self.price_history: Dict[str, deque] = {}  # token_id -> deque of PriceSnapshot
        self.active_entries: Dict[str, Leg1Entry] = {}  # entry_id -> Leg1Entry
        self.running = False
        
        # Hooks for confirmation system
        self.on_dislocation_detected: Optional[Callable[[DislocationSignal], None]] = None
        self.on_leg1_filled: Optional[Callable[[Leg1Entry], None]] = None
        self.on_leg1_failed: Optional[Callable[[Leg1Entry, str], None]] = None
        
        # Statistics
        self.stats = {
            "price_updates": 0,
            "dislocations_detected": 0,
            "leg1_entries": 0,
            "leg1_filled": 0,
            "leg1_failed": 0,
        }
        
        # Latency tracking
        self.latency_stats = LatencyStats(window_size=100)
        self.stats_log_interval = 50  # Log rolling stats every 50 trades
    
    def _now_ms(self) -> int:
        """Get current timestamp in milliseconds (wall clock)."""
        return int(time.time() * 1000)
    
    def _monotonic_ms(self) -> float:
        """Get monotonic timestamp in milliseconds (for latency measurements)."""
        return time.monotonic() * 1000.0
    
    def _log_ms(self, event: str, data: Dict[str, Any]) -> None:
        """Log with millisecond precision."""
        timestamp_ms = self._now_ms()
        log_entry = {
            "ts_ms": timestamp_ms,
            "event": event,
            **data
        }
        logger.info(f"[FAST_ENTRY] {json.dumps(log_entry)}")
    
    async def _fetch_price(self, token_id: str) -> Optional[PriceSnapshot]:
        """
        Fetch current price snapshot for a token.
        
        Optimized: Only one API call (get_orderbook) instead of two.
        OrderBook contains all needed price information.
        """
        try:
            # Single API call: get_orderbook contains bids/asks with prices
            orderbook = self.polymarket.get_orderbook(token_id)
            
            # Extract best bid/ask from orderbook
            best_bid = float(orderbook.bids[0].price) if orderbook.bids else None
            best_ask = float(orderbook.asks[0].price) if orderbook.asks else None
            
            # Calculate mid price
            # NOTE: Use explicit None checks, not truthiness (0.0 is a valid price!)
            if best_bid is not None and best_ask is not None:
                mid_price = (best_bid + best_ask) / 2.0
                price = mid_price  # Use mid price as reference
            elif best_bid is not None:
                price = best_bid
                mid_price = best_bid
            elif best_ask is not None:
                price = best_ask
                mid_price = best_ask
            else:
                # Fallback: try to get price if orderbook is empty
                try:
                    price = self.polymarket.get_orderbook_price(token_id)
                    mid_price = price
                except:
                    logger.warning(f"Empty orderbook for {token_id[:16]}...")
                    return None
            
            return PriceSnapshot(
                timestamp_ms=self._now_ms(),
                price=price,
                best_bid=best_bid or price,
                best_ask=best_ask or price,
                mid_price=mid_price,
            )
        except Exception as e:
            logger.error(f"Price fetch error for {token_id}: {e}")
            return None
    
    def _update_price_history(self, token_id: str, snapshot: PriceSnapshot) -> None:
        """Update sliding window price history."""
        if token_id not in self.price_history:
            self.price_history[token_id] = deque(maxlen=1000)  # Max 1000 snapshots
        
        history = self.price_history[token_id]
        history.append(snapshot)
        
        # Remove old entries outside window
        cutoff_ms = snapshot.timestamp_ms - self.window_ms
        while history and history[0].timestamp_ms < cutoff_ms:
            history.popleft()
    
    def _detect_dislocation(self, token_id: str) -> Optional[DislocationSignal]:
        """
        Detect price dislocation using sliding window.
        
        Returns DislocationSignal if:
        - Price dropped by drop_threshold_pct within window_ms
        - Speed ratio (realized/expected) exceeds threshold
        """
        if token_id not in self.price_history:
            return None
        
        history = self.price_history[token_id]
        if len(history) < 2:
            return None
        
        current = history[-1]
        baseline = history[0]  # Oldest in window
        
        # Avoid division by zero if baseline mid_price is zero (valid but rare for probability prices).
        # If baseline is zero we cannot compute a meaningful percentage drop, so skip detection.
        if baseline.mid_price <= 0.0:
            logger.debug(f"Baseline mid_price is zero for {token_id}, skipping dislocation detection")
            return None

        # Calculate price drop percentage
        price_drop_pct = ((baseline.mid_price - current.mid_price) / baseline.mid_price) * 100.0
        
        if price_drop_pct < self.drop_threshold_pct:
            return None  # Not enough drop
        
        # Calculate speed ratio
        time_elapsed_ms = current.timestamp_ms - baseline.timestamp_ms
        if time_elapsed_ms == 0:
            return None
        
        expected_move_pct = (time_elapsed_ms / 1000.0) * 0.1  # Assume 0.1% per second baseline
        realized_move_pct = abs(price_drop_pct)
        speed_ratio = realized_move_pct / max(expected_move_pct, 0.01)  # Avoid division by zero
        
        if speed_ratio < self.speed_ratio_threshold:
            return None  # Not fast enough
        
        # Determine side: if price dropped, buy (expecting bounce).
        # Use price movement only — do not rely on substring matches in token_id,
        # which may produce false positives (e.g. token IDs containing "up" in other words).
        side = "UP" if current.mid_price < baseline.mid_price else "DOWN"
        
        t_detect = self._monotonic_ms()
        
        signal = DislocationSignal(
            timestamp_ms=current.timestamp_ms,
            token_id=token_id,
            side=side,
            price_drop_pct=price_drop_pct,
            speed_ratio=speed_ratio,
            current_price=current.mid_price,
            baseline_price=baseline.mid_price,
            window_ms=time_elapsed_ms,
        )
        
        # Store detection time in signal for later use
        signal.t_detect_ms = t_detect
        
        self.stats["dislocations_detected"] += 1
        self._log_ms("DISLOCATION_DETECTED", {
            "token_id": token_id,
            "side": side,
            "drop_pct": round(price_drop_pct, 3),
            "speed_ratio": round(speed_ratio, 3),
            "current_price": round(current.mid_price, 6),
            "baseline_price": round(baseline.mid_price, 6),
            "t_detect_ms": round(t_detect, 3),
        })
        
        return signal
    
    async def _execute_leg1(self, signal: DislocationSignal) -> Optional[Leg1Entry]:
        """
        Execute immediate small-size entry (Leg 1) with precise latency measurement.
        
        Optimized: Pre-computed risk checks can be done in parallel with market_id fetch.
        """
        entry_id = f"leg1_{signal.timestamp_ms}_{signal.token_id[:8]}"
        
        # t_detect from signal
        t_detect = signal.t_detect_ms if hasattr(signal, 't_detect_ms') and signal.t_detect_ms else self._monotonic_ms()
        
        # Timing gates: check entry deadline & min time to end for configured timeframe
        try:
            from src.config.settings import get_settings as _get_settings
            _settings = _get_settings()
            entry_deadline = int(getattr(_settings, "BTC_UPDOWN_ENTRY_DEADLINE_SECONDS", 60))
            min_time_to_end = int(getattr(_settings, "BTC_UPDOWN_MIN_TIME_TO_END_SECONDS", 30))
            auto_close_buffer = int(getattr(_settings, "BTC_UPDOWN_AUTO_CLOSE_BUFFER_SECONDS", 15))
        except Exception:
            entry_deadline = 60
            min_time_to_end = 30
            auto_close_buffer = 15

        from datetime import datetime, timezone
        now_dt = datetime.now(timezone.utc)
        s_from_start = seconds_from_start(now_dt, self.timeframe_min)
        s_to_end = seconds_to_end(now_dt, self.timeframe_min)
        # Log timing context
        logger.info(f"Entry timing: timeframe={self.timeframe_min}m start_offset_s={s_from_start} to_end_s={s_to_end} token={signal.token_id[:16]}")

        if s_from_start > entry_deadline:
            logger.info(f"Entry blocked by deadline: token={signal.token_id[:16]} timeframe={self.timeframe_min}m seconds_from_start={s_from_start} deadline={entry_deadline}")
            return None

        if s_to_end < min_time_to_end:
            logger.info(f"Entry blocked too close to window end: token={signal.token_id[:16]} timeframe={self.timeframe_min}m seconds_to_end={s_to_end} min_required={min_time_to_end}")
            return None

        # Pre-compute risk checks in parallel (if risk manager available)
        # This can be done while fetching market_id to save time
        risk_checks_passed = True
        try:
            from webhook_server_fastapi import get_risk_manager, get_position_manager
            rm = get_risk_manager()
            pm = get_position_manager()
            
            # Quick exposure check (non-blocking, can run in parallel)
            exposure_check = rm.check_exposure(
                proposed_trade_size=self.leg1_size_usdc,
                active_trades=pm.active_trades,
            )
            if not exposure_check.allowed:
                logger.warning(f"Leg1 entry skipped: {exposure_check.reason}")
                risk_checks_passed = False
            
            # Direction limit check
            direction_allowed, _ = rm.check_direction_limit(
                side=signal.side,
                active_trades=pm.active_trades,
            )
            if not direction_allowed:
                logger.warning(f"Leg1 entry skipped: direction limit")
                risk_checks_passed = False
        except Exception as e:
            # If risk manager not available, continue (for standalone FastEntryEngine)
            logger.debug(f"Risk checks skipped (not available): {e}")
        
        if not risk_checks_passed:
            return None
        
        # Get market_id from token (async to avoid blocking)
        market_id = None
        try:
            # Use existing get_market method
            market = self.polymarket.get_market(signal.token_id)
            if market:
                market_id = str(getattr(market, 'id', None) if hasattr(market, 'id') else None)
        except Exception as e:
            logger.debug(f"Could not fetch market_id for {signal.token_id}: {e}")
        
        entry = Leg1Entry(
            entry_id=entry_id,
            timestamp_ms=self._now_ms(),
            token_id=signal.token_id,
            side=signal.side,
            size_usdc=self.leg1_size_usdc,
            price=signal.current_price,
            t_detect_ms=t_detect,
            market_id=market_id,
        )
        
        self.active_entries[entry_id] = entry
        self.stats["leg1_entries"] += 1
        
        # Measure t_order_send (just before sending)
        t_order_send = self._monotonic_ms()
        entry.t_order_send_ms = t_order_send
        
        self._log_ms("LEG1_ENTRY_ATTEMPT", {
            "entry_id": entry_id,
            "token_id": signal.token_id,
            "side": signal.side,
            "size_usdc": self.leg1_size_usdc,
            "price": round(signal.current_price, 6),
            "market_id": market_id,
            "t_detect_ms": round(t_detect, 3),
            "t_order_send_ms": round(t_order_send, 3),
        })
        
        try:
            # Execute market order
            # Check central entry gates before sending order
            try:
                from agents.application.risk_manager import get_settings as _rm_get_settings  # noqa: F401
            except Exception:
                pass
            try:
                from agents.application.risk_manager import RiskManager
                rm = get_risk_manager() if 'get_risk_manager' in globals() else None
            except Exception:
                rm = None

            entry_allowed = True
            entry_reason = "ok"
            entry_details = {}
            try:
                # Attempt to use global risk manager if available
                from webhook_server_fastapi import get_risk_manager
                rm = get_risk_manager()
            except Exception:
                pass

            # Use central OrderExecutor to enforce gate
            try:
                from src.order_executor import place_entry_order_with_gate
                res = place_entry_order_with_gate(
                    polymarket=self.polymarket,
                    token_id=signal.token_id,
                    price=signal.current_price,
                    size=self.leg1_size_usdc,
                    side="BUY",
                    confidence=None,
                    market_quality_healthy=None,
                    adapter=self.polymarket,
                )
                if not res.get("allowed", False):
                    logger.info(f"LEG1_ENTRY_BLOCKED {signal.token_id[:16]} reason={res.get('reason')} details={res.get('details')}")
                    return None
                order_id = res.get("order_id")
            except Exception as e:
                logger.error(f"OrderExecutor failed: {e}")
                return None
            
            # Measure t_order_ack (immediately after receiving order_id)
            t_order_ack = self._monotonic_ms()
            entry.t_order_ack_ms = t_order_ack
            entry.order_id = order_id
            entry.status = "FILLED"
            
            # Mark ACK source (simulated in DRY_RUN, real in LIVE)
            ack_source = "simulated" if settings.DRY_RUN else "real"
            
            # Calculate latency metrics
            detect_to_send_ms = t_order_send - t_detect
            send_to_ack_ms = t_order_ack - t_order_send
            detect_to_ack_ms = t_order_ack - t_detect
            
            # Record latency stats
            self.latency_stats.record(detect_to_send_ms, send_to_ack_ms, detect_to_ack_ms)
            
            self.stats["leg1_filled"] += 1
            
            # Log rolling stats every N trades
            if self.stats["leg1_filled"] % self.stats_log_interval == 0:
                self.latency_stats.log_stats(self.stats["leg1_filled"])
            
            # Create active trade with position lock
            active_trade = None
            if market_id:
                # Compute confirmation timeout relative to window end
                ttl = max(0, s_to_end - auto_close_buffer)
                if ttl <= 0:
                    logger.info(f"Not creating trade: TTL <= 0 for token {signal.token_id[:16]} timeframe={self.timeframe_min}m ttl={ttl}")
                else:
                    active_trade = self.position_manager.create_trade(
                        market_id=market_id,
                        token_id=signal.token_id,
                        side=signal.side,
                        leg1_size=self.leg1_size_usdc,
                        leg1_price=signal.current_price,
                        leg1_entry_id=entry_id,
                        timeout_seconds=int(ttl),
                    )
                
                if active_trade:
                    # Store latency metrics in trade
                    active_trade.detect_to_send_ms = detect_to_send_ms
                    active_trade.send_to_ack_ms = send_to_ack_ms
                    active_trade.detect_to_ack_ms = detect_to_ack_ms
                else:
                    logger.warning(
                        f"Could not create trade for market {market_id} "
                        f"(market locked or invalid)"
                    )
            
            # Log with all required fields + trade_id
            log_data = {
                "entry_id": entry_id,
                "order_id": order_id,
                "market_id": market_id,
                "side": signal.side,
                "price": round(signal.current_price, 6),
                "size": self.leg1_size_usdc,
                "t_detect_ms": round(t_detect, 3),
                "t_order_send_ms": round(t_order_send, 3),
                "t_order_ack_ms": round(t_order_ack, 3),
                "detect_to_send_ms": round(detect_to_send_ms, 3),
                "send_to_ack_ms": round(send_to_ack_ms, 3),
                "detect_to_ack_ms": round(detect_to_ack_ms, 3),
                # ACK source (simulated in DRY_RUN, real in LIVE)
                "ack_source": ack_source,
            }
            
            if active_trade:
                log_data["trade_id"] = active_trade.trade_id
                entry.market_id = market_id  # Store for later reference
            
            # Log to JSONL file (for analysis)
            from src.config.settings import is_paper_trading
            if is_paper_trading():
                try:
                    import os
                    log_file = os.path.join(os.path.dirname(__file__), "..", "..", "fast_entry_trades.jsonl")
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps(log_data, ensure_ascii=False) + "\n")
                except Exception as e:
                    logger.error(f"Failed to write to JSONL: {e}")
            
            self._log_ms("LEG1_FILLED", log_data)
            
            # Trigger hook with trade_id
            if self.on_leg1_filled:
                self.on_leg1_filled(entry)
            
            return entry
            
        except Exception as e:
            # Measure t_order_ack even on failure (for failed orders)
            t_order_ack = self._monotonic_ms()
            entry.t_order_ack_ms = t_order_ack
            entry.status = "FAILED"
            
            # Calculate latency metrics
            detect_to_send_ms = t_order_send - t_detect
            send_to_ack_ms = t_order_ack - t_order_send
            detect_to_ack_ms = t_order_ack - t_detect
            
            self.stats["leg1_failed"] += 1
            
            error_msg = str(e)
            
            # Log with all required fields even on failure
            self._log_ms("LEG1_FAILED", {
                "entry_id": entry_id,
                "error": error_msg,
                "market_id": market_id,
                "side": signal.side,
                "price": round(signal.current_price, 6),
                "size": self.leg1_size_usdc,
                "t_detect_ms": round(t_detect, 3),
                "t_order_send_ms": round(t_order_send, 3),
                "t_order_ack_ms": round(t_order_ack, 3),
                "detect_to_send_ms": round(detect_to_send_ms, 3),
                "send_to_ack_ms": round(send_to_ack_ms, 3),
                "detect_to_ack_ms": round(detect_to_ack_ms, 3),
            })
            
            # Trigger hook
            if self.on_leg1_failed:
                self.on_leg1_failed(entry, error_msg)
            
            return None
    
    async def _monitor_token(self, token_id: str) -> None:
        """Monitor a single token for dislocations."""
        while self.running:
            try:
                snapshot = await self._fetch_price(token_id)
                if snapshot:
                    self._update_price_history(token_id, snapshot)
                    self.stats["price_updates"] += 1
                    
                    # Check for dislocation
                    signal = self._detect_dislocation(token_id)
                    if signal:
                        # Trigger hook
                        if self.on_dislocation_detected:
                            self.on_dislocation_detected(signal)
                        
                        # Execute Leg 1 immediately
                        await self._execute_leg1(signal)
                
                await asyncio.sleep(self.poll_interval_ms / 1000.0)
                
            except Exception as e:
                logger.error(f"Monitor error for {token_id}: {e}")
                await asyncio.sleep(1.0)  # Back off on error
    
    async def _get_active_market_tokens(self) -> List[str]:
        """Get token IDs for active 15m markets."""
        try:
            # Fetch markets from Gamma API (use httpx directly)
            response = httpx.get(
                f"{self.polymarket.gamma_url}/markets",
                params={"active": "true", "closed": "false"},
                timeout=5
            )
            
            if response.status_code != 200:
                return []
            
            markets = response.json()
            tokens = []
            
            for market in markets:
                if not market.get("active", False):
                    continue
                
                # Filter by prefix in slug or question
                slug = market.get("slug", "").lower()
                question = market.get("question", "").lower()
                
                if self.market_prefix not in slug and self.market_prefix not in question:
                    continue
                
                # Extract token IDs
                clob_ids = market.get("clobTokenIds")
                if isinstance(clob_ids, str):
                    try:
                        clob_ids = json.loads(clob_ids)
                    except:
                        continue
                
                if isinstance(clob_ids, list) and len(clob_ids) >= 2:
                    tokens.extend([str(clob_ids[0]), str(clob_ids[1])])
            
            return tokens
            
        except Exception as e:
            logger.error(f"Error fetching active markets: {e}")
            return []
    
    async def _timeout_cleanup_task(self) -> None:
        """Background task to clean up timed out trades."""
        while self.running:
            try:
                await asyncio.sleep(5.0)  # Check every 5 seconds
                cleaned = self.position_manager.cleanup_timeout_trades()
                if cleaned > 0:
                    logger.info(f"Cleaned up {cleaned} timed out trades")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Timeout cleanup error: {e}")
    
    async def start(self) -> None:
        """Start the fast entry engine."""
        if self.running:
            logger.warning("Engine already running")
            return
        
        self.running = True
        logger.info("Fast Entry Engine starting...")
        
        # Get active market tokens
        tokens = await self._get_active_market_tokens()
        logger.info(f"Monitoring {len(tokens)} tokens")
        
        # Ensure cleanup_task is always defined so finally blocks can safely cancel it
        cleanup_task = None
        
        # WebSocket mode: use real-time updates
        if self.use_websocket and self.ws_client:
            logger.info("Using WebSocket for real-time price updates (lower latency)")
            
            # Define callback for WebSocket updates
            def on_ws_update(update: "OrderBookUpdate"):
                """Handle WebSocket orderbook update."""
                if update.mid_price:
                    snapshot = PriceSnapshot(
                        timestamp_ms=update.timestamp_ms,
                        price=update.mid_price,
                        best_bid=update.best_bid or update.mid_price,
                        best_ask=update.best_ask or update.mid_price,
                        mid_price=update.mid_price,
                    )
                    self._update_price_history(update.token_id, snapshot)
                    self.stats["price_updates"] += 1
                    
                    # Fast-exit evaluation for existing trades on this token
                    try:
                        trade = self.position_manager.get_trade_by_token(update.token_id)
                        if trade:
                            now_mon = self._monotonic_ms()/1000.0
                            # call evaluate_fast_exit with best_bid/best_ask
                            self.position_manager.evaluate_fast_exit(trade, snapshot.best_bid, snapshot.best_ask, now_monotonic=time.monotonic())
                    except Exception:
                        logger.debug("fast_exit evaluation failed for token %s", update.token_id[:8])

                    # Check for dislocation
                    signal = self._detect_dislocation(update.token_id)
                    if signal:
                        # Trigger hook
                        if self.on_dislocation_detected:
                            self.on_dislocation_detected(signal)
                        
                        # Execute Leg 1 immediately (fire and forget)
                        asyncio.create_task(self._execute_leg1(signal))
            
            # Start WebSocket client
            ws_task = asyncio.create_task(
                self.ws_client.start(tokens, on_ws_update)
            )
            
            # Start timeout cleanup task
            cleanup_task = asyncio.create_task(self._timeout_cleanup_task())
            
            try:
                await asyncio.gather(ws_task, cleanup_task)
            except asyncio.CancelledError:
                logger.info("Engine stopped")
            except Exception as e:
                logger.error(f"Engine error: {e}")
            finally:
                # Stop websocket client if running
                if self.ws_client:
                    try:
                        await self.ws_client.stop()
                    except Exception:
                        logger.exception("Error stopping ws_client")
                # Ensure cleanup task is cancelled
                if cleanup_task is not None:
                    cleanup_task.cancel()
                    try:
                        await cleanup_task
                    except asyncio.CancelledError:
                        pass
                self.running = False
        
        else:
            # REST polling mode (fallback)
            logger.info("Using REST API polling (100ms interval)")
            
            # Start monitoring tasks
            monitor_tasks = [self._monitor_token(token_id) for token_id in tokens]
            
            # Start timeout cleanup task
            cleanup_task = asyncio.create_task(self._timeout_cleanup_task())
            
            try:
                await asyncio.gather(*monitor_tasks, cleanup_task)
            except asyncio.CancelledError:
                logger.info("Engine stopped")
            except Exception as e:
                logger.error(f"Engine error: {e}")
            finally:
                self.running = False
                if cleanup_task is not None:
                    cleanup_task.cancel()
                    try:
                        await cleanup_task
                    except asyncio.CancelledError:
                        pass
    
    def stop(self) -> None:
        """Stop the engine."""
        self.running = False
        logger.info("Fast Entry Engine stopping...")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            **self.stats,
            "active_entries": len(self.active_entries),
            "monitored_tokens": len(self.price_history),
        }
    
    # Hooks for confirmation system (using trade_id)
    def add_size_by_trade_id(self, trade_id: str, additional_size_usdc: float) -> bool:
        """Add size to existing trade (called by confirmation system)."""
        trade = self.position_manager.get_trade(trade_id)
        if not trade:
            logger.warning(f"Trade {trade_id} not found")
            return False
        
        if trade.status.value not in ("PENDING", "ADDED"):
            logger.warning(f"Trade {trade_id} in status {trade.status.value}, cannot add size")
            return False
        
        try:
            # Execute market order
            self.polymarket.execute_order(
                price=trade.leg1_price,
                size=additional_size_usdc,
                side="BUY",
                token_id=trade.token_id,
            )

            # Update trade state via PositionManager to keep totals/idempotency consistent.
            # Generate a unique action_id for idempotency tracking.
            action_id = f"add_{trade_id}_{int(time.time() * 1000)}"
            try:
                result = self.position_manager.process_confirmation(
                    trade_id=trade_id,
                    action=TradeAction.ADD,
                    action_id=action_id,
                    additional_size=additional_size_usdc,
                )
            except Exception as e:
                logger.exception(f"PositionManager.process_confirmation failed for ADD on {trade_id}: {e}")
                result = {"ok": False, "message": str(e)}

            if not result.get("ok"):
                logger.warning(f"ADD processed but position update failed for {trade_id}: {result.get('message')}")

            # Refresh trade object (may have been mutated)
            trade = self.position_manager.get_trade(trade_id)

            self._log_ms("ADD_SIZE", {
                "trade_id": trade_id,
                "entry_id": trade.leg1_entry_id if trade else None,
                "additional_size_usdc": additional_size_usdc,
                "total_size": trade.total_size if trade else None,
                "status": trade.status.value if trade else None,
            })

            return True
        except Exception as e:
            logger.error(f"Add size failed: {e}")
            return False
    
    def hedge_by_trade_id(self, trade_id: str) -> bool:
        """Hedge existing position (called by confirmation system)."""
        trade = self.position_manager.get_trade(trade_id)
        if not trade:
            return False
        
        try:
            # Determine opposite token (simplified - would need proper lookup)
            opposite_side = "DOWN" if trade.side == "UP" else "UP"
            
            # Execute hedge order (simplified)
            self._log_ms("HEDGE", {
                "trade_id": trade_id,
                "entry_id": trade.leg1_entry_id,
                "original_side": trade.side,
                "hedge_side": opposite_side,
            })
            
            return True
        except Exception as e:
            logger.error(f"Hedge failed: {e}")
            return False
    
    def exit_by_trade_id(self, trade_id: str) -> bool:
        """Exit position (called by confirmation system)."""
        trade = self.position_manager.get_trade(trade_id)
        if not trade:
            return False
        
        try:
            # Execute exit order (simplified - would need to sell the position)
            self._log_ms("EXIT", {
                "trade_id": trade_id,
                "entry_id": trade.leg1_entry_id,
                "token_id": trade.token_id,
            })
            
            return True
        except Exception as e:
            logger.error(f"Exit failed: {e}")
            return False
    
    # Legacy methods (for backward compatibility)
    def add_size(self, entry_id: Optional[str] = None, additional_size_usdc: float = 0.0) -> bool:
        """Legacy: Add size (use add_size_by_trade_id instead)."""
        if entry_id:
            # Try to find trade by entry_id
            for trade_id, trade in self.position_manager.active_trades.items():
                if trade.leg1_entry_id == entry_id:
                    return self.add_size_by_trade_id(trade_id, additional_size_usdc)
        return False
    
    def hedge(self, entry_id: Optional[str] = None) -> bool:
        """Legacy: Hedge (use hedge_by_trade_id instead)."""
        if entry_id:
            for trade_id, trade in self.position_manager.active_trades.items():
                if trade.leg1_entry_id == entry_id:
                    return self.hedge_by_trade_id(trade_id)
        return False
    
    def exit(self, entry_id: Optional[str] = None) -> bool:
        """Legacy: Exit (use exit_by_trade_id instead)."""
        if entry_id:
            for trade_id, trade in self.position_manager.active_trades.items():
                if trade.leg1_entry_id == entry_id:
                    return self.exit_by_trade_id(trade_id)
        return False


async def main():
    """Example usage."""
    from dotenv import load_dotenv
    load_dotenv()
    
    polymarket = Polymarket()
    engine = FastEntryEngine(
        polymarket=polymarket,
        window_ms=2000,
        drop_threshold_pct=2.0,
        speed_ratio_threshold=1.5,
        leg1_size_usdc=1.0,
        poll_interval_ms=100,
    )
    
    # Set hooks
    def on_dislocation(signal: DislocationSignal):
        logger.info(f"Dislocation detected: {signal.side} @ {signal.current_price}")
    
    def on_filled(entry: Leg1Entry):
        logger.info(f"Leg 1 filled: {entry.entry_id}")
    
    engine.on_dislocation_detected = on_dislocation
    engine.on_leg1_filled = on_filled
    
    try:
        await engine.start()
    except KeyboardInterrupt:
        engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
