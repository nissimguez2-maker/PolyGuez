# CLAUDE.md — instructions for every Claude surface working on PolyGuez

> Claude Code reads this file automatically on session start. The Claude.ai Project has this
> file in its knowledge. Cowork's memory points at this file. Keep it short.

## First thing, every conversation (non-negotiable)

1. **Fetch the latest `CONTEXT.md` directly from GitHub** before doing anything else:
   `https://raw.githubusercontent.com/nissimguez2-maker/PolyGuez/main/CONTEXT.md`
   Use `web_fetch`, `curl`, or whatever tool is available. Do **not** trust any older
   cached copy. The file on GitHub is the only source of truth.

2. **Check the `LIVE STATE` block's "Refreshed at" timestamp.** If it is more than 26 hours
   old, the auto-refresh GitHub Action is broken. Stop, tell Nessim, and offer to debug
   `.github/workflows/refresh-context.yml` — do not act on stale numbers.

3. **Read `CONTEXT.md` in full.** Do not ask Nessim to re-explain session state, config,
   infra, or recent changes — CONTEXT.md has all of it.

## Working style (standing preferences)

- Short answers. Lead with the action, not the explanation.
- Don't make Nessim open a terminal. Do the work through tools.
- Fix first, explain second — and only if asked.
- No emojis. No trailing "let me know if…" boilerplate.

## Before merging / deploying / changing config

- Any change to `agents/utils/objects.py::PolyGuezConfig` defaults → update the "Current
  config" table in CONTEXT.md **in the same PR**.
- Any session-tag bump → update "Current session" section in CONTEXT.md *and* bump the
  `reset_token` constant in `PolyGuezConfig` so the Supabase singleton wins.
- Any infra change (Railway, Supabase, Render, GitHub) → update the "Infrastructure" table.
- New architectural decision ("we decided X because Y") → add to "Pending / Phase 2" or a
  new section in CONTEXT.md.

## Live-trading rules (do not violate without explicit confirmation)

- Mode stays `dry-run` unless Nessim types `CONFIRM` in the dashboard.
- Do not loosen `min_terminal_edge`, `velocity_ok`, `oracle_gap_ok`, or the entry-price band
  without calibrated outcome data.
- Do not change the logistic steepness `k = 0.035` without evidence.
- Do not go live until ≥100 clean V5 trades with stable win rate.

## What's in the repo (quick map)

- `agents/application/run_polyguez.py` — main async loop (discover → entry window → hold → settle)
- `agents/strategies/polyguez_strategy.py` — signal eval + position sizing + execute_entry
- `agents/strategies/btc_feed.py` — multi-source BTC price feed
- `agents/strategies/market_discovery.py` — deterministic slug `btc-updown-5m-{window_ts}`
- `agents/connectors/chainlink_feed.py` — Polygon aggregator on-chain read
- `agents/polymarket/` — Gamma (discovery) + CLOB (execution)
- `agents/utils/` — config, logger, Supabase logger, vol tracker
- `scripts/python/` — CLI, FastAPI dashboard server, migrations
- `scripts/frontend/` — dashboard HTML + JS
- `supabase/` — schema + migrations
- `.github/workflows/refresh-context.yml` — auto-refreshes CONTEXT.md's LIVE STATE block

## Supabase

- Project ID: `rapmxqnxsobvxqtfnwqh` (region ap-south-1, Mumbai)
- Dashboards filter by `session_tag = (SELECT tag FROM session_tag_current)` — update that
  row to flip the active dashboard session.
