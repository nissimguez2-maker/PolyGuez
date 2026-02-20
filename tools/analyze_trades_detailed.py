import json
from glob import glob
from statistics import mean, median, pstdev


def load_lines(files):
    for fn in files:
        try:
            with open(fn, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except Exception:
                        continue
        except FileNotFoundError:
            continue


def stats_list(xs):
    if not xs:
        return {"count": 0}
    return {
        "count": len(xs),
        "mean": mean(xs),
        "median": median(xs),
        "p90": sorted(xs)[int(len(xs) * 0.9) - 1] if len(xs) >= 1 else None,
        "std": pstdev(xs) if len(xs) > 1 else 0.0,
    }


def main():
    files = sorted(glob("paper_trades_legacy*.jsonl") + glob("paper_trades_legacy.jsonl"))
    entries = []
    exits = []
    for obj in load_lines(files):
        if "realized_pnl" in obj:
            exits.append(obj)
        else:
            entries.append(obj)

    # Confidence bucket analysis (closed trades)
    conf_buckets = {}
    for e in exits:
        conf = e.get("confidence")
        conf_buckets.setdefault(conf, []).append(e)

    conf_summary = {}
    for conf, items in sorted(conf_buckets.items(), key=lambda x: (x[0] is None, x[0])):
        pnls = [(it.get("realized_pnl") or 0) for it in items]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        draws = sum(1 for p in pnls if p == 0)
        conf_summary[conf] = {
            "count": len(items),
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "win_rate_pct": round(wins / len(items) * 100, 2) if items else 0.0,
            "total_pnl": round(sum(pnls), 6),
            "avg_pnl": round(mean(pnls), 6) if pnls else 0.0,
        }

    # Exit reasons
    exit_reasons = {}
    for e in exits:
        r = e.get("exit_reason", "unknown")
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    # Spread entry stats (from entries and exits where available)
    spreads = []
    spread_entries = []
    for obj in entries + exits:
        s = obj.get("spread_entry")
        if s is None:
            # try to compute from best bid/ask
            bid = obj.get("entry_best_bid")
            ask = obj.get("entry_best_ask")
            if bid is not None and ask is not None:
                try:
                    s = float(ask) - float(bid)
                except Exception:
                    s = None
        if s is not None:
            spreads.append(float(s))
            if obj.get("trade_id"):
                spread_entries.append({"trade_id": obj.get("trade_id"), "spread": float(s), "confidence": obj.get("confidence"), "entry_price": obj.get("entry_price")})

    spread_stats = stats_list(spreads)
    pct_over_0_1 = round(sum(1 for x in spreads if x > 0.1) / len(spreads) * 100, 2) if spreads else 0.0
    pct_over_0_05 = round(sum(1 for x in spreads if x > 0.05) / len(spreads) * 100, 2) if spreads else 0.0

    # Top losing trades
    losing = sorted([e for e in exits if (e.get("realized_pnl") or 0) < 0], key=lambda x: x.get("realized_pnl") or 0)
    top_losses = [{
        "trade_id": t.get("trade_id"),
        "realized_pnl": t.get("realized_pnl"),
        "exit_reason": t.get("exit_reason"),
        "confidence": t.get("confidence"),
        "spread_entry": t.get("spread_entry"),
    } for t in losing[:10]]

    out = {
        "files_scanned": files,
        "total_entries": len(entries),
        "total_exits": len(exits),
        "conf_summary": conf_summary,
        "exit_reasons": exit_reasons,
        "spread_stats": spread_stats,
        "pct_spread_over_0.10": pct_over_0_1,
        "pct_spread_over_0.05": pct_over_0_05,
        "top_losses": top_losses,
    }

    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

