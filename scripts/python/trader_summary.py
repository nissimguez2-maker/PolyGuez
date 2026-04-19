#!/usr/bin/env python3
"""OC-03: trader agent data tool.

Emits a structured JSON summary of the current V5 session — trade counts,
win rate, total PnL, Brier score (MODEL-03), fee-attribution breakdown,
and the N most recent trades. Designed to be invoked by the OpenClaw
trader agent via its bash tool so the agent has a deterministic,
easy-to-parse endpoint instead of ad-hoc SQL.

Usage:
    # Default: current V5 session, last 50 trades
    python scripts/python/trader_summary.py

    # Custom session / limit
    python scripts/python/trader_summary.py --session V5 --limit 20

Environment:
    SUPABASE_URL          — full https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY  — service-role key (read-only query)

Exits:
    0 — JSON emitted to stdout
    1 — required env vars missing
    2 — Supabase error (details on stderr)
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Trader summary → JSON")
    parser.add_argument("--session", default="V6",
                        help="session_tag to summarize (default: V6)")
    parser.add_argument("--limit", type=int, default=50,
                        help="max recent trades to include (default: 50)")
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

    # -- trades for the session --------------------------------------------
    try:
        trades = (
            client.table("trade_log")
            .select(
                "ts,side,entry_price,fill_price,exit_price,pnl,outcome,"
                "fee_paid,taker_maker,size_usdc,terminal_edge,net_edge,signal_id"
            )
            .eq("session_tag", args.session)
            .order("ts", desc=True)
            .limit(args.limit)
            .execute()
            .data
            or []
        )
    except Exception as e:
        print(f"Supabase trade_log query failed: {e}", file=sys.stderr)
        return 2

    wins = [t for t in trades if t.get("outcome") == "win"]
    losses = [t for t in trades if t.get("outcome") in ("loss", "emergency-exit")]
    closed = wins + losses
    pending = [t for t in trades if t.get("outcome") == "pending"]
    expired = [t for t in trades if t.get("outcome") == "expired"]

    def _safe_sum(rows, key):
        return round(sum((t.get(key) or 0.0) for t in rows), 4)

    # -- rolling_stats singleton -------------------------------------------
    rolling: dict = {}
    try:
        rs_rows = (
            client.table("rolling_stats")
            .select("data,updated_at")
            .eq("id", "singleton")
            .limit(1)
            .execute()
            .data
            or []
        )
        if rs_rows:
            rolling = rs_rows[0].get("data") or {}
            rolling["__rolling_stats_updated_at__"] = rs_rows[0].get("updated_at")
    except Exception as e:
        # Soft-fail: rolling_stats is nice-to-have, not blocking.
        print(f"rolling_stats query failed (ignored): {e}", file=sys.stderr)

    # -- Brier score (MODEL-03 RPC) ----------------------------------------
    brier_data = None
    try:
        brier_resp = client.rpc(
            "get_session_brier", {"p_session_tag": args.session}
        ).execute()
        rows = getattr(brier_resp, "data", None) or []
        if rows:
            brier_data = rows[0]
    except Exception as e:
        print(f"get_session_brier RPC failed (ignored): {e}", file=sys.stderr)

    # -- assemble output ---------------------------------------------------
    output = {
        "session": args.session,
        "trade_count_in_query": len(trades),
        "closed_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "pending": len(pending),
        "expired": len(expired),
        "win_rate": round(len(wins) / len(closed), 4) if closed else 0.0,
        "total_pnl": _safe_sum(trades, "pnl"),
        "total_fees_paid": _safe_sum(trades, "fee_paid"),
        "net_pnl_after_fees": round(
            _safe_sum(trades, "pnl") - _safe_sum(trades, "fee_paid"), 4
        ),
        "fill_breakdown": {
            "maker": sum(1 for t in trades if t.get("taker_maker") == "maker"),
            "taker": sum(1 for t in trades if t.get("taker_maker") == "taker"),
            "simulated": sum(1 for t in trades if t.get("taker_maker") == "simulated"),
            "unknown": sum(1 for t in trades if not t.get("taker_maker")),
        },
        "calibration": {
            "brier_score": brier_data.get("brier") if brier_data else None,
            "brier_n_trades": brier_data.get("n_trades") if brier_data else None,
            "avg_predicted": brier_data.get("avg_predicted") if brier_data else None,
            "avg_realized": brier_data.get("avg_realized") if brier_data else None,
            "threshold_for_live": 0.25,
            "meets_threshold": (
                brier_data is not None
                and brier_data.get("brier") is not None
                and float(brier_data["brier"]) <= 0.25
            ),
        },
        "rolling_stats": rolling,
        "recent_trades": trades[:10],
    }

    print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
