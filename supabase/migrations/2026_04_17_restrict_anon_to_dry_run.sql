-- Phase 0.1 of the audit remediation plan.
--
-- Problem: the original RLS posture grants `anon` SELECT on every trading
-- table unconditionally. The project ID is in public CLAUDE.md and the anon
-- JWT is embedded in the dashboard JS, so a REST call like
--   https://rapmxqnxsobvxqtfnwqh.supabase.co/rest/v1/trade_log?select=*
-- reads the entire trading history without authenticating.
--
-- Fix (staged): restrict to dry-run data only on tables that have a `mode`
-- column, and drop anon entirely on tables that expose strategy state or
-- historical real-trade data.
--
-- Dashboard impact:
--   signal_log / trade_log            — pre-live all rows are dry-run, so no
--                                       visible impact on the live dashboard.
--                                       Post-live, live rows become hidden
--                                       from anon; they should be read
--                                       through the authenticated FastAPI
--                                       proxy (DASHBOARD_SECRET) instead.
--   shadow_trade_log                  — every row is dry-run by definition
--                                       (shadow = not executed). Anon kept.
--   rolling_stats                     — singleton JSONB exposing strategy
--                                       state (reset_token, win_rate, etc.).
--                                       Anon dropped. Dashboard reads the
--                                       balance via the runner's /api/stats
--                                       endpoint now.
--   trade_archive                     — historical real-trade blob. Anon
--                                       dropped. Dashboard does not read
--                                       this today.
--   session_tag_current               — public session name only, not
--                                       sensitive. Anon kept.
--   dashboard_* views                 — inherit RLS from base tables, so
--                                       anon readers will see aggregates
--                                       computed over dry-run rows only.

-- ---------------------------------------------------------------------------
-- signal_log: restrict anon to dry-run rows
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS "anon_select_signal_log" ON signal_log;
CREATE POLICY "anon_select_signal_log_dry_run"
    ON signal_log FOR SELECT TO anon
    USING (mode = 'dry-run');

-- ---------------------------------------------------------------------------
-- trade_log: restrict anon to dry-run rows
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS "anon_select_trade_log" ON trade_log;
CREATE POLICY "anon_select_trade_log_dry_run"
    ON trade_log FOR SELECT TO anon
    USING (mode = 'dry-run');

-- ---------------------------------------------------------------------------
-- rolling_stats: drop anon entirely (exposes strategy state)
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS "anon_select_rolling_stats" ON rolling_stats;

-- ---------------------------------------------------------------------------
-- trade_archive: drop anon entirely (historical real trades)
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS "anon_select_trade_archive" ON trade_archive;

-- ---------------------------------------------------------------------------
-- shadow_trade_log and session_tag_current: anon retained.
-- shadow_trade_log is dry-run by definition; session_tag_current is just the
-- current session name.
-- ---------------------------------------------------------------------------

-- Sanity check: list all surviving anon policies after this migration.
-- (Comment out if the Supabase migration runner doesn't allow notices.)
-- SELECT tablename, policyname, qual FROM pg_policies
--  WHERE schemaname='public' AND roles @> '{anon}'::name[]
--  ORDER BY tablename, policyname;
