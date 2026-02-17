"""
Polymarket CLOB WebSocket Client
Block E - Market Data WebSocket
"""

import json
import time
import asyncio
import websockets
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import threading
import logging

logger = logging.getLogger(__name__)


class WSEventType(Enum):
    """WebSocket event types"""
    QUOTE = "quote"
    TRADE = "trade"
    ORDERBOOK_SNAPSHOT = "orderbook_snapshot"
    ORDERBOOK_DELTA = "orderbook_delta"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


@dataclass
class Quote:
    """Normalized quote event"""
    market_id: str
    best_bid: float
    best_ask: float
    bid_size: float
    ask_size: float
    timestamp: float = field(default_factory=time.time)
    
    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid
    
    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2


@dataclass
class Trade:
    """Normalized trade event"""
    market_id: str
    price: float
    size: float
    side: str  # "buy" or "sell"
    timestamp: float = field(default_factory=time.time)


@dataclass
class WSHealth:
    """WebSocket health status"""
    connected: bool = False
    last_message_age_s: float = float('inf')
    active_subscriptions: int = 0
    messages_received: int = 0
    reconnects: int = 0
    last_error: Optional[str] = None


class PolymarketWSClient:
    """
    Polymarket CLOB WebSocket Client
    
    Connects to Polymarket's WebSocket feed for real-time market data.
    Normalizes events into Quote, Trade, Orderbook structures.
    """
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    def __init__(
        self,
        on_quote: Optional[Callable[[Quote], None]] = None,
        on_trade: Optional[Callable[[Trade], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        reconnect_interval: float = 5.0,
        heartbeat_interval: float = 30.0
    ):
        self.on_quote = on_quote
        self.on_trade = on_trade
        self.on_error = on_error
        
        self.reconnect_interval = reconnect_interval
        self.heartbeat_interval = heartbeat_interval
        
        # Connection state
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._running = False
        
        # In-memory state
        self._latest_quotes: Dict[str, Quote] = {}
        self._subscriptions: set = set()
        
        # Health tracking
        self._health = WSHealth()
        self._last_message_time: float = 0
        self._message_count = 0
        self._reconnect_count = 0
        
        # Threading
        self._lock = threading.RLock()
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
    
    @property
    def health(self) -> WSHealth:
        """Get current health status"""
        with self._lock:
            age = time.time() - self._last_message_time if self._last_message_time > 0 else float('inf')
            return WSHealth(
                connected=self._connected,
                last_message_age_s=age,
                active_subscriptions=len(self._subscriptions),
                messages_received=self._message_count,
                reconnects=self._reconnect_count,
                last_error=self._health.last_error
            )
    
    def get_latest_quote(self, market_id: str) -> Optional[Quote]:
        """Get latest quote for a market"""
        with self._lock:
            return self._latest_quotes.get(market_id)
    
    def start(self):
        """Start WebSocket client in background thread"""
        if self._running:
            logger.warning("WebSocket client already running")
            return
        
        self._running = True
        self._ws_thread = threading.Thread(target=self._run, daemon=True)
        self._ws_thread.start()
        logger.info("WebSocket client started")
    
    def stop(self):
        """Stop WebSocket client"""
        self._running = False
        
        if self._ws:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._event_loop)
        
        if self._ws_thread:
            self._ws_thread.join(timeout=5)
        
        logger.info("WebSocket client stopped")
    
    def subscribe(self, market_id: str):
        """Subscribe to a market"""
        with self._lock:
            self._subscriptions.add(market_id)
        
        if self._ws and self._connected:
            msg = {
                "type": "subscribe",
                "market": market_id
            }
            asyncio.run_coroutine_threadsafe(
                self._ws.send(json.dumps(msg)),
                self._event_loop
            )
        
        logger.info(f"Subscribed to {market_id}")
    
    def unsubscribe(self, market_id: str):
        """Unsubscribe from a market"""
        with self._lock:
            self._subscriptions.discard(market_id)
            self._latest_quotes.pop(market_id, None)
        
        if self._ws and self._connected:
            msg = {
                "type": "unsubscribe",
                "market": market_id
            }
            asyncio.run_coroutine_threadsafe(
                self._ws.send(json.dumps(msg)),
                self._event_loop
            )
        
        logger.info(f"Unsubscribed from {market_id}")
    
    def _run(self):
        """Main WebSocket loop (runs in separate thread)"""
        self._event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._event_loop)
        
        while self._running:
            try:
                self._event_loop.run_until_complete(self._connect_and_listen())
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                with self._lock:
                    self._health.last_error = str(e)
                
                if self.on_error:
                    self.on_error(e)
            
            if self._running:
                logger.info(f"Reconnecting in {self.reconnect_interval}s...")
                time.sleep(self.reconnect_interval)
                with self._lock:
                    self._reconnect_count += 1
        
        # Clean up event loop
        if self._event_loop:
            self._event_loop.close()
    
    async def _connect_and_listen(self):
        """Connect and listen to WebSocket"""
        logger.info(f"Connecting to {self.WS_URL}")
        
        async with websockets.connect(self.WS_URL, ping_interval=20, ping_timeout=10) as ws:
            with self._lock:
                self._ws = ws
                self._connected = True
            
            # Resubscribe to all markets
            with self._lock:
                subs = list(self._subscriptions)
            
            for market_id in subs:
                await ws.send(json.dumps({
                    "type": "subscribe",
                    "market": market_id
                }))
            
            logger.info(f"Connected, subscribed to {len(subs)} markets")
            
            # Listen for messages
            async for message in ws:
                if not self._running:
                    break
                
                await self._handle_message(message)
            
            # Connection closed or broken
            with self._lock:
                self._connected = False
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "unknown")
            
            with self._lock:
                self._message_count += 1
                self._last_message_time = time.time()
            
            if msg_type == "quote":
                self._handle_quote(data)
            elif msg_type == "trade":
                self._handle_trade(data)
            elif msg_type == "orderbook":
                self._handle_orderbook(data)
            elif msg_type == "heartbeat":
                pass  # Just update last_message_time
            else:
                logger.debug(f"Unknown message type: {msg_type}")
        
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    def _handle_quote(self, data: dict):
        """Handle quote event"""
        try:
            market_id = data.get("market", "")
            
            quote = Quote(
                market_id=market_id,
                best_bid=float(data.get("bid", 0)),
                best_ask=float(data.get("ask", 0)),
                bid_size=float(data.get("bidSize", 0)),
                ask_size=float(data.get("askSize", 0)),
                timestamp=time.time()
            )
            
            with self._lock:
                self._latest_quotes[market_id] = quote
                # Limit memory usage - keep only subscribed markets
                if len(self._latest_quotes) > 1000:
                    # Remove quotes for unsubscribed markets
                    for mid in list(self._latest_quotes.keys()):
                        if mid not in self._subscriptions:
                            del self._latest_quotes[mid]
                            break
            
            if self.on_quote:
                self.on_quote(quote)
        
        except Exception as e:
            logger.error(f"Error handling quote: {e}")
    
    def _handle_trade(self, data: dict):
        """Handle trade event"""
        try:
            trade = Trade(
                market_id=data.get("market", ""),
                price=float(data.get("price", 0)),
                size=float(data.get("size", 0)),
                side=data.get("side", ""),
                timestamp=time.time()
            )
            
            if self.on_trade:
                self.on_trade(trade)
        
        except Exception as e:
            logger.error(f"Error handling trade: {e}")
    
    def _handle_orderbook(self, data: dict):
        """Handle orderbook event"""
        # Will be implemented in Block F
        pass


# Singleton instance
_ws_client: Optional[PolymarketWSClient] = None

def get_ws_client() -> PolymarketWSClient:
    """Get or create singleton WebSocket client"""
    global _ws_client
    if _ws_client is None:
        _ws_client = PolymarketWSClient()
    return _ws_client
