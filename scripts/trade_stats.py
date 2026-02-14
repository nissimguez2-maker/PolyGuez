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
    return Path(__file__).resolve().parent.parent / "paper_trades.jsonl"


def main():
    path = _paper_trades_path()
    if not path.exists():
        print("no_data")
        return
    latest = {}
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
            latest[tid] = j

    closed = [r for r in latest.values() if r.get("status") == "closed"]
    wins = sum(1 for r in closed if r.get("realized_pnl") is not None and float(r.get("realized_pnl")) > 0)
    losses = sum(1 for r in closed if r.get("realized_pnl") is not None and float(r.get("realized_pnl")) < 0)
    ties = sum(1 for r in closed if r.get("realized_pnl") is None)
    total = len(closed)
    pct = (wins/total*100) if total>0 else 0.0
    # print: wins losses ties total pct
    print(f"{wins} {losses} {ties} {total} {pct:.1f}")

if __name__ == '__main__':
    main()

