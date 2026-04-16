# `scripts/ops/` — operational scripts for OpenClaw agents

Every script here wraps one dangerous or load-bearing action so that
OpenClaw agents (and humans, if convenient) invoke it the same way
every time, with an audit trail, and with confirmation-string guards
on anything irreversible.

**Agents must never run raw `git push`, raw `psql`, or arbitrary SQL
that modifies state.** Use the scripts below.

## Audit log

Every invocation writes one JSON line to `scripts/ops/ops_log.jsonl`:

```json
{"ts":"…","action":"github_push","status":"ok","details":{…}}
```

Tail the log with `tail -f scripts/ops/ops_log.jsonl` to watch live
activity.

## Scripts

| Script | Action | Confirm string |
|---|---|---|
| `github_push.py` | Commit (if `--allow-dirty`) + push branch. `main` needs `--confirm CONFIRM_PUSH_MAIN` | `CONFIRM_PUSH_MAIN` (main only) |
| `deploy_prod.py` | Trigger a Railway deploy via the GraphQL API | `CONFIRM_DEPLOY` |
| `sb_read.py` | Safe read-only select from a table/view with optional filter/order | none (read-only) |
| `sb_migrate.py` | Apply SQL files in `supabase/migrations/` in order | `CONFIRM_SCHEMA` |
| `sb_maintenance.py` | Run a named, pre-defined one-off task | `CONFIRM_DANGER` |

## Usage examples

```bash
# Push a feature branch
python scripts/ops/github_push.py --branch openclaw/fix-xyz --message "fix: xyz"

# Commit pending changes and push them in one shot
python scripts/ops/github_push.py --branch openclaw/fix-xyz \
    --message "fix: xyz" --allow-dirty

# Force-redeploy current main to Railway
python scripts/ops/deploy_prod.py --confirm CONFIRM_DEPLOY

# Read last 20 V5 trades
python scripts/ops/sb_read.py --table trade_log \
    --filter session_tag=V5 --order ts:desc --limit 20

# Apply any pending schema migrations
python scripts/ops/sb_migrate.py --dry-run          # inspect first
python scripts/ops/sb_migrate.py --confirm CONFIRM_SCHEMA

# Smoke-test the maintenance runner
python scripts/ops/sb_maintenance.py --list
python scripts/ops/sb_maintenance.py --task noop --confirm CONFIRM_DANGER
```

## Required environment

All scripts read env vars from the shell environment. On the VPS we
source `/etc/polyguez.env` (0640 root:thiago) which should contain:

```
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_KEY=<JWT>
RAILWAY_TOKEN=<…>
RAILWAY_PROJECT_ID=<…>
RAILWAY_SERVICE_ID=<…>
SUPABASE_DB_DSN=postgresql://…   # only needed by sb_migrate.py
```

## Adding new maintenance tasks

Open `sb_maintenance.py`, add a new function `task_<name>(client) -> dict`
with fixed SQL, and register it in the `TASKS` dict. The task name must
be passed explicitly via `--task` — agents cannot invent tasks at
runtime, because a missing name fails fast with `unknown_task`.

## Golden rule

If an ops action isn't gated, logged, and confirmed, it doesn't belong
in `scripts/ops/`. Plain utilities go elsewhere (e.g.
`scripts/python/trader_summary.py` is read-only + non-destructive and
lives outside `ops/`).
