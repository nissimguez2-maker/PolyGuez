"""
Market Data Health Endpoint
Block E - Health monitoring for WebSocket and market data
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import json
import logging
import time
from typing import Dict, Any, Optional

from .providers.polymarket_ws import get_ws_client

logger = logging.getLogger(__name__)


class MarketDataHealthHandler(BaseHTTPRequestHandler):
    """HTTP handler for market data health endpoints"""
    
    def log_message(self, format, *args):
        """Suppress default logging"""
        pass
    
    def do_GET(self):
        """Handle GET requests"""
        if self.path == "/market-data/health":
            self._send_health_response()
        elif self.path == "/market-data/status":
            self._send_status_response()
        else:
            self._send_404()
    
    def _send_health_response(self):
        """Send health check response"""
        try:
            ws_client = get_ws_client()
            health = ws_client.health
            
            # Determine overall health
            is_healthy = (
                health.connected and
                health.last_message_age_s < 60 and  # Message within last minute
                health.active_subscriptions > 0
            )
            
            response = {
                "status": "healthy" if is_healthy else "degraded",
                "timestamp": health.last_message_age_s,
                "websocket": {
                    "connected": health.connected,
                    "last_message_age_s": round(health.last_message_age_s, 2),
                    "active_subscriptions": health.active_subscriptions,
                    "messages_received": health.messages_received,
                    "reconnects": health.reconnects
                }
            }
            
            if health.last_error:
                response["last_error"] = health.last_error
            
            self._send_json(200, response)
        
        except Exception as e:
            logger.error(f"Health check error: {e}")
            self._send_json(500, {"status": "error", "message": str(e)})
    
    def _send_status_response(self):
        """Send detailed status response"""
        try:
            ws_client = get_ws_client()
            health = ws_client.health
            
            # Get latest quotes for all subscribed markets
            quotes = {}
            for market_id in ws_client._subscriptions:
                quote = ws_client.get_latest_quote(market_id)
                if quote:
                    quotes[market_id] = {
                        "bid": quote.best_bid,
                        "ask": quote.best_ask,
                        "spread": round(quote.spread, 4),
                        "mid": round(quote.mid, 4),
                        "age_s": round(time.time() - quote.timestamp, 2)
                    }
            
            response = {
                "websocket": {
                    "connected": health.connected,
                    "last_message_age_s": round(health.last_message_age_s, 2),
                    "active_subscriptions": health.active_subscriptions,
                    "messages_received": health.messages_received,
                    "reconnects": health.reconnects
                },
                "quotes": quotes
            }
            
            self._send_json(200, response)
        
        except Exception as e:
            logger.error(f"Status check error: {e}")
            self._send_json(500, {"status": "error", "message": str(e)})
    
    def _send_json(self, status_code: int, data: Dict):
        """Send JSON response"""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def _send_404(self):
        """Send 404 response"""
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Not found"}).encode())


class MarketDataHealthServer:
    """HTTP server for market data health endpoints"""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 9091):
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[Thread] = None
        self._running = False
    
    def start(self):
        """Start health server in background thread"""
        if self._running:
            logger.warning("Health server already running")
            return
        
        try:
            self.server = HTTPServer((self.host, self.port), MarketDataHealthHandler)
            self.thread = Thread(target=self._serve, daemon=True)
            self._running = True
            self.thread.start()
            
            logger.info(f"Market data health server started on http://{self.host}:{self.port}")
            logger.info(f"Endpoints: /market-data/health, /market-data/status")
        
        except Exception as e:
            logger.error(f"Failed to start health server: {e}")
            raise
    
    def _serve(self):
        """Serve requests"""
        while self._running:
            try:
                self.server.handle_request()
            except Exception as e:
                if self._running:
                    logger.error(f"Health server error: {e}")
    
    def stop(self):
        """Stop health server"""
        if not self._running:
            return
        
        self._running = False
        
        if self.server:
            self.server.shutdown()
        
        if self.thread:
            self.thread.join(timeout=5)
        
        logger.info("Market data health server stopped")


# Singleton instance
_health_server: Optional[MarketDataHealthServer] = None

def start_market_data_health_server(host: str = "0.0.0.0", port: int = 9091):
    """Start global health server"""
    global _health_server
    if _health_server is None:
        _health_server = MarketDataHealthServer(host, port)
        _health_server.start()
    return _health_server
