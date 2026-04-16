#!/usr/bin/env python3
"""Supabase maintenance tasks — rare one-off fixes with hard-coded SQL.

Usage:
  python scripts/ops/sb_maintenance.py --task noop --confirm CONFIRM_DANGER
  python scripts/ops/sb_maintenance.py --list

Principles:
- No arbitrary SQL. Each task is an explicit function in this file with
  fixed SQL, named arguments, and a well-defined outcome.
- Every task requires `--confirm CONFIRM_DANGER` to run.
- Every task logs to scripts/ops/ops_log.jsonl (start + outcome).
- Adding a new task = adding a new function in the TASKS dict below. The
  task name must be explicitly passed via --task, so agents cannot invent
  new tasks at runtime.

Current tasks:
  noop                — sanity-check that the env + confirm plumbing works.
                        Hits Supabase to run `SELECT 1` and returns.
  (no real tasks yet — add as needed)

New tasks: define a function `task_<name>(client) -> dict` and register
it in TASKS. Keep each task's SQL narrow and idempotent where possible.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Callable, Dict

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


def task_noop(client) -> Dict[str, Any]:
    """Smoke test: fetch one row from session_tag_current to prove the env
    + client are wired correctly. Returns the active session tag."""
    resp = client.table("session_tag_current").select("tag").limit(1).execute()
    rows = getattr(resp, "data", []) or []
    active = rows[0]["tag"] if rows else None
    return {"active_session_tag": active, "rows": len(rows)}


# Registry of allowed task names. Agents must pass one of these via --task.
TASKS: Dict[str, Callable] = {
    "noop": task_noop,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", help=f"Task to run. One of: {', '.join(TASKS)}")
    parser.add_argument(
        "--confirm",
        default="",
        help="Must equal CONFIRM_DANGER to run a non-noop task.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List registered tasks and exit.",
    )
    args = parser.parse_args()

    if args.list:
        print("Registered maintenance tasks:")
        for name, fn in TASKS.items():
            doc = (fn.__doc__ or "").strip().split("\n")[0]
            print(f"  {name}\t{doc}")
        return 0

    if not args.task:
        print("--task required (or use --list). Available tasks:", file=sys.stderr)
        for name in TASKS:
            print(f"  {name}", file=sys.stderr)
        return 1

    if args.task not in TASKS:
        write_ops_log("sb_maintenance", "error", {
            "reason": "unknown_task",
            "task": args.task,
            "registered": list(TASKS),
        })
        print(f"Unknown task: {args.task!r}. Use --list to see registered tasks.", file=sys.stderr)
        return 1

    if args.confirm != "CONFIRM_DANGER":
        write_ops_log("sb_maintenance", "error", {
            "task": args.task,
            "reason": "missing_confirm",
        })
        print("Refusing to run without --confirm CONFIRM_DANGER", file=sys.stderr)
        return 1

    write_ops_log("sb_maintenance", "start", {"task": args.task})

    try:
        client = _get_client()
        result = TASKS[args.task](client)
        write_ops_log("sb_maintenance", "ok", {"task": args.task, "result": result})
        print(f"task {args.task}: {result}")
        return 0
    except Exception as exc:
        write_ops_log("sb_maintenance", "error", {"task": args.task, "error": str(exc)})
        print(f"sb_maintenance failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
