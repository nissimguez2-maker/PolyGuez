-- Follow-up to 2026_04_17_restrict_anon_to_dry_run.sql.
--
-- The previous pass only dropped the `anon_select_*` policies named in
-- supabase/schema.sql. A separate legacy batch of `anon_read_*` policies
-- (created by an earlier migration not in schema.sql) remained. Postgres RLS
-- is permissive-OR across policies, so the `anon_read_*` policies with
-- `USING (true)` still granted full anon SELECT and defeated the dry-run
-- restriction. This migration drops them.
--
-- shadow_trade_log: intentionally left readable (all rows are dry-run shadow
-- by nature; keeping the existing `anon_read_shadow_trade_log` policy is the
-- correct state).

DROP POLICY IF EXISTS "anon_read_rolling_stats" ON rolling_stats;
DROP POLICY IF EXISTS "anon_read_trade_archive" ON trade_archive;
DROP POLICY IF EXISTS "anon_read_trade_log" ON trade_log;
DROP POLICY IF EXISTS "anon_read_signal_log" ON signal_log;

-- After this migration the surviving anon SELECT policies are:
--   signal_log            anon_select_signal_log_dry_run         USING (mode = 'dry-run')
--   trade_log             anon_select_trade_log_dry_run          USING (mode = 'dry-run')
--   shadow_trade_log      anon_read_shadow_trade_log             USING (true)
--   session_tag_current   session_tag_current_read (public)      USING (true)
--
-- Outstanding hygiene (not in this migration, tracked separately):
--   1. `anon` still holds INSERT/UPDATE/DELETE table GRANTs. RLS denies the
--      writes because no matching anon WRITE policy exists, but the grants
--      themselves are cruft and should be REVOKE'd.
--   2. `session_tag_current_write` is defined on role `public` with an
--      auth.role()='service_role' check — redundant and confusing. Should
--      be rewritten as a `TO service_role` policy with `USING (true)`.
