#!/usr/bin/env python3
import json
from pathlib import Path

def main():
    path = Path("c:/Users/sefa1/agents/paper_trades.jsonl")
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

