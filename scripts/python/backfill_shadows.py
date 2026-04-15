"""Backfill settlement for unresolved shadow_trade_log rows.

Strategy
--------
Rather than re-fetching historical Chainlink prices (expensive + fragile), we
ask Polymarket's Gamma API for each market's resolution and back-settle every
shadow for that market. This works for any market the exchange has already
resolved (which is all of them older than ~15 min).

For each unsettled shadow:
  * If the market is resolved and shadow.direction matches the winning
    outcome → outcome='win', pnl = (1 - entry_price) * size
  * If resolved and direction loses → outcome='loss', pnl = -entry_price * size
  * If the market is still open on Gamma, skip (the live settlement loop will
    pick it up once Railway redeploys the new BTC-feed settlement path).

Size defaults to $10 when shadow.size_usdc is NULL (matches the dry-run sizing
used historically).

Usage
-----
    # Dry-run preview (no writes) — default
    python scripts/python/backfill_shadows.py --session V5

    # Actually write settlements
    python scripts/python/backfill_shadows.py --session V5 --commit

    # All sessions at once
    python scripts/python/backfill_shadows.py --all --commit

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
from collections import defaultdict

import requests

GAMMA_BASE = "https://gamma-api.polymarket.com"
DEFAULT_SIZE_USDC = 10.0
BATCH = 50


def _sb_headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def fetch_unsettled(url: str, key: str, session: str | None) -> list[dict]:
    params = {
        "select": "id,market_id,direction,entry_price,size_usdc,session_tag",
        "settled": "eq.false",
        "order": "market_id.asc,id.asc",
        "limit": "200000",
    }
    if session:
        params["session_tag"] = f"eq.{session}"
    r = requests.get(f"{url}/rest/v1/shadow_trade_log", headers=_sb_headers(key), params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_market_resolution(market_id: str) -> tuple[str | None, bool]:
    """Return (winning_outcome_lower, is_closed). winning_outcome is 'up', 'down', or None."""
    try:
        r = requests.get(f"{GAMMA_BASE}/markets/{market_id}", timeout=15)
        if r.status_code == 404:
            return None, False
        r.raise_for_status()
        m = r.json()
    except Exception as e:
        print(f"  gamma error for {market_id}: {e}", file=sys.stderr)
        return None, False

    closed = bool(m.get("closed")) or bool(m.get("resolved"))
    if not closed:
        return None, False

    # Gamma returns outcomes as a JSON-encoded string list and
    # outcomePrices as a list of "0" / "1" strings marking the winner.
    outcomes = m.get("outcomes")
    prices = m.get("outcomePrices")
    try:
        if isinstance(outcomes, str):
            import json as _j
            outcomes = _j.loads(outcomes)
        if isinstance(prices, str):
            import json as _j
            prices = _j.loads(prices)
    except Exception:
        outcomes, prices = None, None

    if not outcomes or not prices or len(outcomes) != len(prices):
        return None, closed

    winner = None
    for name, px in zip(outcomes, prices):
        if str(px).strip() in ("1", "1.0"):
            winner = str(name).strip().lower()
            break

    if winner in ("up", "yes"):
        return "up", closed
    if winner in ("down", "no"):
        return "down", closed
    return None, closed


def settle_rows(url: str, key: str, rows: list[dict], winner: str) -> int:
    """Update a batch of shadow rows with outcome+pnl."""
    n = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        for row in batch:
            size = row.get("size_usdc") or DEFAULT_SIZE_USDC
            ep = float(row.get("entry_price") or 0.0)
            win = (row.get("direction") or "").lower() == winner
            outcome = "win" if win else "loss"
            pnl = (1.0 - ep) * size if win else -ep * size
            payload = {"settled": True, "outcome": outcome, "pnl": pnl}
            r = requests.patch(
                f"{url}/rest/v1/shadow_trade_log?id=eq.{row['id']}",
                headers=_sb_headers(key),
                json=payload,
                timeout=30,
            )
            if r.status_code >= 300:
                print(f"  patch failed id={row['id']}: {r.status_code} {r.text[:200]}", file=sys.stderr)
                continue
            n += 1
    return n


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--session", help="session_tag to backfill (e.g. V5)")
    p.add_argument("--all", action="store_true", help="backfill every session_tag")
    p.add_argument("--commit", action="store_true", help="actually write (default: dry-run)")
    p.add_argument("--limit-markets", type=int, default=0, help="cap markets processed (0 = no cap)")
    args = p.parse_args()

    if not args.session and not args.all:
        p.error("must pass --session <tag> or --all")

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY required", file=sys.stderr)
        return 1

    mode = "COMMIT" if args.commit else "DRY-RUN"
    target = "ALL" if args.all else args.session
    print(f"[{mode}] backfill shadows for session_tag={target}")

    rows = fetch_unsettled(url, key, None if args.all else args.session)
    print(f"fetched {len(rows)} unsettled rows")
    if not rows:
        return 0

    # group by market_id
    by_market: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        mid = r.get("market_id")
        if mid:
            by_market[mid].append(r)

    markets = list(by_market.keys())
    if args.limit_markets:
        markets = markets[: args.limit_markets]
    print(f"{len(markets)} unique markets to resolve")

    total_settled = 0
    skipped_open = 0
    skipped_unresolved = 0
    for idx, mid in enumerate(markets, 1):
        batch_rows = by_market[mid]
        winner, closed = fetch_market_resolution(mid)
        if not closed:
            skipped_open += 1
            if idx % 25 == 0:
                print(f"[{idx}/{len(markets)}] {mid}: still open, skip ({len(batch_rows)} rows)")
            time.sleep(0.05)
            continue
        if winner is None:
            skipped_unresolved += 1
            print(f"[{idx}/{len(markets)}] {mid}: closed but no clear winner, skip ({len(batch_rows)} rows)")
            time.sleep(0.05)
            continue

        if args.commit:
            n = settle_rows(url, key, batch_rows, winner)
            total_settled += n
            print(f"[{idx}/{len(markets)}] {mid}: winner={winner} settled={n}/{len(batch_rows)}")
        else:
            preview_n = len(batch_rows)
            total_settled += preview_n
            print(f"[{idx}/{len(markets)}] {mid}: winner={winner} would-settle={preview_n}")
        time.sleep(0.05)

    print()
    print(f"done. {mode}: {total_settled} rows {'settled' if args.commit else 'would be settled'}")
    print(f"     skipped (still open): {skipped_open} markets")
    print(f"     skipped (unresolved): {skipped_unresolved} markets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
