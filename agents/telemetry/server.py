"""
HTTP Endpoint for Metrics Export
Block C - Step 2
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Optional
import logging

from .metrics import get_metrics_collector

logger = logging.getLogger(__name__)


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler for metrics endpoints"""
    
    def log_message(self, format, *args):
        """Suppress default logging"""
        pass
    
    def do_GET(self):
        """Handle GET requests"""
        collector = get_metrics_collector()
        
        if self.path == "/metrics":
            # Prometheus format
            self._send_prometheus_metrics(collector)
        
        elif self.path == "/metrics/json":
            # JSON format
            self._send_json_metrics(collector)
        
        elif self.path == "/health":
            # Health check
            self._send_health_check()
        
        else:
            self._send_404()
    
    def _send_prometheus_metrics(self, collector):
        """Send metrics in Prometheus format"""
        try:
            metrics_text = collector.export_prometheus_format()
            
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(metrics_text.encode())
        
        except Exception as e:
            logger.error(f"Error exporting metrics: {e}")
            self._send_error(500, str(e))
    
    def _send_json_metrics(self, collector):
        """Send metrics in JSON format"""
        try:
            summary = collector.get_metrics_summary()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(summary, indent=2).encode())
        
        except Exception as e:
            logger.error(f"Error exporting metrics: {e}")
            self._send_error(500, str(e))
    
    def _send_health_check(self):
        """Send health check response"""
        health = {
            "status": "healthy",
            "service": "polymarket-trading-bot"
        }
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(health).encode())
    
    def _send_404(self):
        """Send 404 response"""
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Not found"}).encode())
    
    def _send_error(self, code: int, message: str):
        """Send error response"""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode())


class MetricsServer:
    """HTTP server for metrics export"""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 9090):
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[Thread] = None
        self._running = False
    
    def start(self):
        """Start metrics server in background thread"""
        if self._running:
            logger.warning("Metrics server already running")
            return
        
        try:
            self.server = HTTPServer((self.host, self.port), MetricsHandler)
            self.thread = Thread(target=self._serve, daemon=True)
            self._running = True
            self.thread.start()
            
            logger.info(f"Metrics server started on http://{self.host}:{self.port}")
            logger.info(f"Endpoints: /metrics, /metrics/json, /health")
        
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")
            raise
    
    def _serve(self):
        """Serve requests"""
        while self._running:
            try:
                self.server.handle_request()
            except Exception as e:
                if self._running:
                    logger.error(f"Metrics server error: {e}")
    
    def stop(self):
        """Stop metrics server"""
        if not self._running:
            return
        
        self._running = False
        
        if self.server:
            self.server.shutdown()
        
        if self.thread:
            self.thread.join(timeout=5)
        
        logger.info("Metrics server stopped")
    
    def is_running(self) -> bool:
        """Check if server is running"""
        return self._running


# Global server instance
_metrics_server: Optional[MetricsServer] = None

def start_metrics_server(host: str = "0.0.0.0", port: int = 9090) -> MetricsServer:
    """Start global metrics server"""
    global _metrics_server
    if _metrics_server is None:
        _metrics_server = MetricsServer(host, port)
        _metrics_server.start()
    return _metrics_server

def stop_metrics_server():
    """Stop global metrics server"""
    global _metrics_server
    if _metrics_server:
        _metrics_server.stop()
        _metrics_server = None
