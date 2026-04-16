"""Shared append-only ops log.

Every operational action taken by an agent (github push, deploy,
Supabase read / migrate / maintenance) writes one JSON line here with
timestamp, action, status, and structured details. The file is the
audit trail — if an agent did something, it should appear in here.

Used by scripts in scripts/ops/.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict


LOG_PATH = os.path.join(os.path.dirname(__file__), "ops_log.jsonl")


def write_ops_log(action: str, status: str, details: Dict[str, Any]) -> None:
    """Append one JSON entry to scripts/ops/ops_log.jsonl."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "status": status,
        "details": details,
    }
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
