#!/usr/bin/env python3
"""Supabase read-only helper for OpenClaw.

Usage:
  python scripts/ops/sb_read.py --table trade_log --limit 10
  python scripts/ops/sb_read.py --table signal_log --limit 5 --filter session_tag=V5 --order ts:desc
  python scripts/ops/sb_read.py --view session_brier_scores

Rules:
- READ-ONLY. This script does not modify data; it does not accept raw SQL
  containing DDL or DML. For analysis, prefer the canned, higher-level
  scripts (trader_summary.py, etc.) over this one — this exists for
  ad-hoc debugging by operator/architect agents.
- Accepts --table/--view, optional --filter (repeatable), --order, --limit.
- Logs every query to scripts/ops/ops_log.jsonl.

Env:
  SUPABASE_URL
  SUPABASE_SERVICE_KEY   (service_role — read-only here by convention)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# sibling-import helper
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from log_utils import write_ops_log  # noqa: E402


def _get_client():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set. "
            "Source /etc/polyguez.env before calling this script."
        )
    from supabase import create_client  # lazy import
    return create_client(url, key)


def _parse_filters(filter_args: list[str]) -> list[tuple[str, str, str]]:
    """Parse `col=value` or `col:op=value` filters.

    Supported ops: eq (default), neq, gt, gte, lt, lte, like, ilike.
    """
    allowed = {"eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike"}
    parsed: list[tuple[str, str, str]] = []
    for raw in filter_args or []:
        if "=" not in raw:
            raise RuntimeError(f"bad --filter format: {raw!r} (expected col=value or col:op=value)")
        lhs, value = raw.split("=", 1)
        if ":" in lhs:
            col, op = lhs.split(":", 1)
        else:
            col, op = lhs, "eq"
        if op not in allowed:
            raise RuntimeError(f"filter op {op!r} not supported (allowed: {sorted(allowed)})")
        parsed.append((col.strip(), op, value))
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", help="Supabase table to read")
    parser.add_argument("--view", help="Supabase view to read (same as --table semantically)")
    parser.add_argument("--select", default="*", help="Columns to select (default: *)")
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        help="Filter in the form col=value or col:op=value. Repeatable. ops: eq,neq,gt,gte,lt,lte,like,ilike.",
    )
    parser.add_argument(
        "--order",
        default="",
        help="col:asc or col:desc (default: no ordering).",
    )
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    source = args.table or args.view
    if not source:
        print("Either --table or --view is required", file=sys.stderr)
        write_ops_log("sb_read", "error", {"reason": "missing_table_or_view"})
        return 1

    try:
        client = _get_client()
        query = client.table(source).select(args.select)

        for col, op, value in _parse_filters(args.filter):
            query = getattr(query, op)(col, value)

        if args.order:
            if ":" in args.order:
                col, direction = args.order.split(":", 1)
            else:
                col, direction = args.order, "asc"
            query = query.order(col, desc=(direction.lower() == "desc"))

        query = query.limit(args.limit)

        resp = query.execute()
        data = getattr(resp, "data", []) or []

        write_ops_log("sb_read", "ok", {
            "source": source,
            "filters": args.filter,
            "order": args.order,
            "limit": args.limit,
            "rows": len(data),
        })

        print(json.dumps(data, indent=2, default=str))
        return 0

    except Exception as exc:
        write_ops_log("sb_read", "error", {
            "source": source,
            "error": str(exc),
        })
        print(f"sb_read failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
