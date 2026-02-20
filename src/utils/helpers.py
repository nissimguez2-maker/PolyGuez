from datetime import datetime, timezone
from typing import Any, Optional


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def parse_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def parse_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def normalize_signal(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip().upper()
    if s in ("BUY_UP", "UP", "LONG", "BULL", "BULLISH"):
        return "BULL"
    if s in ("BUY_DOWN", "DOWN", "SHORT", "BEAR", "BEARISH"):
        return "BEAR"
    return s


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def calc_session(hour_utc: int) -> str:
    # Simple session buckets by UTC hour
    if 0 <= hour_utc < 7:
        return "ASIA"
    if 7 <= hour_utc < 13:
        return "LONDON"
    if 13 <= hour_utc < 21:
        return "NY"
    return "ASIA"

