"""Backfill Polymarket-resolved market outcomes into signal_log.

Strategy
--------
`signal_log.outcome` + `outcome_ts` are declared in the schema but never
written by the runtime. Without authoritative resolutions we cannot:
  * score the logistic prior (Brier on terminal_probability)
  * validate shadow-trade settlement (bot BTC-feed vs Polymarket oracle)
  * compute per-signal win/loss for calibration reports

For every distinct `market_id` in signal_log with `outcome IS NULL` we hit
Gamma, read the resolved winner, and patch every matching signal_log row
with `outcome='up'|'down'` (the market's resolved side, not a per-signal
win flag) and `outcome_ts=<market_end_date>`.

Idempotent: the UPDATE filter is `outcome=is.null`, so re-runs only fill
gaps. Safe on live data — no DELETE, no overwrite.

Usage
-----
    # Dry-run preview (no writes) — default
    python scripts/python/backfill_market_outcomes.py --era V5

    # Actually write
    python scripts/python/backfill_market_outcomes.py --era V5 --commit

    # Bound the run while testing
    python scripts/python/backfill_market_outcomes.py --era V5 --limit-markets 20

Environment
-----------
    SUPABASE_URL          full https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY  service-role key (needed for UPDATE)
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_shadows import fetch_market_resolution  # noqa: E402

GAMMA_BASE = "https://gamma-api.polymarket.com"


def _sb_headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def fetch_unresolved_market_ids(url: str, key: str, era: str | None) -> list[str]:
    """Distinct market_ids in signal_log that still have no outcome."""
    params = {
        "select": "market_id",
        "outcome": "is.null",
        "market_id": "not.is.null",
        "limit": "200000",
    }
    if era:
        params["era"] = f"eq.{era}"
    r = requests.get(f"{url}/rest/v1/signal_log", headers=_sb_headers(key), params=params, timeout=60)
    r.raise_for_status()
    seen: dict[str, None] = {}
    for row in r.json():
        mid = row.get("market_id")
        if mid:
            seen.setdefault(mid, None)
    return list(seen.keys())


def fetch_market_end_date(market_id: str) -> str | None:
    """Gamma endDate (ISO timestamp) for outcome_ts, or None if missing."""
    try:
        r = requests.get(f"{GAMMA_BASE}/markets/{market_id}", timeout=15)
        if r.status_code != 200:
            return None
        m = r.json()
    except Exception:
        return None
    return m.get("endDate") or m.get("closedTime") or None


def patch_market(url: str, key: str, market_id: str, era: str | None, outcome: str, outcome_ts: str | None) -> int:
    """Update every signal_log row for (market_id, era) where outcome IS NULL.

    Returns number of rows patched (Prefer: return=minimal so we use count=exact).
    """
    params = {
        "market_id": f"eq.{market_id}",
        "outcome": "is.null",
    }
    if era:
        params["era"] = f"eq.{era}"
    payload: dict = {"outcome": outcome}
    if outcome_ts:
        payload["outcome_ts"] = outcome_ts
    headers = {**_sb_headers(key), "Prefer": "return=minimal,count=exact"}
    r = requests.patch(
        f"{url}/rest/v1/signal_log",
        headers=headers,
        params=params,
        json=payload,
        timeout=30,
    )
    if r.status_code >= 300:
        print(f"  patch failed market={market_id}: {r.status_code} {r.text[:200]}", file=sys.stderr)
        return 0
    content_range = r.headers.get("Content-Range", "")
    if "/" in content_range:
        try:
            return int(content_range.split("/", 1)[1])
        except (ValueError, IndexError):
            return 0
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--era", default="V5", help="era tag to backfill (default V5). Pass empty string to skip the era filter.")
    p.add_argument("--commit", action="store_true", help="actually write (default: dry-run preview)")
    p.add_argument("--limit-markets", type=int, default=0, help="cap markets processed (0 = no cap)")
    args = p.parse_args()

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY required", file=sys.stderr)
        return 1

    era = args.era if args.era else None
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"[{mode}] backfill market outcomes into signal_log (era={era or 'ALL'})")

    market_ids = fetch_unresolved_market_ids(url, key, era)
    print(f"{len(market_ids)} distinct markets with NULL outcome")
    if args.limit_markets:
        market_ids = market_ids[: args.limit_markets]
        print(f"limited to first {len(market_ids)} markets")
    if not market_ids:
        return 0

    total_patched = 0
    skipped_open = 0
    skipped_unresolved = 0
    for idx, mid in enumerate(market_ids, 1):
        winner, closed = fetch_market_resolution(mid)
        if not closed:
            skipped_open += 1
            if idx % 25 == 0:
                print(f"[{idx}/{len(market_ids)}] {mid}: still open, skip")
            time.sleep(0.05)
            continue
        if winner is None:
            skipped_unresolved += 1
            print(f"[{idx}/{len(market_ids)}] {mid}: closed but no clear winner, skip")
            time.sleep(0.05)
            continue

        outcome_ts = fetch_market_end_date(mid)
        if args.commit:
            n = patch_market(url, key, mid, era, winner, outcome_ts)
            total_patched += n
            print(f"[{idx}/{len(market_ids)}] {mid}: winner={winner} outcome_ts={outcome_ts} patched={n} rows")
        else:
            print(f"[{idx}/{len(market_ids)}] {mid}: winner={winner} outcome_ts={outcome_ts} (would patch)")
        time.sleep(0.05)

    print()
    print(f"done. {mode}: {total_patched} rows {'patched' if args.commit else 'would be patched'}")
    print(f"     skipped (still open): {skipped_open} markets")
    print(f"     skipped (no clear winner): {skipped_unresolved} markets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
