from __future__ import annotations
import argparse
import json
import csv
from pathlib import Path
from typing import Iterable, List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import statistics
import sys


def find_trade_files(roots: Iterable[str], patterns: Iterable[str]) -> List[Path]:
    roots = list(roots) or ["data", "paper_trades", "legacy", "exports", "logs"]
    patterns = list(patterns) or ["**/*.json", "**/*.jsonl", "**/*.csv"]
    out = []
    for r in roots:
        p = Path(r)
        if not p.exists():
            continue
        for pat in patterns:
            out.extend(list(p.glob(pat)))
    # dedupe and keep readable files only
    seen = set()
    files = []
    for f in out:
        try:
            if not f.is_file():
                continue
            key = str(f.resolve())
            if key in seen:
                continue
            seen.add(key)
            files.append(f)
        except Exception:
            continue
    return files


def read_trades(path: Path) -> List[Dict[str, Any]]:
    ext = path.suffix.lower()
    out = []
    try:
        if ext == ".jsonl":
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
        elif ext == ".json":
            with path.open("r", encoding="utf-8") as fh:
                obj = json.load(fh)
                # list of trades or dict containing trades
                if isinstance(obj, list):
                    out.extend(obj)
                elif isinstance(obj, dict):
                    # try common keys
                    for k in ("trades", "data", "items"):
                        if k in obj and isinstance(obj[k], list):
                            out.extend(obj[k])
                            break
                    else:
                        out.append(obj)
        elif ext == ".csv":
            with path.open("r", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    out.append(row)
        else:
            # try jsonl fallback
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
    except Exception:
        return []
    return out


def parse_ts(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        if isinstance(v, (int, float)):
            # ms vs s
            if v > 1e12:
                return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
            if v > 1e9:
                return datetime.fromtimestamp(v, tz=timezone.utc)
        s = str(v)
        if s.isdigit():
            iv = int(s)
            if iv > 1e12:
                return datetime.fromtimestamp(iv / 1000.0, tz=timezone.utc)
            if iv > 1e9:
                return datetime.fromtimestamp(iv, tz=timezone.utc)
        # ISO parse (accept Z)
        s2 = s.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s2)
        except Exception:
            # last resort: try common formats
            for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z"):
                try:
                    return datetime.strptime(s2, fmt)
                except Exception:
                    continue
    except Exception:
        return None
    return None


def normalize_trade(d: Dict[str, Any], source_file: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    out["source_file"] = source_file
    out["trade_id"] = d.get("trade_id") or d.get("id") or d.get("uuid") or d.get("order_id") or None
    # status
    status = d.get("status") or d.get("state") or None
    if status:
        status = status.lower()
        out["status"] = "closed" if "clos" in status or status in ("closed", "finished", "done") else "open"
    else:
        out["status"] = "closed" if ("realized_pnl" in d or "exit_time_utc" in d or "exit_time" in d) else "open"

    # timestamps
    opened = d.get("utc_time") or d.get("opened_at") or d.get("open_time") or d.get("entry_time") or d.get("opened")
    closed = d.get("exit_time_utc") or d.get("closed_at") or d.get("close_time") or d.get("exit_time")
    out["opened_at"] = parse_ts(opened)
    out["closed_at"] = parse_ts(closed)
    # if pnl/realized exists but closed_at missing, use opened as closed timestamp fallback
    if out["closed_at"] is None and any(k in d for k in ("realized_pnl", "pnl", "profit", "total_pnl")):
        out["closed_at"] = out["opened_at"]

    # pnl
    pnl_keys = ["realized_pnl", "pnl", "profit", "profit_usd", "pnl_usd", "total_pnl"]
    pnl = None
    for k in pnl_keys:
        if k in d and d[k] is not None:
            try:
                pnl = float(d[k])
                break
            except Exception:
                continue
    out["pnl"] = pnl

    # confidence
    conf = None
    for k in ("rawConf", "confidence", "conf"):
        if k in d and d[k] is not None:
            try:
                conf = int(float(d[k]))
                break
            except Exception:
                continue
    out["confidence"] = conf

    # exit reason / blocked reason
    out["exit_reason"] = d.get("exit_reason") or d.get("close_reason") or d.get("reason") or None
    out["blocked_reason"] = d.get("blocked_reason") or d.get("block_reason") or d.get("reject_reason") or None

    # smoke/test/paper heuristics
    fn = source_file.lower()
    tags = " ".join(str(d.get(k, "")).lower() for k in ("signal_id", "market", "note", "tag", "mode"))
    is_smoke = False
    if any(x in fn for x in ("smoke", "test", "paper", "fallback", "dev")):
        is_smoke = True
    if "smoke" in tags or "test" in tags:
        is_smoke = True
    if str(d.get("mode", "")).lower() == "paper" or d.get("paper") is True:
        out["is_paper"] = True
    else:
        out["is_paper"] = False
    out["is_smoke"] = is_smoke
    out["is_test"] = ("test" in tags) or ("smoke" in tags and not out["is_paper"])

    # other metadata
    out["side"] = d.get("side")
    out["size"] = d.get("size")
    out["raw"] = d
    return out


def compute_metrics(trades: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    trades = list(trades)
    total = len(trades)
    closed = [t for t in trades if t.get("status") == "closed" and t.get("pnl") is not None]
    open_trades = [t for t in trades if t.get("status") != "closed"]
    wins = sum(1 for t in closed if t["pnl"] > 0)
    losses = sum(1 for t in closed if t["pnl"] < 0)
    ties = sum(1 for t in closed if t["pnl"] == 0)
    pnls = [float(t["pnl"]) for t in closed]
    sum_pnl = sum(pnls) if pnls else 0.0
    avg_pnl = statistics.mean(pnls) if pnls else 0.0
    median_pnl = statistics.median(pnls) if pnls else 0.0

    by_conf: Dict[int, List[Dict[str, Any]]] = {}
    for t in closed:
        c = t.get("confidence")
        if c is None:
            c = -1
        by_conf.setdefault(c, []).append(t)

    conf_metrics = {}
    for c, items in sorted(by_conf.items()):
        vals = [float(x["pnl"]) for x in items if x.get("pnl") is not None]
        conf_metrics[str(c)] = {
            "count": len(items),
            "wins": sum(1 for x in items if x.get("pnl") and x["pnl"] > 0),
            "losses": sum(1 for x in items if x.get("pnl") and x["pnl"] < 0),
            "sum_pnl": sum(vals) if vals else 0.0,
            "avg_pnl": statistics.mean(vals) if vals else 0.0,
        }

    exit_reasons: Dict[str, int] = {}
    blocked_reasons: Dict[str, int] = {}
    for t in closed:
        er = t.get("exit_reason") or "unknown"
        exit_reasons[er] = exit_reasons.get(er, 0) + 1
        br = t.get("blocked_reason")
        if br:
            blocked_reasons[br] = blocked_reasons.get(br, 0) + 1

    return {
        "total_trades": total,
        "closed_trades": len(closed),
        "open_trades": len(open_trades),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "winrate": wins / (len(closed) or 1),
        "sum_pnl": sum_pnl,
        "avg_pnl": avg_pnl,
        "median_pnl": median_pnl,
        "by_confidence": conf_metrics,
        "exit_reasons": exit_reasons,
        "blocked_reasons": blocked_reasons,
        "closed_samples": closed,
    }


def filter_recent(trades: List[Dict[str, Any]], last_n: Optional[int], since_hours: Optional[int], tz: ZoneInfo) -> Tuple[List[Dict[str, Any]], dict]:
    now = datetime.now(tz=timezone.utc)
    res = [t for t in trades if t.get("status") == "closed" and t.get("closed_at") is not None]
    res_sorted = sorted(res, key=lambda x: x.get("closed_at") or datetime.fromtimestamp(0, tz=timezone.utc), reverse=True)
    info = {}
    if last_n:
        info["last_n"] = res_sorted[:last_n]
    if since_hours:
        cutoff = now - timedelta(hours=since_hours)
        info["since_hours"] = [t for t in res_sorted if (t.get("closed_at") or datetime.fromtimestamp(0, tz=timezone.utc)) >= cutoff]
    return res_sorted, info


def generate_markdown(report: Dict[str, Any], tz_name: str) -> str:
    lines = []
    try:
        now_tz = ZoneInfo(tz_name)
    except Exception:
        now_tz = timezone.utc
    now = datetime.now(now_tz)
    lines.append(f"# Trade Performance Report — {now.isoformat()}\n")
    def add_kv(k, v):
        lines.append(f"- **{k}**: {v}")
    add_kv("Total trades", report["all"]["total_trades"])
    add_kv("Closed trades", report["all"]["closed_trades"])
    add_kv("Open trades", report["all"]["open_trades"])
    add_kv("Wins", report["all"]["wins"])
    add_kv("Losses", report["all"]["losses"])
    add_kv("Winrate", f"{report['all']['winrate']:.3f}")
    add_kv("Sum PnL", f"{report['all']['sum_pnl']:.6f}")
    lines.append("\n## Only real trades\n")
    add_kv("Total trades", report["real"]["total_trades"])
    add_kv("Closed trades", report["real"]["closed_trades"])
    add_kv("Winrate", f"{report['real']['winrate']:.3f}")
    lines.append("\n## By confidence\n")
    lines.append("|confidence|count|wins|losses|sum_pnl|avg_pnl|")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for c, v in report["all"]["by_confidence"].items():
        lines.append(f"|{c}|{v['count']}|{v['wins']}|{v['losses']}|{v['sum_pnl']:.6f}|{v['avg_pnl']:.6f}|")

    lines.append("\n## Exit reasons\n")
    for k, v in report["all"]["exit_reasons"].items():
        lines.append(f"- {k}: {v}")

    lines.append("\n## Blocked reasons (best effort)\n")
    if report["all"]["blocked_reasons"]:
        for k, v in report["all"]["blocked_reasons"].items():
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- No blocked_reason data found in artifacts.")

    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--roots", nargs="+", default=["."], help="roots to search")
    p.add_argument("--glob", nargs="+", default=["**/*.jsonl", "**/*.json", "**/*.csv"])
    p.add_argument("--only-real", action="store_true")
    p.add_argument("--include-open", action="store_true")
    p.add_argument("--last-n", type=int, default=None)
    p.add_argument("--since-hours", type=int, default=None)
    p.add_argument("--out-md", default=None)
    p.add_argument("--out-json", default=None)
    p.add_argument("--print-blocked", action="store_true")
    p.add_argument("--timezone", default="Europe/Istanbul")
    args = p.parse_args(argv)

    files = find_trade_files(args.roots, args.glob)
    all_trades = []
    for f in files:
        records = read_trades(f)
        for r in records:
            all_trades.append(normalize_trade(r, str(f)))

    real_trades = [t for t in all_trades if not (t.get("is_smoke") or t.get("is_test") or t.get("is_paper"))]

    report_all = compute_metrics(all_trades)
    report_real = compute_metrics(real_trades)

    tz = ZoneInfo(args.timezone)
    recent_sorted, recent_info = filter_recent(all_trades, args.last_n, args.since_hours, tz)

    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "all": report_all, "real": report_real}
    if args.last_n or args.since_hours:
        out["recent"] = {
            "last_n": [t["trade_id"] for t in recent_info.get("last_n", [])],
            "since_hours": [t["trade_id"] for t in recent_info.get("since_hours", [])],
        }

    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, default=str)
    if args.out_md:
        md = generate_markdown({"all": report_all, "real": report_real}, args.timezone)
        with open(args.out_md, "w", encoding="utf-8") as fh:
            fh.write(md)
    # print summary
    print(f"Found {len(all_trades)} trades ({len(real_trades)} real). Closed={report_all['closed_trades']} wins={report_all['wins']} winrate={report_all['winrate']:.3f}")
    if args.print_blocked:
        print("Blocked reasons:", report_all["blocked_reasons"] or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

