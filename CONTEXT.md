# PolyGuez — Project Context

> **Read this first, every new conversation.** It is the single source of truth for where
> PolyGuez stands. Live numbers (trade counts, PnL, recent commits) are auto-refreshed from
> Supabase and git by a GitHub Action — they are accurate up to the timestamp inside the
> `LIVE STATE` block below. Stable facts (rules, architecture, config, infra) are hand-edited.
>
> Raw URL of this file (fetch this directly in any new chat):
> `https://raw.githubusercontent.com/nissimguez2-maker/PolyGuez/main/CONTEXT.md`

---

## Owner

Nessim — non-developer, finance background, based in Israel. Communication style: short,
direct, fix-don't-explain, lead with action. Does not use their phone for PolyGuez work.
Goal: passive income from algo trading, target $60–70/day when live.

---

## What PolyGuez does

Trades Polymarket's 5-minute BTC binary markets ("Will BTC close Up or Down vs opening price?").
Strategy: compare the real-time Chainlink oracle BTC price to the market's **price-to-beat**
(P2B) strike, compute a terminal-probability edge via a logistic model
`P = 1/(1+e^(-k·Δ))` with `k = 0.035 / sqrt(seconds_remaining/60)`, and fire a trade when
edge + price + liquidity + consensus conditions all pass. Execution: maker GTD limit orders
via py-clob-client with a FOK market-order fallback. All signals and trades log to Supabase
for post-hoc calibration.

---

## Current session: **V5 (clean era)** — started 2026-04-15

V5 was designed with Perplexity on 2026-04-15 and committed in a burst the same day. It is a
full reset: `rolling_stats.reset_token = "V5-CLEAN"` forces every running bot to discard its
local cache on boot and load the clean singleton from Supabase. All `signal_log` / `trade_log`
rows written from V5 onward carry `era = "V5"` permanently so pre-V5 data can never contaminate
dashboards again.

### V5 design intent
- Tighten entry gates so we only take high-conviction trades.
- Replace the daily-loss hard stop with tiered size reduction (so losing days don't kill the
  day's data collection).
- Make the clean-era boundary provably permanent via `era` column + `reset_token`.
- Rebuild dashboard with real KPIs and live signal visibility (shadcn dark design).

---

## Current config (defaults in `agents/utils/objects.py::PolyGuezConfig`)

| Param | Value | Notes |
|---|---|---|
| `mode` | `dry-run` | Live requires typing `CONFIRM` on dashboard |
| `session_tag` | `V5` | From env `SESSION_TAG`; default fallback is V5 |
| `bet_size_normal` / `strong` | $8 / $10 | `low_balance` variants $3 / $5 |
| `max_capital_fraction` | 0.20 | Per-trade cap as fraction of balance |
| `max_daily_loss` | $20 | Tiered: 50% size at $10, 25% at $15, stop at $20 (bypassed in dry-run/paper) |
| `min_edge` / `min_terminal_edge` | 0.03 / 0.03 | Floor on expected value |
| `min_entry_token_price` / `max` | 0.35 / 0.50 | Tightened in V5 |
| `max_spread` | 0.03 | Tightened in V5 (was 0.10) |
| `min_clob_consensus` | 0.30 | Raised in V5 (was 0.15) |
| `min_clob_depth` | $50 | Min size at best ask |
| `reversal_chainlink_threshold` / `velocity` | $50 / $0.08/s | Emergency exit triggers |
| `blocked_hours_utc` | `[0, 3]` | Thin-liquidity windows |
| `use_maker_orders` / `maker_price_offset` | True / 0.005 | GTD + post_only |
| `llm_enabled` | **False** | Phase 0 disables LLM entirely |

---

## Infrastructure

| Piece | Where | Notes |
|---|---|---|
| Bot runtime | Railway project `stunning-perfection` | Procfile: `web: python scripts/python/cli.py run-polyguez --dashboard-port ${PORT:-8080}` |
| Supabase | project `rapmxqnxsobvxqtfnwqh` (PolyGuez Project), region ap-south-1 (Mumbai) | Tables: `signal_log`, `trade_log`, `shadow_trade_log`, `rolling_stats`, `trade_archive`, `rolling_stats_archive`, `session_tag_current` |
| Dashboard | same Railway service, FastAPI on `$PORT` | Auth via `DASHBOARD_SECRET` query param or cookie |
| Agent system | Render (`polyguez.onrender.com`) | Dev/Ops agents; Telegram frontend = OpenClaw bot |
| GitHub | `nissimguez2-maker/PolyGuez` (public) | Push to `main` auto-deploys Railway and auto-refreshes the LIVE STATE block below |
| Wallet | Polygon mainnet; USDC-e at `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` | CTF Exchange `0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e`, Neg Risk `0xC5d563A36AE78145C45a50134d48A1215220f80a` |

---

## Rules (persistent, from Nessim)

- **Do not go live** until there's a clean V5 run with stable win rate (≥100 trades suggested).
- **Do not loosen** `velocity_ok`, `oracle_gap_ok`, `min_terminal_edge`, or the entry-price band without calibrated outcome data justifying it.
- **Do not change** the logistic steepness `k = 0.035` without calibrated data showing a better value.
- **Communication**: short, action-first. Never make Nessim open a terminal. Fix, don't explain. No emojis. No "let me know if…" boilerplate.

---

## Pending / Phase 2

- **Settle V5 shadow trades** — `settle_shadow_trades()` needs to actually run on market close.
- **Confirm V5 config passes trades** — entry band 0.35–0.50 + spread 0.03 + consensus 0.30 may be too tight; watch blocker ratios.
- **Complete-set edge (Phase 2)** — currently logged, not acted on.
- **Go-live gate**: 100 clean V5 trades threshold still stands (re-confirm before flipping to live).
- **LLM re-enable** (post Phase 0) — currently disabled; Groq is preferred provider when re-enabled.

---

## Where to look for more detail

| Question | File |
|---|---|
| Main event loop | `agents/application/run_polyguez.py` |
| Signal brain | `agents/strategies/polyguez_strategy.py` |
| Market discovery / P2B parsing | `agents/strategies/market_discovery.py` |
| BTC price feed (Binance + RTDS + REST fallback) | `agents/strategies/btc_feed.py` |
| Chainlink on-chain oracle | `agents/connectors/chainlink_feed.py` |
| CLOB order execution | `agents/polymarket/polymarket.py` |
| Config model | `agents/utils/objects.py` |
| Supabase logging | `agents/utils/supabase_logger.py` |
| Dashboard backend | `scripts/python/server.py` |
| CLI entrypoint | `scripts/python/cli.py` |
| Supabase schema | `supabase/schema.sql` + migrations in `supabase/migrations/` |

---

<!-- LIVE_STATE_BEGIN -->
## LIVE STATE (auto-refreshed)

_This block is regenerated by `.github/workflows/refresh-context.yml` on every push to `main` and daily at 06:00 UTC. If the "Refreshed at" timestamp below is more than 26 hours old, assume the auto-refresh is broken and flag it to Nessim rather than acting on the numbers._

**Refreshed at:** 2026-04-15T22:20:12+00:00 (UTC) — commit `c17b098` by Claude

### Recent commits (last 7 days)

- `c17b098` 2026-04-15 fix: clean up 5 audit bugs (stats persistence + deprecations)
- `dae2dd6` 2026-04-15 chore(ctx): auto-refresh LIVE STATE [skip ci]
- `eb3029a` 2026-04-16 Add backfill_shadows.py for settling shadow trades
- `6b2dfa9` 2026-04-16 Fix missing newline at end of refresh_context.py
- `dbfe048` 2026-04-15 chore(ctx): auto-refresh LIVE STATE [skip ci]
- `576d34e` 2026-04-16 Merge pull request #3 from nissimguez2-maker/claude/reverent-agnesi
- `06b47b2` 2026-04-16 fix: shadow settlement + trade_log era + dashboard session_tag singleton
- `e1bafcf` 2026-04-15 chore(ctx): auto-refresh LIVE STATE [skip ci]
- `be9331b` 2026-04-16 Add type hints to functions in refresh_context.py
- `dff3c83` 2026-04-15 chore(ctx): auto-refresh LIVE STATE [skip ci]
- `a8ab5bd` 2026-04-15 Refactor refresh_context.py for improved functionality
- `445f17b` 2026-04-15 Create refresh_context.py
- `87739d9` 2026-04-15 Create refresh-context.yml
- `6eb5caa` 2026-04-15 Add files via upload
- `c2e7f80` 2026-04-15 Add guidelines for updating CONTEXT.md
- `24ec270` 2026-04-15 docs: add CONTEXT.md + CLAUDE.md
- `2b3f1ba` 2026-04-15 fix: update _dashboard_tag V4 → V5 — dashboard views now filter V5 trades only
- `cf1dc95` 2026-04-15 chore: trigger redeploy — V5-CLEAN reset token active, balance=$100 pnl=$0
- `de35e3f` 2026-04-15 fix: bypass daily_loss limit entirely in dry-run/paper mode — sandbox should never hard-stop
- `512cf91` 2026-04-15 fix: load_rolling_stats — prefer Supabase when reset_token mismatches (clean era reset)
- `21bcc75` 2026-04-15 feat: add reset_token field to RollingStats — allows Supabase to force-override stale local file
- `a49c852` 2026-04-15 feat: write era field on every signal_log/trade_log insert — V5+ rows permanently tagged as clean era
- `a998ba6` 2026-04-15 feat: write era field on every signal_log/trade_log insert — V5+ rows permanently tagged
- `5b85662` 2026-04-15 chore: bump default session_tag fallback v1.1 → V5 (clean era start)
- `3024914` 2026-04-15 feat: wire daily loss size multiplier into bet_size calculation — tiered reduction active in trade loop
- `5da9b7f` 2026-04-15 fix: replace daily_loss hard stop with tiered position reduction — 50% size at 50% limit, 25% at 75% limit, hard stop at 100%
- `a085964` 2026-04-15 fix: raise max_entry_token_price 0.45→0.50, lower max_spread 0.10→0.03, raise min_clob_consensus 0.15→0.30 — audit confirmed dead conditions + optimal price zone
- `9f0052c` 2026-04-15 refactor: split dashboard JS into config/charts/polling/init + fix 5 bugs
- `e597c22` 2026-04-15 chore: force redeploy — reload clean Supabase state 2026-04-15
- `592b167` 2026-04-15 fix: remove max_capital log spam, heartbeat degrades gracefully on old py-clob-client
- `883cab3` 2026-04-15 feat: add latency column to trade table, complete_set_edge panel with 24h stats
- `acef4f6` 2026-04-15 fix: wire bot WS fields (daily_pnl, cooldown, market timer, CLOB dot), unhide edge/prob KPIs, add live market card
- `314ba36` 2026-04-15 feat: dashboard v5c — live signal updates, CS edge frequency, dark chart colors
- `60e2c2b` 2026-04-15 feat: dashboard v5b — two-column layout, live signal card, CS edge panel, blocker pills
- `e303bba` 2026-04-15 feat: dashboard v5a — shadcn dark design tokens and CSS system
- `d26d0ae` 2026-04-15 observability: log hot-path latency (LLM, order, total) per trade
- `c8d9041` 2026-04-15 data: log complete_set_edge per cycle for Phase 2 feasibility analysis
- `5bb491a` 2026-04-15 fix: switch maker orders to GTD + post_only — auto-expire at market end, guaranteed maker
- `efa5357` 2026-04-15 fix: add CLOB heartbeat loop — prevents silent maker order cancellation
- `7e4109b` 2026-04-15 config: Phase 0 — disable LLM, raise entry floor to 0.35, set daily loss cap $20

### Trade counts (from Supabase)

| session_tag | trades | wins | losses | total PnL (USDC) |
|---|---|---|---|---|
| `V4.1` | 23 | 0 | 23 | -97.41 |
| `v1.0` | 8 | 0 | 8 | -37.50 |
| `V4` | 5 | 0 | 5 | -40.00 |
| `V5` | 5 | 0 | 5 | -27.00 |
| `V3` | 4 | 0 | 4 | -29.00 |
| `V2` | 3 | 1 | 2 | +17.26 |

### Shadow trade counts (from Supabase)

| session_tag | total | settled | wins | losses | settled PnL |
|---|---|---|---|---|---|
| `V4.1` | 79263 | 79263 | 37790 | 41473 | -1381.24 |
| `V4` | 5098 | 5098 | 1616 | 3482 | -4040.04 |
| `V5` | 3743 | 3743 | 1849 | 1894 | +1312.96 |
| `V3` | 2009 | 2009 | 763 | 1246 | +283.51 |
| `V2` | 1917 | 1917 | 398 | 1519 | -2501.48 |
| `v1.1` | 44 | 44 | 44 | 0 | +283.65 |

### Rolling stats singleton

- `id=singleton` updated_at=`2026-04-15T19:59:27.008956+00:00`  reset_token=`V5-CLEAN`  trade_count=`None`  total_pnl=`None`  wins/losses=`None/None`

### Current active session_tag (from `session_tag_current`)

`V5`
<!-- LIVE_STATE_END -->
