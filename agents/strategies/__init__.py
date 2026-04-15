"""PolyGuez strategies package.

Defines the public interface for PolyGuez's trading brain. Previously empty,
which meant any file could import anything from anywhere here — no declared
boundary between "stable public surface" and "internal helpers." This module
fixes that by re-exporting the stable symbols and leaving everything else
as private to its defining module.

Public surface (stable — importable via `from agents.strategies import X`):

- Signal + sizing:
    evaluate_entry_signal, calculate_position_size, compute_clob_depth
- Trade execution:
    execute_entry
- Settlement:
    settle_with_retry
- Stats persistence:
    load_rolling_stats, save_rolling_stats
- LLM gate:
    get_llm_confirmation
- Price + discovery primitives:
    PriceFeedManager, MarketDiscovery

Everything else in this package is considered internal. If a symbol you need
isn't here, prefer importing it directly from its defining module rather
than adding it to __all__ without a review.
"""

from agents.strategies.btc_feed import PriceFeedManager
from agents.strategies.market_discovery import MarketDiscovery
from agents.strategies.polyguez_strategy import (
    calculate_position_size,
    compute_clob_depth,
    evaluate_entry_signal,
    execute_entry,
    get_llm_confirmation,
    load_rolling_stats,
    save_rolling_stats,
    settle_with_retry,
)

__all__ = [
    "PriceFeedManager",
    "MarketDiscovery",
    "calculate_position_size",
    "compute_clob_depth",
    "evaluate_entry_signal",
    "execute_entry",
    "get_llm_confirmation",
    "load_rolling_stats",
    "save_rolling_stats",
    "settle_with_retry",
]
