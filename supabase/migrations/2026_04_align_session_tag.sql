-- Migration: align dashboard views to use a session_tag_current helper table
-- instead of hardcoded 'V4' strings.
--
-- Usage: INSERT/UPDATE the single row in session_tag_current to change
-- which session the dashboard views display.

-- Helper table: single row holding the active session tag
CREATE TABLE IF NOT EXISTS session_tag_current (
    id   BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),  -- enforce single row
    tag  TEXT NOT NULL DEFAULT 'V4'
);

-- Seed with default value (no-op if row exists)
INSERT INTO session_tag_current (id, tag)
VALUES (TRUE, 'V4')
ON CONFLICT (id) DO NOTHING;

-- Convenience function to update the active session tag
CREATE OR REPLACE FUNCTION set_active_session(new_tag TEXT)
RETURNS VOID LANGUAGE sql AS $$
    UPDATE session_tag_current SET tag = new_tag WHERE id = TRUE;
$$;

-- Recreate dashboard views to join against session_tag_current

CREATE OR REPLACE VIEW dashboard_trade_summary AS
SELECT
    COUNT(*) FILTER (WHERE outcome = 'win')  AS wins,
    COUNT(*) FILTER (WHERE outcome = 'loss') AS losses,
    COALESCE(SUM(pnl), 0)                   AS total_pnl,
    ROUND(AVG(pnl)::numeric, 4)             AS avg_pnl,
    COUNT(*)                                 AS total_trades
FROM trade_log
WHERE session_tag = (SELECT tag FROM session_tag_current LIMIT 1);

CREATE OR REPLACE VIEW dashboard_blockers AS
SELECT
    blocking_conditions AS name,
    COUNT(*)            AS cnt,
    COUNT(*) FILTER (WHERE outcome = 'win')  AS would_win,
    COUNT(*) FILTER (WHERE outcome = 'loss') AS would_lose,
    COALESCE(SUM(pnl), 0)                   AS missed_pnl
FROM shadow_trade_log
WHERE session_tag = (SELECT tag FROM session_tag_current LIMIT 1)
  AND blocking_conditions IS NOT NULL
  AND blocking_conditions != ''
GROUP BY blocking_conditions
ORDER BY cnt DESC;

CREATE OR REPLACE VIEW dashboard_signals_hourly AS
SELECT
    date_trunc('hour', ts) AS hour,
    COUNT(*)               AS signals,
    COUNT(*) FILTER (WHERE all_conditions_met) AS all_met,
    COUNT(*) FILTER (WHERE trade_fired)        AS fired
FROM signal_log
WHERE session_tag = (SELECT tag FROM session_tag_current LIMIT 1)
GROUP BY 1
ORDER BY 1 DESC
LIMIT 48;

-- RLS for the new table
ALTER TABLE session_tag_current ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "anon_select_session_tag" ON session_tag_current FOR SELECT TO anon USING (true);
CREATE POLICY IF NOT EXISTS "service_all_session_tag" ON session_tag_current FOR ALL TO service_role USING (true);
