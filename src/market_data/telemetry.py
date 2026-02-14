from __future__ import annotations
import threading
import time
from typing import Dict, Optional


class Telemetry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: Dict[str, int] = {}
        self.gauges: Dict[str, float] = {}
        self.last_msg_ts: Optional[float] = None

    def incr(self, key: str, value: int = 1) -> None:
        with self._lock:
            self.counters[key] = self.counters.get(key, 0) + value

    def set_gauge(self, key: str, value: float) -> None:
        with self._lock:
            self.gauges[key] = float(value)

    def set_last_msg_ts(self, ts: Optional[float]) -> None:
        with self._lock:
            self.last_msg_ts = ts

    def get_snapshot(self) -> Dict[str, Optional[float]]:
        with self._lock:
            now = time.time()
            last_age = None
            if self.last_msg_ts is not None:
                last_age = now - self.last_msg_ts
            return {
                "counters": dict(self.counters),
                "gauges": dict(self.gauges),
                "last_msg_age_s": last_age,
            }


# Global telemetry instance for market_data
telemetry = Telemetry()

