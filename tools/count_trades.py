import json
from glob import glob

def main():
    files = glob("paper_trades_legacy*.jsonl") + glob("paper_trades_legacy.jsonl")
    total_closed = 0
    wins = 0
    losses = 0
    draws = 0
    open_trades = 0
    pnls = []
    for fn in files:
        try:
            with open(fn, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if "realized_pnl" in obj:
                        total_closed += 1
                        rp = obj.get("realized_pnl") or 0
                        pnls.append(rp)
                        if rp > 0:
                            wins += 1
                        elif rp < 0:
                            losses += 1
                        else:
                            draws += 1
                    else:
                        # treat as open/entry
                        open_trades += 1
        except FileNotFoundError:
            continue

    total_trades = total_closed + open_trades
    win_rate = (wins / total_closed * 100) if total_closed else 0.0
    total_pnl = sum(pnls)
    out = {
        "files_scanned": files,
        "total_trades": total_trades,
        "closed_trades": total_closed,
        "open_trades": open_trades,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate_pct": round(win_rate, 2),
        "total_realized_pnl": round(total_pnl, 6),
    }
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()

