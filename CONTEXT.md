# PolyGuez — Project Context

> **Purpose of this file.** Single source of truth about where the project stands.
> Every Claude surface — Claude Code (repo), Cowork (desktop), Claude Project (web) —
> should read this before doing anything so the human doesn't have to re-explain.
>
> **Keep it fresh.** Update this file on every material change (new config, new session,
> infra change, architecture decision). See `docs/UPDATE-CONTEXT.md`.

---

## Last updated
**2026-04-15** — V5 "clean era" live. Dashboard rebuilt with shadcn dark. Phase 0 config active.

## Owner
Nessim — non-developer, finance background, based in Israel. Communication style: short, direct, fix-don't-explain, lead with action. Goal: $60–70/day passive income from the bot.

---

## What PolyGuez does (one paragraph)
Trades Polymarket's 5-minute BTC binary markets ("Will BTC close Up or Down vs opening price?").
Strategy: compare the real-time Chainlink oracle BTC price to the market's **price-to-beat** (P2B)
strike, compute a terminal-probability edge via a logistic model `P = 1/(1+e^(-k·Δ))` with
`k = 0.035 / sqrt(seconds_remaining/60)`, and fire a trade when edge + price + liquidity + consensus
conditions all pass. Execution: maker GTD limit orders via py-clob-client, FOK fallback. All signals
and trades log to Supabase for post-hoc calibration.

---

## Current session: **V5 (clean era)** — started 2026-04-15 ~16:00 UTC

V5 was designed with Perplexity and committed in a burst on 2026-04-15. It is a full reset:
`rolling_stats.reset_token = "V5-CLEAN"` forces every running bot to discard its local cache on boot
and load the clean singleton from Supabase. All `signal_log` / `trade_log` rows written from V5 onward
carry `era = "V5"` permanently so pre-V5 data can never contaminate dashboards again.

### What changed in V5 (key commits from 2026-04-15)
- **Phase 0 config**: LLM disabled, entry floor 0.35, daily-loss cap $20 (`7e4109b`)
- **Entry band tightened**: `max_entry_token_price` 0.45→**0.50**, `max_spread` 0.10→**0.03**, `min_clob_consensus` 0.15→**0.30** (`a085964`)
- **Daily-loss logic**: hard stop replaced with tiered reduction — 50% size at 50% limit, 25% at 75%, hard stop at 100% (`5da9b7f`, `3024914`)
- **Dry-run/paper bypass**: daily-loss tripwire now fully bypassed in sandbox modes (`de35e3f`)
- **Era tagging**: every new row gets `era = session_tag` so V5+ is provably clean (`a49c852`)
- **Reset mechanism**: `reset_token` on `rolling_stats` lets Supabase force-override stale local files (`21bcc75`, `512cf91`)
- **Dashboard**: full rewrite with shadcn dark design tokens, two-column layout, live signal card, blocker pills, CS-edge panel, latency column (`e303bba` → `883cab3`)
- **Maker orders**: switched to GTD + `post_only=True`, auto-expire at market end, CLOB heartbeat keeps them alive (`5bb491a`, `efa5357`)
- **Observability**: latency logged per trade (LLM/order/total ms), `complete_set_edge` logged per cycle for Phase 2 (`d26d0ae`, `c8d9041`)
- **Dashboard tag**: `_dashboard_tag` hardcoded V4 → V5 (`2b3f1ba`)
- **Security**: `DASHBOARD_SECRET` wired to control-panel endpoints (`d9060b1`)

---

## Current config (active defaults in `agents/utils/objects.py::PolyGuezConfig`)
| Param | Value | Notes |
|---|---|---|
| `mode` | `dry-run` | Live requires typing CONFIRM on dashboard |
| `session_tag` | `V5` | From env `SESSION_TAG`; default fallback is now V5 |
| `bet_size_normal` / `strong` | $8 / $10 | `low_balance` variants $3 / $5 |
| `max_capital_fraction` | 0.20 | Per-trade cap as fraction of balance |
| `max_daily_loss` | $20 | Tiered: 50% size at $10, 25% at $15, stop at $20 (bypassed in dry-run) |
| `min_edge` / `min_terminal_edge` | 0.03 / 0.03 | Floor on expected value |
| `min_entry_token_price` / `max` | 0.35 / **0.50** | Tightened in V5 |
| `max_spread` | **0.03** | Tightened in V5 (was 0.10) |
| `min_clob_consensus` | **0.30** | Raised in V5 (was 0.15) |
| `min_clob_depth` | $50 | Min size at best ask |
| `reversal_chainlink_threshold` / `velocity` | $50 / $0.08/s | Emergency exit triggers |
| `blocked_hours_utc` | `[0, 3]` | Thin-liquidity windows |
| `use_maker_orders` / `maker_price_offset` | True / 0.005 | GTD + post_only |
| `llm_enabled` | **False** | Phase 0 disables LLM entirely |

---

## Live state (as of 2026-04-15 20:14 UTC)
- **Bot**: running on Railway (`stunning-perfection`), auto-deploy from GitHub `main`
- **Trades ever**: 43 across all sessions (V4.1 last to fire at 15:22 UTC today — before V5 flip)
- **V5 trades so far**: 0 (bot just came up on V5, waiting for a signal to pass tightened gates)
- **V5 shadow trades**: 2,562 logged, 0 settled yet
- **Top blockers (last 24h)**: `daily_loss + entry_price` (1,421), `daily_loss` alone (1,011), `entry_price` alone (477)
- **Rolling stats**: reset_token=`V5-CLEAN`, trades/pnl/wins/losses all null (clean slate)
- **Historical**: V4.1 = 23 trades, **−$97.41**. V4 = 5 trades, −$40. V3 = 4, −$29. V2 = 3, +$17.26. v1.0 = 8, −$37.50. All eras net negative except V2.

---

## Infrastructure
| Piece | Where | Notes |
|---|---|---|
| Bot runtime | Railway project `stunning-perfection` | Procfile: `web: python scripts/python/cli.py run-polyguez --dashboard-port ${PORT:-8080}` |
| Supabase | project `rapmxqnxsobvxqtfnwqh` (PolyGuez Project), region ap-south-1 (Mumbai) | Tables: `signal_log`, `trade_log`, `shadow_trade_log`, `rolling_stats`, `trade_archive`, `rolling_stats_archive`, `session_tag_current` |
| Dashboard | same Railway service, FastAPI on `$PORT` | Auth via `DASHBOARD_SECRET` query param or cookie |
| Agent system | Render (`polyguez.onrender.com`) | Dev/Ops agents; Telegram frontend = OpenClaw bot |
| GitHub | `nissimguez2-maker/PolyGuez` | Push to `main` auto-deploys Railway |
| Wallet | Polygon mainnet; USDC-e at `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` | CTF Exchange `0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e`, Neg Risk `0xC5d563A36AE78145C45a50134d48A1215220f80a` |

---

## Pending / Phase 2 backlog
- **Settle V5 shadow trades** — 2,562 pending, `settle_shadow_trades()` has to actually run on market close
- **Confirm V5 config passes trades** — entry band 0.35–0.50 + spread 0.03 + consensus 0.30 may be too tight; watch blocker ratios over next 24h
- **Complete-set edge (Phase 2)** — currently logged, not yet acted on
- **Go-live gate**: user's rule is "no live until 100 clean V5 trades" (verify — rule was set for V2/V3 era; may need re-stating)
- **LLM re-enable** (post Phase 0): currently disabled; Groq is preferred provider when re-enabled

---

## Rules (from Nessim, persistent)
- **Do not go live** until there's a clean run with stable win rate.
- **Do not loosen** `velocity_ok` / `oracle_gap_ok` / `min_terminal_edge` without outcome data to justify it.
- **Do not change** `k = 0.035` (logistic steepness) without calibrated data showing a better value.
- **Communication**: short, action-first. Never make Nessim open a terminal. Fix, don't explain.

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
