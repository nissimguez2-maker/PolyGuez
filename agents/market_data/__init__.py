"""
Market Data Module - WebSocket + Orderbook + Execution
Blocks E, F, G
"""

from .providers.polymarket_ws import (
    PolymarketWSClient,
    Quote,
    Trade,
    WSHealth,
    get_ws_client
)

from .orderbook import (
    OrderBook,
    OrderBookManager,
    LiquidityGate,
    PriceLevel,
    get_orderbook_manager
)

from .execution_engine import (
    ExecutionEngine,
    ExecutionConfig,
    ExecutionResult,
    OrderType,
    get_execution_engine
)

from .health_server import (
    MarketDataHealthServer,
    start_market_data_health_server
)

__all__ = [
    # WebSocket
    "PolymarketWSClient",
    "Quote",
    "Trade", 
    "WSHealth",
    "get_ws_client",
    
    # Orderbook
    "OrderBook",
    "OrderBookManager",
    "LiquidityGate",
    "PriceLevel",
    "get_orderbook_manager",
    
    # Execution
    "ExecutionEngine",
    "ExecutionConfig",
    "ExecutionResult",
    "OrderType",
    "get_execution_engine",
    
    # Health
    "MarketDataHealthServer",
    "start_market_data_health_server"
]
