#!/usr/bin/env python3
"""Generate PolyGuez briefs for the OpenClaw main agent.

Usage:
    python scripts/python/brief_generator.py --kind full
    python scripts/python/brief_generator.py --kind short

Prints a ready-to-send Telegram-style text brief to stdout. The main agent
wraps this in a Telegram send; see `docs/openclaw/main_soul_briefs_addendum.md`.

Composition:
    * `trader_summary.py`   -> trade counts, win rate, PnL, fees, Brier
    * `signal_analysis.py`  -> signal volume, fire rate, top blocker (24h)
    * `bot_health.py`       -> status, time since last signal / trade
    * `trade_log` (direct)  -> trades today (Israel day)

Adapts field names to the *actual* `trader_summary.py` output:
    closed_trades, wins, losses, win_rate (0-1), total_pnl,
    total_fees_paid, net_pnl_after_fees, calibration.brier_score, ...

`min_net_edge` in the "LIVE GATE" block reflects the *gross* entry gate
(`min_terminal_edge`) because MODEL-05 (net_edge gate) is still open per
SYSTEM.md. The brief labels this as "gross" so the reader is not misled.

Environment:
    SUPABASE_URL, SUPABASE_SERVICE_KEY  (inherited by child scripts).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


# Repo root = two levels up from this file (scripts/python/brief_generator.py)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PY = sys.executable or "python3"


# ------- helpers -----------------------------------------------------------


def _run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"stderr: {proc.stderr.strip()}"
        )
    return json.loads(proc.stdout)


def _classify_brier(brier) -> str:
    if brier is None:
        return "UNKNOWN"
    try:
        b = float(brier)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if b <= 0.20:
        return "OK"
    if b <= 0.30:
        return "BORDERLINE"
    return "BAD"


def _fmt(val, spec: str, fallback: str = "n/a") -> str:
    """Safe format: returns fallback if val is None / not numeric."""
    if val is None:
        return fallback
    try:
        return format(float(val), spec)
    except (TypeError, ValueError):
        return fallback


def _trades_today(session: str, tz: ZoneInfo) -> dict:
    """Count trades since start-of-today in Israel time. Soft-fails."""
    result = {"trades_today": None, "wins_today": None, "losses_today": None}
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return result
    try:
        from supabase import create_client
    except ImportError:
        return result
    try:
        client = create_client(url, key)
    except Exception:
        return result

    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)

    try:
        rows = (
            client.table("trade_log")
            .select("outcome")
            .eq("session_tag", session)
            .gte("ts", start_utc.isoformat())
            .execute()
            .data
            or []
        )
    except Exception:
        return result

    result["trades_today"] = len(rows)
    result["wins_today"] = sum(1 for r in rows if r.get("outcome") == "win")
    result["losses_today"] = sum(
        1 for r in rows if r.get("outcome") in ("loss", "emergency-exit")
    )
    return result


def _live_gate_defaults() -> dict:
    """Pull entry-gate defaults from PolyGuezConfig so the brief tracks config drift."""
    defaults = {
        "min_terminal_edge": None,
        "live_fok_net_edge_min": None,
        "model_05_open": True,
    }
    try:
        sys.path.insert(0, REPO_ROOT)
        from agents.utils.objects import PolyGuezConfig  # type: ignore

        cfg = PolyGuezConfig()
        defaults["min_terminal_edge"] = cfg.min_terminal_edge
        defaults["live_fok_net_edge_min"] = cfg.live_fok_net_edge_min
    except Exception:
        pass
    return defaults


# ------- main --------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="PolyGuez brief generator")
    parser.add_argument("--kind", choices=["full", "short"], default="full")
    parser.add_argument("--session", default="V5")
    args = parser.parse_args()

    tz = ZoneInfo("Asia/Jerusalem")
    now = datetime.now(tz)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    trader = _run_json([PY, "scripts/python/trader_summary.py",
                        "--session", args.session, "--limit", "1000"])
    signals = _run_json([PY, "scripts/python/signal_analysis.py",
                         "--session", args.session])
    health = _run_json([PY, "scripts/python/bot_health.py",
                        "--session", args.session])
    today = _trades_today(args.session, tz)
    gate = _live_gate_defaults()

    # ---- trader metrics ----
    rolling = trader.get("rolling_stats") or {}
    trades_total = (
        rolling.get("trade_count")
        if isinstance(rolling.get("trade_count"), int)
        else trader.get("closed_trades", 0)
    )
    wins = trader.get("wins") or 0
    losses = trader.get("losses") or 0
    win_rate_frac = trader.get("win_rate")
    win_rate_pct = (win_rate_frac * 100.0) if win_rate_frac is not None else 0.0

    gross_pnl = trader.get("total_pnl") or 0.0
    fees = trader.get("total_fees_paid") or 0.0
    net_pnl = trader.get("net_pnl_after_fees")
    if net_pnl is None:
        net_pnl = float(gross_pnl) - float(fees)

    calibration = trader.get("calibration") or {}
    brier = calibration.get("brier_score")
    brier_label = _classify_brier(brier)

    # ---- bot health ----
    status = health.get("status", "unknown")
    mins_sig = health.get("minutes_since_last_signal")
    mins_trade = health.get("minutes_since_last_trade")

    # ---- signals ----
    signals_24h = signals.get("signals_24h") or 0
    fired_24h = signals.get("fired_24h") or 0
    fire_rate_24h = signals.get("fire_rate_24h") or 0.0
    top_blocker = signals.get("top_blocker") or {}
    tb_name = top_blocker.get("gate", "-")
    tb_pct = top_blocker.get("blocked_pct", 0.0)

    # ---- live gate ----
    pass_trades = "PASS" if (trades_total and trades_total >= 100) else "FAIL"
    if brier is None:
        pass_brier = "NO DATA"
    else:
        try:
            pass_brier = "PASS" if float(brier) <= 0.25 else "FAIL"
        except (TypeError, ValueError):
            pass_brier = "NO DATA"
    gate_gross_threshold = gate.get("min_terminal_edge")

    # ---- build brief ----
    mins_sig_s = f"{mins_sig} min ago" if mins_sig is not None else "unknown"
    mins_trade_s = f"{mins_trade} min ago" if mins_trade is not None else "none today"

    trades_today_s = (
        f"{today['trades_today']} ({today['wins_today']}W/{today['losses_today']}L)"
        if today.get("trades_today") is not None
        else "n/a"
    )

    if args.kind == "full":
        lines = [
            f"POLYGUEZ BRIEF - {date_str} {time_str} IDT",
            "",
            "BOT",
            f"  Status        : {status}",
            f"  Last signal   : {mins_sig_s}",
            f"  Last trade    : {mins_trade_s}",
            f"  Signals (24h) : {signals_24h}  |  Fired: {fired_24h}"
            f"  |  Fire rate: {fire_rate_24h}%",
            f"  Top blocker   : {tb_name} ({tb_pct}% of rejects)",
            "",
            f"PERFORMANCE - {args.session}",
            f"  Trades (V5)   : {trades_total}  |  Today: {trades_today_s}",
            f"  Wins/Losses   : {wins}/{losses}",
            f"  Win rate      : {_fmt(win_rate_pct, '.1f')}%",
            f"  Gross PnL     : {_fmt(gross_pnl, '.2f')} USDC",
            f"  Fees paid     : {_fmt(fees, '.2f')} USDC",
            f"  Net PnL       : {_fmt(net_pnl, '.2f')} USDC",
            f"  Brier ({args.session})    : {_fmt(brier, '.4f')}  [{brier_label}]",
            "",
            "LIVE GATE",
            f"  Trades        : {trades_total} / 100  [{pass_trades}]",
            f"  Brier         : {_fmt(brier, '.4f')} / 0.25  [{pass_brier}]",
            f"  Entry gate    : {_fmt(gate_gross_threshold, '.3f')} (gross)"
            f"  / 0.02 net target  [MODEL-05 PENDING]",
            "  Kill-switch   : dry-run (mode locked per SYSTEM.md)",
            "",
            "AGENTS (last 24h)",
            "  main          : TODO heartbeats / alerts (wire counters)",
            "  trader        : TODO summary calls",
            "  operator      : TODO health/log calls",
            "  developer     : TODO files edited, PRs touched",
            "  architect     : TODO strategy sessions",
            "",
            "AGENT ACTIVITY (since last brief)",
            "  trader    : TODO",
            "  operator  : TODO",
            "  developer : TODO",
            "  architect : TODO",
            "",
            "SYNTHESIS",
            "  - TODO bullet 1 (main agent fills this in from its own context)",
            "  - TODO bullet 2",
            "  - TODO bullet 3",
        ]
        print("\n".join(lines))

    else:  # short
        lines = [
            f"POLYGUEZ BRIEF - {time_str} IDT",
            "",
            f"BOT      : {status}, last signal {mins_sig_s}, last trade {mins_trade_s}",
            f"PERF {args.session}  : trades {trades_total}, win {_fmt(win_rate_pct, '.1f')}%,"
            f" net {_fmt(net_pnl, '.2f')} USDC, Brier {_fmt(brier, '.3f')}",
            f"LIVE     : {trades_total}/100 trades, Brier {_fmt(brier, '.3f')}/0.25,"
            f" entry gate {_fmt(gate_gross_threshold, '.3f')} (gross, MODEL-05 pending)"
            f" [{pass_trades}/{pass_brier}]",
            "AGENTS   : main TODO alerts, trader TODO calls, dev TODO edits",
            "",
            "SYNTHESIS",
            "  - TODO (fill only if notable this slot)",
        ]
        print("\n".join(lines))

    return 0


if __name__ == "__main__":
    sys.exit(main())
