-- Hygiene follow-up to 2026_04_17_restrict_anon_to_dry_run + 2026_04_17b.
--
-- Two issues surfaced while auditing the anon policy surface:
--
-- 1. `anon` holds table-level GRANTs for INSERT/UPDATE/DELETE/TRUNCATE on
--    every trading table. RLS denies the writes because no matching anon
--    WRITE policy exists, but the grants themselves are cruft — anyone
--    inspecting the schema sees a write-capable role where they shouldn't,
--    and if someone later adds a permissive anon WRITE policy (intentional
--    or accidental) the grants become immediately exploitable. REVOKE them.
--
-- 2. `session_tag_current_write` policy targets role `public` with a WHERE
--    clause `auth.role() = 'service_role'`. That's a confused construction
--    — the policy should target service_role directly with USING (true).
--    Rewrite it so the intent is legible from pg_policies alone.

-- ---------------------------------------------------------------------------
-- 1. Revoke anon write grants on trading tables.
--    SELECT is retained where RLS restricts it (the restricted anon policies
--    still govern what anon can read, row-by-row).
-- ---------------------------------------------------------------------------
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON signal_log, trade_log, shadow_trade_log, rolling_stats,
       trade_archive, session_tag_current
    FROM anon;

-- ---------------------------------------------------------------------------
-- 2. Rewrite session_tag_current_write to target service_role directly.
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS "session_tag_current_write" ON session_tag_current;
CREATE POLICY "session_tag_current_service_all"
    ON session_tag_current FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
