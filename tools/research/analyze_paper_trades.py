#!/usr/bin/env python3
"""
Analyze paper trades and print a Markdown summary.

Usage:
  python tools/research/analyze_paper_trades.py
"""
from __future__ import annotations
import json
import glob
from statistics import mean, median
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import math
import argparse
from src.utils.ab_router import ab_bucket, ab_variant

# Expanded AB key candidates and list fallbacks
AB_KEYS_DEFAULT = [
    "routing_key_used", "routing_key", "router_key", "ab_key",
    "token_id", "tokenId", "clob_token_id", "clobTokenId",
    "outcome_token_id", "outcomeTokenId",
    "yes_token_id", "no_token_id",
    "token", "tokenId",
    "asset_id", "assetId",
    "market_id", "marketId",
    "signal_id", "signalId",
]

LIST_KEY_FALLBACKS = [
    "clob_token_ids", "clobTokenIds",
    "token_ids", "tokenIds",
    "outcome_token_ids", "outcomeTokenIds",
]


def _norm_key(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def deep_find_first(obj, keys):
    """Recursively search for the first occurrence of any key in keys within nested dict/list."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj:
                v = _norm_key(obj.get(k))
                if v is not None:
                    return v
        for v in obj.values():
            hit = deep_find_first(v, keys)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for it in obj:
            hit = deep_find_first(it, keys)
            if hit is not None:
                return hit
    return None


def find_ab_key(trade: Dict[str, Any], priority_keys: List[str]) -> Optional[str]:
    # 1) deep search using provided priority_keys
    k = deep_find_first(trade, priority_keys)
    if k is not None:
        return k
    # 2) try expanded defaults
    k = deep_find_first(trade, AB_KEYS_DEFAULT)
    if k is not None:
        return k
    # 3) list fallbacks e.g. clob_token_ids etc.
    if isinstance(trade, dict):
        for lk in LIST_KEY_FALLBACKS:
            v = trade.get(lk)
            if isinstance(v, list) and len(v) > 0:
                vv = _norm_key(v[0])
                if vv is not None:
                    return vv
    return None


def load_closed_trades(paths: List[str]) -> List[Dict[str, Any]]:
    # Read all lines and merge records by trade_id so we have a combined view
    trades_by_id: Dict[str, Dict[str, Any]] = {}
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    tid = obj.get("trade_id") or obj.get("id") or None
                    if not tid:
                        # skip records without a trade_id
                        continue
                    existing = trades_by_id.get(tid, {})
                    # merge: update existing with new keys (new keys overwrite)
                    merged = existing.copy()
                    merged.update(obj)
                    trades_by_id[tid] = merged
        except Exception:
            continue
    # return only those trades that have realized_pnl (i.e., closed trades)
    return [v for v in trades_by_id.values() if "realized_pnl" in v]


def summary_stats(trades: List[Dict[str, Any]]):
    pnls = [float(t.get("realized_pnl") or 0.0) for t in trades]
    total = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    breakeven = sum(1 for p in pnls if p == 0)
    winrate = (wins / total * 100.0) if total else 0.0
    avg = mean(pnls) if pnls else 0.0
    med = median(pnls) if pnls else 0.0
    avg_win = mean([p for p in pnls if p > 0]) if any(p > 0 for p in pnls) else 0.0
    avg_loss = mean([p for p in pnls if p < 0]) if any(p < 0 for p in pnls) else 0.0
    profit = sum(p for p in pnls if p > 0)
    loss = -sum(p for p in pnls if p < 0)
    profit_factor = (profit / loss) if loss > 0 else float("inf")
    expectancy = avg
    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "winrate_pct": winrate,
        "avg_pnl": avg,
        "median_pnl": med,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
    }


def bucket_by(trades: List[Dict[str, Any]], key_func, min_size: int = 1):
    buckets = {}
    for t in trades:
        k = key_func(t)
        buckets.setdefault(k, []).append(t)
    # compute stats per bucket
    out = {}
    for k, items in buckets.items():
        if len(items) < min_size:
            continue
        out[k] = summary_stats(items)
    return out


def price_bucket(price: float) -> str:
    # buckets 0-0.1, 0.1-0.2, ... 0.9-1.0
    if price is None:
        return "na"
    try:
        p = float(price)
    except Exception:
        return "na"
    idx = min(9, max(0, int(p * 10)))
    lo = idx / 10.0
    hi = (idx + 1) / 10.0
    return f"{lo:.1f}-{hi:.1f}"


def print_markdown_report(trades: List[Dict[str, Any]]):
    s = summary_stats(trades)
    print("# Paper Trades Analysis\n")
    print("## Summary")
    print(f"- Total closed trades: **{s['total']}**")
    print(f"- Wins: {s['wins']}, Losses: {s['losses']}, Breakeven: {s['breakeven']}")
    print(f"- Winrate: **{s['winrate_pct']:.2f}%**")
    print(f"- Avg PnL: {s['avg_pnl']:.6f}, Median PnL: {s['median_pnl']:.6f}")
    print(f"- Avg Win: {s['avg_win']:.6f}, Avg Loss: {s['avg_loss']:.6f}")
    print(f"- Profit factor: {s['profit_factor']:.3f}")
    print(f"- Expectancy per trade: {s['expectancy']:.6f}\n")

    # avg entry price overall and by side
    entry_prices = [float(t.get("entry_price")) for t in trades if t.get("entry_price") is not None]
    avg_entry = mean(entry_prices) if entry_prices else None
    print("## Entry Price")
    print(f"- Avg entry price (all): {avg_entry}\n")
    by_side = {}
    for t in trades:
        side = t.get("side") or "unknown"
        if t.get("entry_price") is not None:
            by_side.setdefault(side, []).append(float(t.get("entry_price")))
    for side, prices in by_side.items():
        print(f"- Avg entry price ({side}): {mean(prices):.6f}")
    print("\n")

    # Buckets: by confidence
    print("## Buckets: by confidence")
    conf_buckets = bucket_by(trades, lambda t: int(t.get("confidence") or -1), min_size=1)
    print("|confidence|count|winrate%|expectancy|avg_pnl|")
    print("|---:|---:|---:|---:|---:|")
    for k in sorted(conf_buckets.keys()):
        v = conf_buckets[k]
        print(f"|{k}|{v['total']}|{v['winrate_pct']:.2f}|{v['expectancy']:.6f}|{v['avg_pnl']:.6f}|")
    print("\n")

    # By entry price buckets
    print("## Buckets: by entry price")
    price_buckets = bucket_by(trades, lambda t: price_bucket(t.get("entry_price")), min_size=1)
    print("|bucket|count|winrate%|expectancy|")
    print("|---|---:|---:|---:|")
    for k in sorted(price_buckets.keys()):
        v = price_buckets[k]
        print(f"|{k}|{v['total']}|{v['winrate_pct']:.2f}|{v['expectancy']:.6f}|")
    print("\n")

    # By session (best-effort from session_id)
    print("## Buckets: by session")
    sess_buckets = bucket_by(trades, lambda t: (t.get("session_id") or "unknown"), min_size=1)
    for k in sess_buckets:
        v = sess_buckets[k]
    print("|session|count|winrate%|expectancy|")
    print("|---|---:|---:|---:|")
    for k in sorted(sess_buckets.keys()):
        v = sess_buckets[k]
        print(f"|{k}|{v['total']}|{v['winrate_pct']:.2f}|{v['expectancy']:.6f}|")
    print("\n")

    # By spread_pct buckets if present
    def spread_bucket(t):
        sp = t.get("spread_pct") or t.get("spread") or None
        if sp is None:
            return "na"
        try:
            spf = float(sp)
        except Exception:
            return "na"
        # bucket pct into 0.0-0.01, 0.01-0.02 etc
        idx = min(9, int(spf * 100))
        return f"{idx/100:.2f}-{(idx+1)/100:.2f}"

    print("## Buckets: by spread_pct")
    sp_buckets = bucket_by(trades, lambda t: spread_bucket(t), min_size=1)
    print("|bucket|count|winrate%|expectancy|")
    print("|---|---:|---:|---:|")
    for k in sorted(sp_buckets.keys()):
        v = sp_buckets[k]
        print(f"|{k}|{v['total']}|{v['winrate_pct']:.2f}|{v['expectancy']:.6f}|")
    print("\n")

    # Top 5 worst segments (lowest expectancy) with sample size >=5
    segs = []
    # combine confidence and price buckets
    for k, v in conf_buckets.items():
        if v['total'] >= 5:
            segs.append(("conf:"+str(k), v['expectancy'], v['total']))
    for k, v in price_buckets.items():
        if v['total'] >= 5:
            segs.append(("price:"+str(k), v['expectancy'], v['total']))
    segs_sorted = sorted(segs, key=lambda x: x[1])
    print("## Worst segments (lowest expectancy, sample>=5)")
    for seg in segs_sorted[:5]:
        print(f"- {seg[0]}: expectancy={seg[1]:.6f} (n={seg[2]})")

def analyze_trades(trades: List[Dict[str, Any]], split_ab: bool = False, ab_key_priority: Optional[List[str]] = None) -> Dict[str, Any]:
    if ab_key_priority is None:
        ab_key_priority = ["token_id", "tokenId", "asset_id", "assetId", "market_id", "marketId", "signal_id", "signalId"]

    out = {"summary": summary_stats(trades)}
    if not split_ab:
        return out

    def pick_key(t: Dict[str, Any]) -> Optional[str]:
        # try user-priority keys first (deep search), then fall back to expanded candidates
        k = find_ab_key(t, ab_key_priority)
        if k is not None:
            return k
        return None

    groups = {"control": [], "variant": [], "unknown": []}
    for t in trades:
        key = pick_key(t)
        if key is None:
            groups["unknown"].append(t)
            continue
        if ab_bucket(key) == 1:
            groups["variant"].append(t)
        else:
            groups["control"].append(t)

    ab_summary = {k: summary_stats(groups[k]) for k in groups}
    delta = {
        "winrate_delta_pct": ab_summary["variant"]["winrate_pct"] - ab_summary["control"]["winrate_pct"],
        "expectancy_delta": ab_summary["variant"]["expectancy"] - ab_summary["control"]["expectancy"],
        "profit_factor_delta": ab_summary["variant"]["profit_factor"] - ab_summary["control"]["profit_factor"],
    }
    out["ab_split"] = {"groups": ab_summary, "delta": delta}
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split-ab", action="store_true", help="Enable A/B split report")
    parser.add_argument("--ab-key-priority", type=str, default="token_id,market_id,signal_id", help="Comma-separated key priority for AB routing")
    parser.add_argument("--out-json", type=str, default=None, help="Optional JSON output file")
    args = parser.parse_args()

    settings_files = []
    p = Path("paper_trades.jsonl")
    if p.exists() and p.stat().st_size > 0:
        settings_files.append(str(p))
    else:
        settings_files.extend(sorted(glob.glob("paper_trades_legacy*.jsonl")))
    trades = load_closed_trades(settings_files)

    if not args.split_ab:
        print_markdown_report(trades)
        if args.out_json:
            with open(args.out_json, "w", encoding="utf-8") as fh:
                json.dump({"summary": summary_stats(trades)}, fh, indent=2)
        return

    ab_keys = [k.strip() for k in args.ab_key_priority.split(",") if k.strip()]
    res = analyze_trades(trades, split_ab=True, ab_key_priority=ab_keys)

    print_markdown_report(trades)
    print("# A/B Split Summary\n")
    for grp in ("control", "variant", "unknown"):
        g = res["ab_split"]["groups"].get(grp, {})
        print(f"## {grp.capitalize()}")
        print(f"- count: {g.get('total', 0)}")
        print(f"- wins: {g.get('wins',0)}, losses: {g.get('losses',0)}, breakeven: {g.get('breakeven',0)}")
        print(f"- winrate: {g.get('winrate_pct',0.0):.2f}%")
        print(f"- avg_pnl: {g.get('avg_pnl',0.0):.6f}")
        print(f"- expectancy: {g.get('expectancy',0.0):.6f}")
        print(f"- profit_factor: {g.get('profit_factor',0.0):.3f}\n")

    print("## Delta (variant - control)")
    d = res["ab_split"]["delta"]
    print(f"- winrate delta (pct): {d.get('winrate_delta_pct',0.0):.2f}")
    print(f"- expectancy delta: {d.get('expectancy_delta',0.0):.6f}")
    print(f"- profit_factor delta: {d.get('profit_factor_delta',0.0):.3f}")

    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2)


if __name__ == "__main__":
    main()

