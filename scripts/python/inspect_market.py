#!/usr/bin/env python3
"""Inspect full Gamma API response for BTC 5-min markets.

Dumps every field so we can find where Price-to-Beat actually lives.
"""

import json
import time

import httpx

GAMMA_URL = "https://gamma-api.polymarket.com"
HEADERS = {"User-Agent": "PolyGuez/1.0", "Accept": "application/json"}
TIMEOUT = 15.0


def fetch_json(url, params=None):
    resp = httpx.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
    print(f"\n{'='*80}")
    print(f"GET {resp.url}  →  HTTP {resp.status_code}")
    print(f"{'='*80}")
    if resp.status_code != 200:
        print(f"ERROR: {resp.text[:500]}")
        return None
    data = resp.json()
    print(json.dumps(data, indent=2, default=str))
    return data


def main():
    now = int(time.time())
    current_window = now - (now % 300)
    windows = {
        "previous": current_window - 300,
        "current": current_window,
        "next": current_window + 300,
    }

    found_event_ids = []

    # --- Query events by slug for each window ---
    for label, ts in windows.items():
        slug = f"btc-updown-5m-{ts}"
        print(f"\n\n{'#'*80}")
        print(f"# {label.upper()} WINDOW — slug: {slug}  (ts={ts})")
        print(f"{'#'*80}")

        data = fetch_json(f"{GAMMA_URL}/events", params={"slug": slug})
        if data and isinstance(data, list) and len(data) > 0:
            event = data[0]
            event_id = event.get("id")
            if event_id:
                found_event_ids.append((label, event_id, slug))

            # Print all top-level keys of the event
            print(f"\n--- Event top-level keys ({len(event)} fields): ---")
            for key in sorted(event.keys()):
                val = event[key]
                if isinstance(val, (list, dict)):
                    print(f"  {key}: <{type(val).__name__} len={len(val)}>")
                else:
                    print(f"  {key}: {val!r}")

            # Print all keys of each nested market
            markets = event.get("markets", [])
            for i, mkt in enumerate(markets):
                print(f"\n--- Event market[{i}] top-level keys ({len(mkt)} fields): ---")
                for key in sorted(mkt.keys()):
                    val = mkt[key]
                    if isinstance(val, (list, dict)):
                        print(f"  {key}: <{type(val).__name__} len={len(val)}>")
                    elif isinstance(val, str) and len(val) > 200:
                        print(f"  {key}: {val[:200]!r}...")
                    else:
                        print(f"  {key}: {val!r}")
        else:
            print("(no events found for this slug)")

    # --- Query /markets for each found event ---
    for label, event_id, slug in found_event_ids:
        print(f"\n\n{'#'*80}")
        print(f"# MARKETS for event {event_id} ({label} window, slug={slug})")
        print(f"{'#'*80}")

        data = fetch_json(f"{GAMMA_URL}/markets", params={"event_slug": slug})
        if data and isinstance(data, list):
            for i, mkt in enumerate(data):
                print(f"\n--- Market[{i}] top-level keys ({len(mkt)} fields): ---")
                for key in sorted(mkt.keys()):
                    val = mkt[key]
                    if isinstance(val, (list, dict)):
                        print(f"  {key}: <{type(val).__name__} len={len(val)}>")
                    elif isinstance(val, str) and len(val) > 200:
                        print(f"  {key}: {val[:200]!r}...")
                    else:
                        print(f"  {key}: {val!r}")


if __name__ == "__main__":
    main()
