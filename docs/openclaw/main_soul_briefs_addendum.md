# OpenClaw `main` agent — Briefs & Daily Report addendum

> Canonical spec for the scheduled-brief behaviour of the `main` OpenClaw
> agent on VPS `178.104.196.211`. The actual SOUL lives at
> `/home/thiago/.openclaw/workspace/workspace-main/SOUL.md` (not tracked in
> this repo). Paste the BEHAVIOR block below into that SOUL, under its
> existing BEHAVIOR section, and save. The VPS auto-pull does **not** modify
> SOULs — this is a one-time manual application.

---

## Schedule (Israel time)

- **Full brief**: 08:00, 23:00
- **Short brief**: 12:00, 16:00, 20:00
- **Daily report**: 23:00 (after the 23:00 full brief)

Each brief is a Telegram message to Nessim. The 23:00 run additionally writes
a Markdown file to
`/home/thiago/.openclaw/workspace/PolyGuez/reports/polyguez-YYYY-MM-DD.md`.

---

## Tooling (already in the repo, synced to VPS via cron auto-pull)

- `scripts/python/trader_summary.py --session V5 --limit 1000`
- `scripts/python/signal_analysis.py --session V5`
- `scripts/python/bot_health.py --session V5`
- `scripts/python/brief_generator.py --kind {full|short}` ← one-shot wrapper

All four print to stdout and read `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` from
`/etc/polyguez.env`. The `main` agent already has bash-tool access.

---

## BEHAVIOR block to paste into `workspace-main/SOUL.md`

```markdown
### Scheduled briefs (Telegram)

On every heartbeat (the existing ~30-minute loop):

1. Compute the current time in `Asia/Jerusalem`.
2. Read `/home/thiago/.openclaw/state/brief_slots.json` (create if missing;
   shape: `{"YYYY-MM-DD": {"08:00": "sent", "12:00": "sent", ...}}`). This is
   how you avoid double-sends.
3. For each slot `(08:00, 23:00)` (full) and `(12:00, 16:00, 20:00)` (short):
   - If current local time is within ±10 minutes of the slot AND the slot is
     not yet marked `sent` for today, generate the brief:

     ```bash
     python /home/thiago/.openclaw/workspace/PolyGuez/scripts/python/brief_generator.py --kind full   # or --kind short
     ```

   - Review the text. Fill any `TODO` lines in `SYNTHESIS` and
     `AGENT ACTIVITY` from your own memory of the last few hours (trader,
     operator, developer, architect calls). Leave a `TODO` as `-` if nothing
     notable happened.
   - Send the final text as a Telegram message to Nessim.
   - Mark the slot as `sent` in `brief_slots.json`.
4. At 23:00 IDT, after the full brief is sent, also write a Markdown report
   to `/home/thiago/.openclaw/workspace/PolyGuez/reports/polyguez-YYYY-MM-DD.md`
   (structure below). Do **not** commit or push it — reports are local
   artifacts for Nessim to feed into Claude Code.

### Alert conditions (fire immediately, outside the schedule)

Regardless of slot, send an immediate Telegram alert if any of these is true
at heartbeat time:

- `bot_health.py` returns `status != "running"`.
- `trader_summary.py → calibration.brier_score` is present and > 0.30.
- `supabase_logger` shows consecutive write failures (see
  `agents/utils/supabase_logger.py` — metric is logged, not yet exposed via
  Supabase; ignore until a dedicated metric row exists).
- `min_net_edge` entry gate was flipped to < 0.02 without a PR (compare to
  `PolyGuezConfig` on disk).

Alerts must not suppress the scheduled brief — send both.

### Daily report (23:00)

Write Markdown to `reports/polyguez-YYYY-MM-DD.md` using this template.
Values come from the same three scripts as the brief.

```markdown
# PolyGuez Daily Report — {DATE}

## Summary
- Net PnL (V5): {net_pnl_after_fees} USDC
- Trades today: {trades_today} ({wins_today}W / {losses_today}L)
- Brier (V5): {brier_score:.4f} [{brier_label}]
- Top blocker (24h): {top_blocker.gate} ({top_blocker.blocked_pct}% of rejects)
- Live gate: trades {trades_total}/100, Brier {brier_score:.4f}/0.25,
  entry gate {min_terminal_edge:.3f} (gross — MODEL-05 PENDING)

## Performance
Dump the relevant fields from `trader_summary.py`:
- `closed_trades`, `wins`, `losses`, `win_rate`
- `total_pnl`, `total_fees_paid`, `net_pnl_after_fees`
- `fill_breakdown` (maker/taker/simulated/unknown)

## Microstructure / Blockers (24h)
From `signal_analysis.py`:
- `signals_24h`, `fired_24h`, `fire_rate_24h`
- Full `blockers` table, sorted by `blocked_count` desc

## Reliability
From `bot_health.py`:
- `status`, `last_signal_ts`, `last_trade_ts`
- `minutes_since_last_signal`, `minutes_since_last_trade`
- Any heartbeat-level stalls you observed during the day

## Agent activity (your memory, not Supabase)
- trader:    N summary calls, any notable outputs
- operator:  N health/log calls, any incidents
- developer: files edited, PRs touched
- architect: strategy sessions, decisions

## Recommendations
1–3 bullets. Concrete actions Nessim can feed back into Claude Code.
```

### Rules

- Never modify `mode`, `k`, `min_terminal_edge`, entry-price band, spread,
  or consensus gates from this loop. Briefs are read-only.
- Never commit or push reports or `brief_slots.json`.
- If `brief_generator.py` fails, include the stderr in a plaintext alert to
  Nessim and skip the slot (don't mark it `sent`); it will retry on the next
  heartbeat within the ±10-minute window.
```

---

## Rollout checklist

1. Merge this PR → VPS auto-pull syncs `scripts/python/*.py` + `reports/`.
2. On the VPS as `thiago`, paste the BEHAVIOR block into
   `/home/thiago/.openclaw/workspace/workspace-main/SOUL.md` under the existing
   BEHAVIOR section, then restart the `main` agent.
3. Smoke-test:

   ```bash
   cd /home/thiago/.openclaw/workspace/PolyGuez
   python scripts/python/signal_analysis.py --session V5 | head
   python scripts/python/bot_health.py       --session V5 | head
   python scripts/python/brief_generator.py  --kind full  | head -40
   python scripts/python/brief_generator.py  --kind short
   ```
4. Wait for the next slot and verify a brief lands in Telegram.
