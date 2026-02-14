from datetime import datetime, timezone, timedelta
import sys
sys.path.append(".")
from src.timeframes import floor_time, window_bounds, seconds_from_start, seconds_to_end


def test_floor_and_bounds_15m():
    dt = datetime(2026, 2, 13, 10, 7, 30, tzinfo=timezone.utc)
    start = floor_time(dt, 15)
    assert start == datetime(2026, 2, 13, 10, 0, tzinfo=timezone.utc)
    s_from = seconds_from_start(dt, 15)
    s_to = seconds_to_end(dt, 15)
    assert s_from == 450  # 7*60 +30 = 450
    assert s_to == 900 - 450


def test_floor_and_bounds_5m():
    dt = datetime(2026, 2, 13, 10, 7, 30, tzinfo=timezone.utc)
    start = floor_time(dt, 5)
    assert start == datetime(2026, 2, 13, 10, 5, tzinfo=timezone.utc)
    s_from = seconds_from_start(dt, 5)
    s_to = seconds_to_end(dt, 5)
    assert s_from == 150  # 2*60 +30
    assert s_to == 300 - 150

