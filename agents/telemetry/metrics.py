"""
Metrics Collection for Trading Bot Observability
Block C - Step 1
"""

import time
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from collections import defaultdict
import threading


@dataclass
class TradeMetrics:
    """Metrics for a single trade attempt"""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    market_id: str = ""
    side: str = ""  # "yes" or "no"
    size: float = 0.0
    entry_price: float = 0.0
    
    # Outcome
    status: str = ""  # "success", "failed", "blocked"
    block_reason: Optional[str] = None
    error: Optional[str] = None
    
    # Timing
    latency_ms: float = 0.0  # End-to-end latency
    
    # PnL (if executed)
    realized_pnl: Optional[float] = None


@dataclass  
class CycleMetrics:
    """Metrics for one trading cycle"""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Stages
    events_found: int = 0
    events_filtered: int = 0
    markets_found: int = 0
    markets_filtered: int = 0
    
    # Timing per stage (ms)
    time_fetch_events_ms: float = 0.0
    time_filter_events_ms: float = 0.0
    time_fetch_markets_ms: float = 0.0
    time_filter_markets_ms: float = 0.0
    time_analyze_ms: float = 0.0
    time_execute_ms: float = 0.0
    
    # Total
    total_latency_ms: float = 0.0
    
    # Result
    trade_executed: bool = False
    trade_blocked: bool = False
    block_reason: Optional[str] = None


class MetricsCollector:
    """Central metrics collection for trading bot"""
    
    def __init__(self, max_history: int = 10000):
        self.max_history = max_history
        self._lock = threading.Lock()
        
        # Counters
        self._counters: Dict[str, int] = defaultdict(int)
        
        # Trade history
        self._trades: List[TradeMetrics] = []
        self._cycles: List[CycleMetrics] = []
        
        # Timing histograms (simple buckets)
        self._latency_buckets = [0, 100, 250, 500, 1000, 2500, 5000, 10000, float('inf')]
        self._latency_distribution: Dict[str, List[int]] = defaultdict(lambda: [0] * len(self._latency_buckets))
        
        # Risk block reasons
        self._block_reasons: Dict[str, int] = defaultdict(int)
    
    # === Counter Methods ===
    
    def increment(self, name: str, value: int = 1, labels: Optional[Dict[str, str]] = None):
        """Increment a counter"""
        with self._lock:
            key = self._format_key(name, labels)
            self._counters[key] += value
    
    def _format_key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        """Format counter key with labels"""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
    
    # === Trade Recording ===
    
    def record_trade(self, metrics: TradeMetrics):
        """Record a trade attempt"""
        with self._lock:
            self._trades.append(metrics)
            
            # Update counters
            if metrics.status == "success":
                self._counters["trades_placed_total"] += 1
            elif metrics.status == "failed":
                self._counters["trades_failed_total"] += 1
            elif metrics.status == "blocked":
                self._counters["trades_blocked_total"] += 1
                if metrics.block_reason:
                    self._block_reasons[metrics.block_reason] += 1
            
            self._counters["trades_attempted_total"] += 1
            
            # Prune old history
            if len(self._trades) > self.max_history:
                self._trades = self._trades[-self.max_history:]
    
    # === Cycle Recording ===
    
    def record_cycle(self, metrics: CycleMetrics):
        """Record a trading cycle"""
        with self._lock:
            self._cycles.append(metrics)
            
            # Update latency distribution
            bucket_idx = self._find_bucket(metrics.total_latency_ms)
            self._latency_distribution["cycle_latency"][bucket_idx] += 1
            
            if metrics.time_execute_ms > 0:
                bucket_idx = self._find_bucket(metrics.time_execute_ms)
                self._latency_distribution["execution_latency"][bucket_idx] += 1
            
            # Prune old history
            if len(self._cycles) > self.max_history:
                self._cycles = self._cycles[-self.max_history:]
    
    def _find_bucket(self, latency_ms: float) -> int:
        """Find histogram bucket for latency"""
        for i, bucket in enumerate(self._latency_buckets):
            if latency_ms <= bucket:
                return i
        return len(self._latency_buckets) - 1
    
    # === Timing Context Manager ===
    
    def time_stage(self, stage_name: str):
        """Context manager for timing a stage"""
        return StageTimer(self, stage_name)
    
    # === Metrics Export ===
    
    def get_counters(self) -> Dict[str, int]:
        """Get all counters"""
        with self._lock:
            return dict(self._counters)
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get summary of all metrics"""
        with self._lock:
            total_trades = self._counters.get("trades_attempted_total", 0)
            successful = self._counters.get("trades_placed_total", 0)
            failed = self._counters.get("trades_failed_total", 0)
            blocked = self._counters.get("trades_blocked_total", 0)
            
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "counters": {
                    "trades_attempted_total": total_trades,
                    "trades_placed_total": successful,
                    "trades_failed_total": failed,
                    "trades_blocked_total": blocked,
                    "success_rate": successful / total_trades if total_trades > 0 else 0,
                    "block_rate": blocked / total_trades if total_trades > 0 else 0,
                    **{k: v for k, v in self._counters.items() if not k.startswith("trades_")}
                },
                "block_reasons": dict(self._block_reasons),
                "latency_distribution": {
                    k: {
                        "buckets": self._latency_buckets,
                        "counts": v
                    }
                    for k, v in self._latency_distribution.items()
                },
                "recent_trades": [asdict(t) for t in self._trades[-10:]],
                "recent_cycles": [asdict(c) for c in self._cycles[-5:]]
            }
    
    def export_prometheus_format(self) -> str:
        """Export metrics in Prometheus text format"""
        lines = []
        
        with self._lock:
            # Counters
            for key, value in self._counters.items():
                name, labels = self._parse_key(key)
                lines.append(f"# HELP {name} Counter")
                lines.append(f"# TYPE {name} counter")
                if labels:
                    lines.append(f'{name}{{{labels}}} {value}')
                else:
                    lines.append(f'{name} {value}')
            
            # Block reasons
            lines.append("# HELP blocked_by_risk_total Total trades blocked by risk")
            lines.append("# TYPE blocked_by_risk_total counter")
            for reason, count in self._block_reasons.items():
                lines.append(f'blocked_by_risk_total{{reason="{reason}"}} {count}')
            
            # Latency histograms
            for metric_name, distribution in self._latency_distribution.items():
                lines.append(f"# HELP {metric_name}_milliseconds Latency histogram")
                lines.append(f"# TYPE {metric_name}_milliseconds histogram")
                
                cumulative = 0
                for i, bucket in enumerate(self._latency_buckets):
                    count = distribution[i]
                    cumulative += count
                    if bucket == float('inf'):
                        lines.append(f'{metric_name}_milliseconds_bucket{{le="+Inf"}} {cumulative}')
                    else:
                        lines.append(f'{metric_name}_milliseconds_bucket{{le="{bucket}"}} {cumulative}')
                
                lines.append(f'{metric_name}_milliseconds_sum {sum(distribution)}')
                lines.append(f'{metric_name}_milliseconds_count {cumulative}')
        
        return "\n".join(lines)
    
    def _parse_key(self, key: str) -> tuple:
        """Parse counter key into name and labels"""
        if "{" not in key:
            return key, ""
        
        name, rest = key.split("{", 1)
        labels = rest.rstrip("}")
        return name, labels
    
    def reset(self):
        """Reset all metrics (use with caution)"""
        with self._lock:
            self._counters.clear()
            self._trades.clear()
            self._cycles.clear()
            self._latency_distribution.clear()
            self._block_reasons.clear()


class StageTimer:
    """Context manager for timing stages"""
    
    def __init__(self, collector: MetricsCollector, stage_name: str):
        self.collector = collector
        self.stage_name = stage_name
        self.start_time: Optional[float] = None
        self.elapsed_ms: float = 0.0
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            self.elapsed_ms = (time.time() - self.start_time) * 1000
            self.collector.increment(f"stage_{self.stage_name}_ms", int(self.elapsed_ms))


# Global collector instance
_metrics_collector: Optional[MetricsCollector] = None

def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector
