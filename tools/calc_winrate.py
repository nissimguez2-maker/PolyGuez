import json
from pathlib import Path

files = list(Path(".").glob("paper_trades_legacy_*.jsonl")) + list(Path(".").glob("paper_trades.jsonl"))
files = [p for p in files if p.exists()]

total = 0
wins = 0
losses = 0
ties = 0
pnls = 0.0
seen = set()

for f in files:
    with open(f, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if "realized_pnl" in obj:
                tid = obj.get("trade_id") or obj.get("id") or None
                key = (tid, obj.get("exit_time_utc"))
                # count each closing record once
                if key in seen:
                    continue
                seen.add(key)
                pnl = obj.get("realized_pnl")
                if pnl is None:
                    continue
                try:
                    pnl = float(pnl)
                except Exception:
                    continue
                total += 1
                pnls += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
                else:
                    ties += 1

print(f"files_considered={len(files)} total_trades={total} wins={wins} losses={losses} ties={ties} winrate={wins/(total or 1):.3f} total_pnl={pnls:.6f}")

