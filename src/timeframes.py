from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Tuple


def floor_time(dt: datetime, minutes: int) -> datetime:
    """
    Floor a UTC datetime to the window start for given minutes.
    Returns timezone-aware UTC datetime.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    total_seconds = int(dt.timestamp())
    window_seconds = minutes * 60
    start_ts = (total_seconds // window_seconds) * window_seconds
    return datetime.fromtimestamp(start_ts, tz=timezone.utc)


def window_bounds(dt: datetime, minutes: int) -> Tuple[datetime, datetime]:
    start = floor_time(dt, minutes)
    end = start + timedelta(minutes=minutes)
    return start, end


def seconds_from_start(dt: datetime, minutes: int) -> int:
    start, _ = window_bounds(dt, minutes)
    return int((dt.astimezone(timezone.utc) - start).total_seconds())


def seconds_to_end(dt: datetime, minutes: int) -> int:
    _, end = window_bounds(dt, minutes)
    return int((end - dt.astimezone(timezone.utc)).total_seconds())

