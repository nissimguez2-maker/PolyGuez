#!/usr/bin/env python3
import glob, json
from pathlib import Path

def main():
    base = Path("c:/Users/sefa1/agents")
    pattern1 = str(base / "paper_trades_legacy*.jsonl")
    pattern2 = str(base / "paper_trades_legacy.jsonl")
    files = glob.glob(pattern1) + glob.glob(pattern2)
    latest = {}
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
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
        except Exception:
            continue
    # include current file
    cur = base / "paper_trades.jsonl"
    if cur.exists():
        with cur.open("r", encoding="utf-8") as f:
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

    total = len(latest)
    open_count = sum(1 for r in latest.values() if r.get("status") != "closed")
    closed = [r for r in latest.values() if r.get("status") == "closed"]
    closed_count = len(closed)
    wins = sum(1 for r in closed if r.get("realized_pnl") is not None and float(r.get("realized_pnl")) > 0)
    losses = sum(1 for r in closed if r.get("realized_pnl") is not None and float(r.get("realized_pnl")) < 0)
    ties = sum(1 for r in closed if r.get("realized_pnl") is None)
    win_rate = (wins / closed_count * 100) if closed_count > 0 else 0.0

    print(f"total:{total} open:{open_count} closed:{closed_count} wins:{wins} losses:{losses} ties:{ties} win_rate:{win_rate:.1f}%")

if __name__ == "__main__":
    main()

