# CLAUDE.md — instructions for every Claude surface working on PolyGuez

> Claude Code reads this file automatically on session start. The Claude.ai
> Project has this file in its knowledge. Cowork's memory points at this file.
> Keep it short.

## First thing, every conversation (non-negotiable)

1. **Fetch both `CONTEXT.md` (live numbers) and `SYSTEM.md` (stable docs) from
   GitHub** before doing anything else:
   - `https://raw.githubusercontent.com/nissimguez2-maker/PolyGuez/main/CONTEXT.md`
   - `https://raw.githubusercontent.com/nissimguez2-maker/PolyGuez/main/SYSTEM.md`

   Use `web_fetch`, `curl`, or whatever tool is available. Do **not** trust any
   older cached copy. The files on GitHub are the only source of truth.

2. **Check the `LIVE STATE` block's "Refreshed at" timestamp in `CONTEXT.md`.**
   If it is more than 26 hours old, the auto-refresh GitHub Action is broken.
   Stop, tell Nessim, and offer to debug
   `.github/workflows/refresh-context.yml` — do not act on stale numbers.

3. **Read `SYSTEM.md` in full** for stable facts (config, infra, standing rules,
   key files, open work). Do not ask Nessim to re-explain anything that is
   already in `SYSTEM.md` or `CONTEXT.md`.

## Working style (standing preferences)

- Short answers. Lead with the action, not the explanation.
- Don't make Nessim open a terminal. Do the work through tools.
- Fix first, explain second — and only if asked.
- No emojis. No trailing "let me know if…" boilerplate.

## Before merging / deploying / changing config

- Any change to `agents/utils/objects.py::PolyGuezConfig` defaults → update the
  "Current config" table in `SYSTEM.md` **in the same PR**.
- Any session-tag bump → update the "Current session" section in `SYSTEM.md`
  *and* bump the `reset_token` constant in `PolyGuezConfig` so the Supabase
  singleton wins.
- Any infra change (Railway, Supabase, VPS, GitHub) → update the
  "Infrastructure" table in `SYSTEM.md`.
- Any change to the "Open work" checklist in `SYSTEM.md` → update it in the
  same PR.
- New architectural decision ("we decided X because Y") → add to `SYSTEM.md`
  under a new section or the "Open work" list.

## Live-trading rules (do not violate without explicit confirmation)

- Mode stays `dry-run` unless Nessim types `CONFIRM` in the dashboard **and**
  the programmatic gate passes (≥100 V5 trades, Brier < 0.25, `net_edge` gate
  enabled).
- Do not loosen `min_terminal_edge`, the entry-price band, the spread gate, or
  the CLOB consensus gate without calibrated outcome data.
- `k = 0.035` is a known-wrong prior (MLE on shadow data suggests 0.007–0.010).
  Do not go live at `k=0.035`. Refit `k` after ≥100 V5 live-mode trades using
  `scripts/python/analyze_k.py`.
- Do not go live if any pre-live blocker in `SYSTEM.md` → "Open work" is still
  open.

## VS Code workspace (committed — Nessim's operator interface)

The repo ships a committed `.vscode/` workspace so every clone opens ready to
run. Prefer it over raw terminal instructions.

- `.vscode/tasks.json` — operator task palette reachable from
  **Terminal → Run Task…**. Tasks are grouped as `Status`, `Supabase`,
  `Deploy`, `Dev`. Always add a task entry when you add a new ops script
  under `scripts/ops/` or `scripts/python/`.
- `.vscode/launch.json` — debug configurations for the bot, dashboard,
  trader summary, bot health, signal analysis, `analyze_k`, and current-file
  pytest.
- `.vscode/settings.json` — pytest, black-on-save, column ruler at 100, and
  a SQLTools stub for the Supabase pooler (password prompt, not stored).
- `.vscode/extensions.json` — recommended extensions (Python, Pylance, black,
  SQLTools + pg driver, GitLens, GH Actions, GH PRs, YAML, TOML).
- `.env.example` — committed; every env var the system reads. Copy to `.env`
  (gitignored) and fill in secrets.

Rules for every Claude surface:

- Never make Nessim open a raw terminal. Surface actions through a task or
  launch config. If the action isn't there yet, add it to `tasks.json` in the
  same PR.
- Any new ops script under `scripts/ops/` or `scripts/python/` → corresponding
  task entry in `.vscode/tasks.json` in the same PR.
- Any new env var read by code → line in `.env.example` in the same PR.
- Do not add machine-specific absolute paths to `.vscode/*`. Use
  `${workspaceFolder}` throughout.

## What's in the repo (quick map)

See `SYSTEM.md` → "Key files". This file does not duplicate that map; update
`SYSTEM.md` when the repo layout changes.
