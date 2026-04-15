# CLAUDE.md — instructions for Claude Code and Cowork when working in this repo

> This file is read automatically by Claude Code on every session. It's also
> uploaded to the Claude.ai Project. Keep it short and point to `CONTEXT.md`
> for live state.

## First thing, every session
1. **Read `CONTEXT.md` in full.** It is the current source of truth for: who the user is,
   what's live in production, which session tag is active, what changed most recently,
   and what's pending. Don't ask Nessim to re-explain any of it.
2. **Read `docs/UPDATE-CONTEXT.md`** to learn when and how to update `CONTEXT.md`.

## Working style (Nessim's standing preferences)
- Short answers. Lead with the action, not the explanation.
- Don't make Nessim open a terminal. Do the work through tools.
- Fix first, explain second — and only if asked.
- No emojis. No trailing "let me know if…" boilerplate.

## Before merging / deploying / changing config
- Any change to `agents/utils/objects.py::PolyGuezConfig` defaults → update the "Current config" table in `CONTEXT.md`.
- Any session-tag bump → update "Current session" section in `CONTEXT.md` *and* bump the `reset_token` constant in `PolyGuezConfig` so the Supabase singleton wins.
- Any infra change (Railway, Supabase, Render, GitHub) → update "Infrastructure" table.
- Any new architectural decision or "we decided X because Y" → add to "Pending / Phase 2" or a new section in `CONTEXT.md`.

## Live-trading rules (do not violate without explicit confirmation)
- Mode stays `dry-run` unless Nessim types `CONFIRM` in the dashboard.
- Do not loosen `min_terminal_edge`, `velocity_ok`, or `oracle_gap_ok` gates without calibrated outcome data.
- Do not change the logistic steepness `k = 0.035` without evidence.
- Do not go live until there's a clean V5 run with stable win rate (≥100 trades suggested).

## What's in the repo
- `agents/application/run_polyguez.py` — main async loop (discover → entry window → hold → settle)
- `agents/strategies/polyguez_strategy.py` — signal eval + position sizing + execute_entry
- `agents/strategies/btc_feed.py` — multi-source BTC price feed with Binance WS + RTDS + REST fallback
- `agents/strategies/market_discovery.py` — deterministic slug `btc-updown-5m-{window_ts}`
- `agents/connectors/chainlink_feed.py` — Polygon aggregator on-chain read
- `agents/polymarket/` — Gamma (discovery) + CLOB (execution)
- `agents/utils/` — config model, logger, Supabase logger, vol tracker
- `scripts/python/` — CLI (`cli.py`), FastAPI dashboard server (`server.py`), migration scripts
- `scripts/frontend/` — dashboard HTML + JS (config/charts/polling/init)
- `supabase/` — schema + migrations
- `tests/` — pytest suite

## Supabase project
- Project ID: `rapmxqnxsobvxqtfnwqh` (region ap-south-1, Mumbai)
- Tables: `signal_log`, `trade_log`, `shadow_trade_log`, `rolling_stats` (singleton), `trade_archive`, `rolling_stats_archive`, `session_tag_current`
- Dashboards filter by `session_tag = (SELECT tag FROM session_tag_current)` — update that row to flip the active dashboard session.
