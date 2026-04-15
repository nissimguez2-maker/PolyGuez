"""Regenerate the LIVE STATE block in CONTEXT.md.

Run from the repo root by the refresh-context workflow. Queries Supabase via
the PostgREST HTTP API (service key) and summarizes recent git history, then
rewrites the block between <!-- LIVE_STATE_BEGIN --> / <!-- LIVE_STATE_END -->.

Environment:
  SUPABASE_URL            — full https://<project-ref>.supabase.co
  SUPABASE_SERVICE_KEY    — service-role key (used read-only here)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta

import requests

CONTEXT_PATH = "CONTEXT.md"
BEGIN_MARK = "<!-- LIVE_STATE_BEGIN -->"
END_MARK = "<!-- LIVE_STATE_END -->"


def sh(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.rstrip()


def recent_commits() -> str:
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        out = sh([
            "git", "log",
            f"--since={since}",
            "--pretty=format:- `%h` %ad %s",
            "--date=short",
            "-n", "40",
        ])
        return out or "_no commits in the last 7 days_"
    except subprocess.CalledProcessError as e:
        return f"_error reading git log: {e}_"


def supabase_get(url: str, key: str, path: str, params: dict | None = None) -> list | dict:
    """GET from PostgREST. Returns parsed JSON."""
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    resp = requests.get(f"{url}/rest/v1/{path}", headers=headers, params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def supabase_rpc(url: str, key: str, fn: str, body: dict | None = None) -> list | dict:
    """POST to /rest/v1/rpc/<fn>. Bypasses PostgREST's ~1000-row cap by doing aggregation server-side."""
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    resp = requests.post(f"{url}/rest/v1/rpc/{fn}", headers=headers, json=body or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def trade_counts(url: str, key: str) -> str:
    try:
        rows = supabase_rpc(url, key, "rpc_trade_counts")
    except Exception as e:
        return f"_error calling rpc_trade_counts: {e}_"
    if not rows:
        return "_no trades yet_"
    rows = sorted(rows, key=lambda r: -(r.get("trades") or 0))
    lines = ["| session_tag | trades | wins | losses | total PnL (USDC) |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| `{r.get('session_tag')}` | {r.get('trades')} | {r.get('wins')} | "
            f"{r.get('losses')} | {float(r.get('total_pnl') or 0.0):+.2f} |"
        )
    return "\n".join(lines)


def shadow_counts(url: str, key: str) -> str:
    try:
        rows = supabase_rpc(url, key, "rpc_shadow_counts")
    except Exception as e:
        return f"_error calling rpc_shadow_counts: {e}_"
    if not rows:
        return "_no shadow trades yet_"
    rows = sorted(rows, key=lambda r: -(r.get("total") or 0))
    lines = ["| session_tag | total | settled | wins | losses | settled PnL |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| `{r.get('session_tag')}` | {r.get('total')} | {r.get('settled')} | "
            f"{r.get('wins')} | {r.get('losses')} | {float(r.get('settled_pnl') or 0.0):+.2f} |"
        )
    return "\n".join(lines)


def rolling_stats(url: str, key: str) -> str:
    rows = supabase_get(url, key, "rolling_stats", {"select": "id,data,updated_at", "limit": "5"})
    if not rows:
        return "_rolling_stats empty_"
    lines = []
    for r in rows:
        data = r.get("data") or {}
        lines.append(
            f"- `id={r.get('id')}` updated_at=`{r.get('updated_at')}`  "
            f"reset_token=`{data.get('reset_token')}`  "
            f"trade_count=`{data.get('trade_count')}`  "
            f"total_pnl=`{data.get('total_pnl')}`  "
            f"wins/losses=`{data.get('wins')}/{data.get('losses')}`"
        )
    return "\n".join(lines)


def active_session_tag(url: str, key: str) -> str:
    try:
        rows = supabase_get(url, key, "session_tag_current", {"select": "tag", "limit": "1"})
        if rows and isinstance(rows, list) and rows[0].get("tag"):
            return f"`{rows[0]['tag']}`"
        return "_table empty_"
    except Exception as e:
        return f"_error: {e}_"


def build_block(url: str, key: str) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        last_sha = sh(["git", "rev-parse", "--short", "HEAD"])
        last_author = sh(["git", "log", "-1", "--pretty=format:%an"])
    except subprocess.CalledProcessError:
        last_sha, last_author = "unknown", "unknown"

    parts = [
        BEGIN_MARK,
        "## LIVE STATE (auto-refreshed)",
        "",
        "_This block is regenerated by `.github/workflows/refresh-context.yml` on every push "
        "to `main` and daily at 06:00 UTC. If the \"Refreshed at\" timestamp below is more "
        "than 26 hours old, assume the auto-refresh is broken and flag it to Nessim rather "
        "than acting on the numbers._",
        "",
        f"**Refreshed at:** {now} (UTC) — commit `{last_sha}` by {last_author}",
        "",
        "### Recent commits (last 7 days)",
        "",
        recent_commits(),
        "",
        "### Trade counts (from Supabase)",
        "",
        trade_counts(url, key),
        "",
        "### Shadow trade counts (from Supabase)",
        "",
        shadow_counts(url, key),
        "",
        "### Rolling stats singleton",
        "",
        rolling_stats(url, key),
        "",
        "### Current active session_tag (from `session_tag_current`)",
        "",
        active_session_tag(url, key),
        END_MARK,
    ]
    return "\n".join(parts)


def main() -> int:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY required", file=sys.stderr)
        return 1

    with open(CONTEXT_PATH, "r", encoding="utf-8") as f:
        doc = f.read()

    new_block = build_block(url, key)

    pattern = re.compile(
        re.escape(BEGIN_MARK) + r".*?" + re.escape(END_MARK),
        re.DOTALL,
    )
    if not pattern.search(doc):
        print("LIVE_STATE markers not found in CONTEXT.md — aborting.", file=sys.stderr)
        return 2

    new_doc = pattern.sub(new_block, doc)
    if new_doc == doc:
        print("CONTEXT.md unchanged.")
        return 0

    with open(CONTEXT_PATH, "w", encoding="utf-8") as f:
        f.write(new_doc)
    print("CONTEXT.md LIVE STATE block refreshed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
