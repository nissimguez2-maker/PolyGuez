from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional


@dataclass
class LatencySnapshot:
    count: int
    avg_ms: float
    p50_ms: float
    p90_ms: float
    p99_ms: float


class LatencyStats:
    """Rolling latency stats for detection/execution timing."""

    def __init__(self, window_size: int = 200):
        self.window_size = max(10, int(window_size))
        self.detect_to_send: Deque[float] = deque(maxlen=self.window_size)
        self.detect_to_ack: Deque[float] = deque(maxlen=self.window_size)

    def record(self, detect_to_send_ms: Optional[float], detect_to_ack_ms: Optional[float]) -> None:
        if detect_to_send_ms is not None:
            self.detect_to_send.append(float(detect_to_send_ms))
        if detect_to_ack_ms is not None:
            self.detect_to_ack.append(float(detect_to_ack_ms))

    def _snapshot(self, values: Deque[float]) -> LatencySnapshot:
        if not values:
            return LatencySnapshot(0, 0.0, 0.0, 0.0, 0.0)
        vals = sorted(values)
        n = len(vals)
        avg = sum(vals) / n
        p50 = vals[int(0.50 * (n - 1))]
        p90 = vals[int(0.90 * (n - 1))]
        p99 = vals[int(0.99 * (n - 1))]
        return LatencySnapshot(n, avg, p50, p90, p99)

    def get_stats(self) -> Dict[str, Dict[str, float]]:
        send = self._snapshot(self.detect_to_send)
        ack = self._snapshot(self.detect_to_ack)
        return {
            "detect_to_send_ms": send.__dict__,
            "detect_to_ack_ms": ack.__dict__,
        }
