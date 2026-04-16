#!/usr/bin/env python3
"""Bot health check for PolyGuez (OpenClaw analyst tool).

Purely observational. Looks at Supabase to answer:
    - is the bot writing signals at all right now?
    - when was the last signal / trade?
    - derive a best-effort status (running / stalled / silent)

Outputs JSON with:
    - status: "running" | "stalled" | "silent"
    - last_signal_ts / last_trade_ts (ISO, or null)
    - minutes_since_last_signal / minutes_since_last_trade (float or null)
    - session: session_tag inspected
    - stall_threshold_minutes: cutoff used for the status heuristic

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
from datetime import datetime, timezone


def _parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Bot health -> JSON")
    parser.add_argument("--session", default="V5",
                        help="session_tag to inspect (default: V5)")
    parser.add_argument("--stall-minutes", type=float, default=15.0,
                        help="minutes without a signal = 'stalled' (default: 15)")
    parser.add_argument("--silent-minutes", type=float, default=60.0,
                        help="minutes without a signal = 'silent' (default: 60)")
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

    try:
        sig = (
            client.table("signal_log")
            .select("ts")
            .eq("session_tag", args.session)
            .order("ts", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        last_signal_ts = sig[0]["ts"] if sig else None
    except Exception as e:
        print(f"Supabase signal_log query failed: {e}", file=sys.stderr)
        return 2

    try:
        tr = (
            client.table("trade_log")
            .select("ts")
            .eq("session_tag", args.session)
            .order("ts", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        last_trade_ts = tr[0]["ts"] if tr else None
    except Exception as e:
        print(f"Supabase trade_log query failed: {e}", file=sys.stderr)
        return 2

    ts_sig = _parse_ts(last_signal_ts)
    ts_trade = _parse_ts(last_trade_ts)

    mins_since_sig = (
        round((now - ts_sig).total_seconds() / 60.0, 1) if ts_sig else None
    )
    mins_since_trade = (
        round((now - ts_trade).total_seconds() / 60.0, 1) if ts_trade else None
    )

    if mins_since_sig is None:
        status = "silent"
    elif mins_since_sig >= args.silent_minutes:
        status = "silent"
    elif mins_since_sig >= args.stall_minutes:
        status = "stalled"
    else:
        status = "running"

    out = {
        "session": args.session,
        "status": status,
        "last_signal_ts": last_signal_ts,
        "last_trade_ts": last_trade_ts,
        "minutes_since_last_signal": mins_since_sig,
        "minutes_since_last_trade": mins_since_trade,
        "stall_threshold_minutes": args.stall_minutes,
        "silent_threshold_minutes": args.silent_minutes,
    }
    print(json.dumps(out, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
