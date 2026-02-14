from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class SetupType(Enum):
    UNKNOWN = "unknown"


@dataclass
class PatternGateResult:
    should_trade: bool
    reason: str
    setup_type: SetupType
    pattern_probability: float
    implied_probability: Optional[float]
    edge: float
    samples: int
    confidence: Optional[int]
    regime: Optional[str]
    details: Optional[Dict[str, Any]] = None


class PatternGate:
    """Placeholder Pattern Gate (fail-open)."""

    def __init__(self, min_edge: float, min_samples: int, min_confidence: float, candle_window: int = 120):
        self.min_edge = float(min_edge)
        self.min_samples = int(min_samples)
        self.min_confidence = float(min_confidence)
        self.candle_window = int(candle_window)

    def evaluate(self, payload: Dict[str, Any], market: Any, chosen_token: str, action: str) -> PatternGateResult:
        confidence = payload.get("confidence")
        return PatternGateResult(
            should_trade=True,
            reason="ok",
            setup_type=SetupType.UNKNOWN,
            pattern_probability=0.5,
            implied_probability=None,
            edge=0.0,
            samples=0,
            confidence=confidence,
            regime=payload.get("regime"),
            details={},
        )
