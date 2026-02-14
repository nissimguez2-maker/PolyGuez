#!/usr/bin/env python3
import json
import os
from pathlib import Path


def _paper_trades_path() -> Path:
    """Resolve paper_trades.jsonl path.

    Priority:
    1. Environment variable PAPER_TRADES_PATH or PAPER_TRADES_FILE
    2. Relative path at repo root: ../paper_trades.jsonl
    """
    env = os.getenv("PAPER_TRADES_PATH") or os.getenv("PAPER_TRADES_FILE")
    if env:
        return Path(env)
    # Default: repository root (two levels up from scripts/) + paper_trades.jsonl
    return Path(__file__).resolve().parent.parent / "paper_trades.jsonl"


def main():
    path = _paper_trades_path()
    if not path.exists():
        print("0 0 0")
        return
    latest_status = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            tid = j.get("trade_id")
            if not tid:
                continue
            status = j.get("status")
            latest_status[tid] = status or "open"

    total_trades = len(latest_status)
    open_trades = sum(1 for s in latest_status.values() if s != "closed")
    closed_trades = total_trades - open_trades
    # Output: total open closed
    print(f"{total_trades} {open_trades} {closed_trades}")

if __name__ == "__main__":
    main()

