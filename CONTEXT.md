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

_This block is regenerated by `.github/workflows/refresh-context.yml` on every push to `main`
and daily at 06:00 UTC. If the "refreshed at" timestamp below is more than 26 hours old,
assume the auto-refresh is broken and flag it to Nessim rather than acting on the numbers._

**Refreshed at:** _not yet populated — will fill on first Action run_

### Recent commits (last 7 days)
_pending first run_

### Trade counts (from Supabase)
_pending first run_

### Shadow trade counts (from Supabase)
_pending first run_

### Rolling stats singleton
_pending first run_

### Current active session_tag (from `session_tag_current` table)
_pending first run_
<!-- LIVE_STATE_END -->
