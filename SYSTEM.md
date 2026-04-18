# PolyGuez — System Reference

> Stable facts about PolyGuez. Hand-edited. Updated only on PRs that change config,
> infra, architecture, or standing rules. Auto-refreshed live numbers live in
> [`CONTEXT.md`](CONTEXT.md). Claude behavioural rules live in
> [`CLAUDE.md`](CLAUDE.md).

---

## Owner

Nessim — non-developer, finance background, based in Israel. Communication style:
short, direct, fix-don't-explain, lead with action. Does not use their phone for
PolyGuez work. Goal: passive income from algo trading, target $60–70/day when live.

---

## What PolyGuez does

Trades Polymarket's 5-minute BTC binary markets ("Will BTC close Up or Down vs
opening price within this window?").

Strategy: compare the real-time Chainlink oracle BTC price to the market's
price-to-beat (P2B) strike, compute a terminal-probability edge via a logistic
model `P = 1 / (1 + e^(-k·Δ))` with time-adjusted steepness, and fire a trade
when edge, price, spread, depth, and CLOB consensus gates all pass.

Execution: maker GTD limit orders via py-clob-client. In live mode, FOK
market-order fallback is gated on `net_edge >= live_fok_net_edge_min` (0.10
default). Dry-run exercises all paths.

All signals and trades log to Supabase for post-hoc calibration.

---

## Current session: **V5 (clean era)** — started 2026-04-15

V5 is the canonical research session. All rows carry `era = 'V5'`. Pre-V5 data
was deleted from Supabase on 2026-04-16 (see
`supabase/migrations/2026_04_18_cleanse_pre_v5.sql`). The
`rolling_stats.reset_token = 'V5-CLEAN'` forces clean boot on every restart.

**V5 goals:**
- Accumulate ≥100 clean dry-run trades to support calibration.
  *Blocked by CRIT-01: counter frozen at 43 since 2026-04-16 16:26:37Z.*
- Refit logistic `k_logistic` on live V5 data. Current value `0.035` is a prior;
  MLE on 88K shadows suggests true `k ≈ 0.007–0.010`. **Do not go live until
  refitted.** Config field landed (MODEL-06(a)); refit (MODEL-06(b)) pending
  data.
- Programmatic live-mode gate — *landed (MODEL-01, commit `93aaef7`).* Gate
  still requires operator to pass `min_net_edge > 0.02` before flipping.
- Flip to live only after that gate passes.

---

## Current config (defaults in `agents/utils/objects.py::PolyGuezConfig`)

| Param | Value | Notes |
|---|---|---|
| `mode` | `dry-run` | Live requires `CONFIRM` in dashboard + (pending) programmatic gate |
| `session_tag` | `V5` | From env `SESSION_TAG` |
| `k_logistic` (logistic steepness) | `0.035` | ⚠️ Overcalibrated — MLE suggests 0.007–0.010. MODEL-06(a) landed: now a `PolyGuezConfig` field, consumed at `polyguez_strategy.py:74`. Refit on V5 live data before flipping to live. |
| `bet_size_normal` / `strong` | $8 / $10 | `low_balance` variants $3 / $5 |
| `max_capital_fraction` | 0.20 | Per-trade cap as fraction of balance |
| `max_daily_loss` | $20 | Tiered: 50% size at $10, 25% at $15, stop at $20 (bypassed in dry-run) |
| `min_edge` / `min_terminal_edge` | 0.03 / 0.03 | Gross-edge floor — switch to `net_edge` gate before live (MODEL-05) |
| `min_entry_token_price` / `max` | 0.35 / 0.50 | Entry price band |
| `max_spread` | 0.03 | |
| `min_clob_consensus` | 0.30 | |
| `min_clob_depth` | $50 | Min liquidity at best ask |
| `taker_fee_coefficient` | 0.072 | Used for `net_edge` logging; not yet a gate |
| `live_fok_net_edge_min` | 0.10 | FOK taker-fallback gate in live mode only |
| `use_maker_orders` / `maker_price_offset` | True / 0.005 | GTD + post_only default |
| `chainlink_onchain_rpc_url` | `polygon.drpc.org` or `$CHAINLINK_RPC_URL` | Free RPC fine for dry-run; set dedicated Alchemy/QuickNode URL before live |
| `p2b_consecutive_failure_halt` | 10 | At 2.5s cadence ≈ 25s of bad shadow entries before halt |
| `blocked_hours_utc` | `[0, 3]` | Thin-liquidity windows |
| `llm_enabled` | `False` | Phase 0 — LLM disabled |
| `max_p2b_chainlink_offset_seconds` | `10.0` | LATENCY-2. Max buffer→eventStart offset for P2B; over = cycle skipped. |
| `max_binance_age_seconds` | `2.0` | LATENCY-3. Hard gate on Binance WS staleness. |
| `max_rtds_age_seconds` | `1.0` | LATENCY-3. Applied only once RTDS has ever delivered. |
| `max_chainlink_age_seconds` | `10.0` | LATENCY-3. General Chainlink staleness gate. |
| `clob_ws_stale_threshold` | `3.0` | LATENCY-4. CLOB WS message-age cutoff. |
| `heartbeat_stale_threshold` | `8.0` | LATENCY-4. Blocks entry before Polymarket's ~10s heartbeat cancel. |
| `max_llm_ms` | `None` | LATENCY-5. Opt-in hard cutoff (ms); over = no-go, bypasses `llm_timeout_fallback`. |
| `max_total_hot_path_ms` | `8000.0` | LATENCY-5. Trades above this flip `hot_path_stale` on the log row (observability). |
| `edge_scaling_mode` | `"step"` | LATENCY-6. Legacy early/mid/late tiers. Flip to `"linear"` to interpolate. |
| `edge_scaling_base` / `edge_scaling_close` | `0.03 / 0.075` | LATENCY-6. Linear-mode thresholds at window start / close. |

---

## Infrastructure

| Piece | Where | Notes |
|---|---|---|
| Bot runtime | Railway — project `stunning-perfection` | `Procfile: web: python scripts/python/cli.py run-polyguez --dashboard-port ${PORT:-8080}`. Auto-deploys on push to `main`. |
| Bot URL | `https://polyguez-production.up.railway.app` | `/health` is unauthenticated; dashboard gated by `DASHBOARD_SECRET`. |
| Supabase | project `rapmxqnxsobvxqtfnwqh`, region ap-south-1 (Mumbai) | Tables: `signal_log`, `trade_log`, `shadow_trade_log`, `rolling_stats`, `session_tag_current`. Archive tables emptied 2026-04-16. |
| Dashboard | Same Railway service, FastAPI on `$PORT` | Auth via `DASHBOARD_SECRET` query param. Anon Supabase reads restricted to `mode='dry-run'`. Balance served via authenticated `/api/stats`. |
| Operator runtime | Hetzner VPS `178.104.196.211` (Ubuntu 24.04) | OpenClaw agents running as user `thiago`. Telegram bot polls from VPS. UFW allows port 22 only. |
| GitHub | `nissimguez2-maker/PolyGuez` (public) | Push to `main` → Railway redeploy + CONTEXT.md auto-refresh. |
| VPS auto-pull | Cron `*/15 * * * *` as `thiago` | Pulls via dedicated deploy key (`~thiago/.ssh/github_polyguez`). |
| Agent-memory backup | Daily cron 02:00 UTC on VPS | `/root/backups/openclaw-agents-YYYYMMDD.tgz`, 7-day retention. Off-site backup not yet configured. |
| Wallet | Polygon mainnet, USDC-e `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` | CTF Exchange `0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e`, Neg Risk `0xC5d563A36AE78145C45a50134d48A1215220f80a` |

---

## Standing rules (do not violate without explicit confirmation from Nessim)

- **Mode stays `dry-run`** until the programmatic gate passes: ≥100 V5 trades +
  Brier < 0.25 + `net_edge` gate enabled + `CONFIRM` typed.
- **Do not change `k`** without refitting on live V5 data. Current value is
  known-wrong (MLE says 4–5× too steep).
- **Do not loosen** the entry-price band, spread gate, consensus gate, or
  `min_terminal_edge` without calibrated outcome data.
- **Do not go live** if any P0 item in the "Open work" list below is unmerged.
- **Net edge, not gross:** the entry gate must use `net_edge` before any real
  capital is at risk.
- **Communication:** short, action-first. Never make Nessim open a terminal.
  Fix, don't explain. No emojis. No "let me know if…" boilerplate.

---

## Key files

| What | File |
|---|---|
| Main event loop | `agents/application/run_polyguez.py` |
| Signal logic + `execute_entry` | `agents/strategies/polyguez_strategy.py` |
| Market discovery / P2B parsing | `agents/strategies/market_discovery.py` |
| BTC feed (Binance WS + RTDS + REST) | `agents/strategies/btc_feed.py` |
| Chainlink oracle | `agents/connectors/chainlink_feed.py` |
| CLOB execution | `agents/polymarket/polymarket.py` |
| Config + state dataclasses | `agents/utils/objects.py` |
| Supabase logger | `agents/utils/supabase_logger.py` |
| Dashboard backend (FastAPI) | `scripts/python/server.py` |
| Dashboard frontend | `scripts/frontend/` |
| CLI entrypoint | `scripts/python/cli.py` |
| Schema | `supabase/schema.sql` + `supabase/migrations/` |
| Live state (auto-refreshed) | [`CONTEXT.md`](CONTEXT.md) |
| VPS hardening runbook | [`docs/VPS_HARDENING.md`](docs/VPS_HARDENING.md) |

---

## Open work (as of 2026-04-18, not done — track here until closed)

**Pre-live blockers (must land before `mode=live`):**

- [ ] **CRIT-01** *(new 2026-04-18)* — Supabase writes silently no-op'd from **2026-04-16 16:26:37Z onwards** (48h dark) while `/health` stayed green. `_client()==None` short-circuit in `agents/utils/supabase_logger.py` bypassed `_on_write_failure`, blinding the audit-1.5 Telegram alerter. Patched on the log_signal / log_trade / log_shadow_trade paths in this PR. Still to do: (1) verify Railway `SUPABASE_SERVICE_KEY` + `SUPABASE_URL` env are correct (likely rotated/renamed); (2) confirm `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALERT_CHAT_ID` are set so alerts actually deliver; (3) extend same `_on_write_failure` hook to `save_rolling_stats` in `polyguez_strategy.py` — it logs-and-swallows. V5 dry-run trade count is **frozen at 43** (none since Apr 16); calibration clock is stalled until writes resume.
- [ ] **SEC-02** — `/api/trades?mode=live` authenticated proxy (dashboard shows zero live trades without it)
- [x] **COR-01** — Fix trade-log race — *landed `0173893` (log → flush → save_rolling_stats → clear position)*
- [x] **COR-02** — Fix pending-eviction capital leak — *landed `0173893`*
- [x] **COR-03** — Fix recovery double-settle window — *landed `0173893` (`_settled_market_ids` in-process guard + unconditional `save_rolling_stats`)*
- [x] **MODEL-01** — Programmatic live-mode gate — *landed `93aaef7`*
- [x] **MODEL-02** — Wire `fee_paid` / `taker_maker` to `trade_log` — *landed `93aaef7` (populated on maker fills, FOK fallback, and dry-run paths)*
- [x] **MODEL-03** — Brier-score SQL view + RPC — *landed `93aaef7`*
- [ ] **MODEL-05** — Flip entry gate to `net_edge` (hold until clean V5 data is actually flowing — CRIT-01 blocks this)
- [x] **MODEL-06(a)** — `k` moved from `polyguez_strategy.py` hardcode to `PolyGuezConfig.k_logistic` — *landed this PR*
- [ ] **MODEL-06(b)** — Refit `k` on V5 live data (post-100 V5 live trades — blocked on CRIT-01 data flow + live flip)
- [ ] **INFRA** — Set `CHAINLINK_RPC_URL` to a dedicated Polygon RPC in Railway env

**Hardening (strongly recommended, not strict blockers):**

- [x] **COR-04..09** — Background-task done-callbacks, thread-safe counter, atomic balance+PnL, CLOB-WS stale-price guard, `reset_token` mismatch alert, position-state lock — *landed `74fbf05`*
- [ ] **SEC-03** — Migrate Telegram bot token in `openclaw.json` to env-var SecretRef
- [ ] **INFRA** — Install Uptime Kuma on VPS; Telegram alert on Railway outage *(CRIT-01 underscores the need for external liveness — `/health` lied for 48h)*
- [ ] **OC-01/02** — Verify CONTEXT.md fetch + input-validation rule in all 5 agent SOULs
- [ ] **OC-04** — Off-site backup of agent memories (currently on-VPS only)
- [x] **OBS-01** — `save_rolling_stats` now routes its exception handler through `_on_write_failure("rolling_stats:save")`, closing the last swallow-and-log Supabase path. Landed alongside VS-01..06.
- [x] **VS-01..06** *(new 2026-04-18)* — committed `.vscode/` operator workspace: `tasks.json` (Status / Supabase / Deploy / Dev groups), `launch.json` (bot, dashboard, trader_summary, bot_health, signal_analysis, analyze_k, pytest-current-file), `settings.json` (pytest + black-on-save + SQLTools stub), `extensions.json`. `.vscode/` removed from `.gitignore`. `.env.example` extended with every env var the runtime reads. `CLAUDE.md` gains a VS Code section so future sessions keep tasks.json and .env.example in sync with new scripts/env vars.

**Schema hygiene (low priority, post-live):**

- [ ] **ARCH-01** — Regenerate canonical `supabase/schema.sql` from prod dump
- [ ] **ARCH-03** — Add `era` column to `shadow_trade_log`
