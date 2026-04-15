# How to keep `CONTEXT.md` fresh

`CONTEXT.md` is how every new Claude conversation loads the current state of the project
without Nessim having to re-explain. Stale context is worse than no context — if this file
lies, Claude will act on stale facts. **Treat updating it as part of every material change.**

## When to update — always, after any of these
- Session tag bump (e.g. V5 → V6). Update the header date, the "Current session" block, the commit-list
  snapshot, and bump `reset_token` on `RollingStats` so Supabase wins on every restart.
- Config change in `PolyGuezConfig` defaults (any row in the "Current config" table).
- Infra change (new Railway service, Supabase project rotation, new agent deployment, new Telegram bot).
- A new rule from Nessim, or a rule retired.
- A new pending item promoted to done, or a new Phase-2 task added.

## When NOT to update
- A single bug fix that doesn't change behavior anyone relies on.
- Refactors that preserve behavior.
- Normal trading activity (daily trade counts, PnL) — those belong in the dashboard, not here.
  Only update the "Live state" block when there's a milestone (first V5 win, 100 V5 trades, etc.).

## How to update (Claude instructions)
1. Edit `CONTEXT.md` directly — edit sections in place, don't append history.
2. Bump the "Last updated" date at the top.
3. If the change touches session state, also edit `CLAUDE.md` if its "Live-trading rules" or
   "What's in the repo" needs to change.
4. Commit with message: `docs: refresh CONTEXT.md — <one-line summary>`.
5. Push. The Claude.ai Project should re-pull `CONTEXT.md` on the next conversation (see below).

## Getting the fresh file into the Claude.ai Project
The Claude.ai Project doesn't auto-sync from GitHub. You have two options:

**A. Manual refresh (simplest).** When `CONTEXT.md` changes materially, Nessim drags the
updated file from GitHub (or from `/Users/NissimGuez/Documents/Claude/Projects/PolyGuez/CONTEXT.md`)
into the Claude.ai Project's Knowledge section, replacing the old copy. One minute of work
per material change.

**B. Use Cowork to sync.** Ask Cowork Claude: "update the Claude Project's CONTEXT.md from
`/Users/NissimGuez/Documents/Claude/Projects/PolyGuez/CONTEXT.md`" — Cowork has Chrome access
and can upload it.

## How Claude Code picks it up
Claude Code automatically reads `CLAUDE.md` at the repo root, which instructs it to read
`CONTEXT.md` first thing. No manual step needed — clone the repo and start a session.

## How Cowork picks it up
Cowork memory lives in `~/Library/Application Support/Claude/.../memory/`. The
`project_polyguez.md` memory file points at `CONTEXT.md` and tells Cowork to read it before
acting on any PolyGuez task. No manual step needed.
