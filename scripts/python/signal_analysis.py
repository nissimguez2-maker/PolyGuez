#!/usr/bin/env python3
"""Signal-level analysis for PolyGuez (OpenClaw analyst tool).

Outputs JSON with:
    - session: session_tag inspected
    - signals_24h: total signals in last 24h
    - fired_24h: how many fired a trade
    - fire_rate_24h: fired_24h / signals_24h as percent
    - blockers: [{gate, blocked_count, blocked_pct}, ...] sorted desc
    - top_blocker: the most frequent blocker (or null)
    - last_signal_ts: ISO timestamp of the most recent signal (or null)

Schema note: the canonical column is `blocking_conditions` (comma-separated
TEXT populated by `agents/application/run_polyguez.py`). The original spec
used `blocked_by`; we adapt here.

Environment:
    SUPABASE_URL          full https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY  service-role key (read-only query)

Exits 0 on success, 1 if env vars missing, 2 on Supabase error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone


def _split_blockers(raw: object) -> list[str]:
    """Parse a `blocking_conditions` value into a clean list of gate names."""
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        items = str(raw).split(",")
    return [s.strip() for s in items if s and str(s).strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Signal-log analysis -> JSON")
    parser.add_argument("--session", default="V6",
                        help="session_tag to analyze (default: V6)")
    parser.add_argument("--hours", type=int, default=24,
                        help="lookback window in hours (default: 24)")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY are required", file=sys.stderr)
        return 1

    try:
        from supabase import create_client
    except ImportError as e:
        print(f"supabase python client not installed: {e}", file=sys.stderr)
        return 2

    try:
        client = create_client(url, key)
    except Exception as e:
        print(f"Supabase client init failed: {e}", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=args.hours)

    try:
        rows = (
            client.table("signal_log")
            .select("ts,trade_fired,all_conditions_met,blocking_conditions")
            .eq("session_tag", args.session)
            .gte("ts", since.isoformat())
            .order("ts", desc=True)
            .execute()
            .data
            or []
        )
    except Exception as e:
        print(f"Supabase signal_log query failed: {e}", file=sys.stderr)
        return 2

    signals_24h = len(rows)
    fired_24h = sum(1 for r in rows if r.get("trade_fired"))
    rejected = max(signals_24h - fired_24h, 0)
    fire_rate_24h = (fired_24h / signals_24h * 100.0) if signals_24h else 0.0

    blockers: dict[str, int] = {}
    for r in rows:
        if r.get("trade_fired"):
            continue
        for gate in _split_blockers(r.get("blocking_conditions")):
            blockers[gate] = blockers.get(gate, 0) + 1

    blocker_list = [
        {
            "gate": gate,
            "blocked_count": count,
            "blocked_pct": round((count / rejected) * 100.0, 1) if rejected else 0.0,
        }
        for gate, count in blockers.items()
    ]
    blocker_list.sort(key=lambda x: x["blocked_count"], reverse=True)
    top_blocker = blocker_list[0] if blocker_list else None

    last_signal_ts = rows[0]["ts"] if rows else None

    out = {
        "session": args.session,
        "window_hours": args.hours,
        "signals_24h": signals_24h,
        "fired_24h": fired_24h,
        "rejected_24h": rejected,
        "fire_rate_24h": round(fire_rate_24h, 2),
        "blockers": blocker_list,
        "top_blocker": top_blocker,
        "last_signal_ts": last_signal_ts,
    }
    print(json.dumps(out, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
