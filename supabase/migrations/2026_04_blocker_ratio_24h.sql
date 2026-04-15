-- Migration: add signal_log-based blocker ratio views (24h window)
--
-- Why: existing dashboard_blockers aggregates shadow_trade_log, which only
-- captures rows where core edge existed but ancillary gates blocked — a
-- filtered view. signal_log.blocking_conditions is written for EVERY signal
-- evaluation (including trades that fired with empty blocking), so it's the
-- unbiased source of truth for "which gate is filtering us right now".
--
-- Also fixes schema drift: runtime writes blocking_conditions/in_trade/
-- chainlink_age_seconds/bid_yes/bid_no/complete_set_edge to signal_log, but
-- those columns were never declared in schema.sql. Prod has them (writes
-- don't error), but checked-in schema lied.

-- 1) Schema drift: declare columns that runtime already writes.
ALTER TABLE signal_log ADD COLUMN IF NOT EXISTS blocking_conditions   TEXT;
ALTER TABLE signal_log ADD COLUMN IF NOT EXISTS in_trade              BOOLEAN;
ALTER TABLE signal_log ADD COLUMN IF NOT EXISTS chainlink_age_seconds FLOAT;
ALTER TABLE signal_log ADD COLUMN IF NOT EXISTS bid_yes               FLOAT;
ALTER TABLE signal_log ADD COLUMN IF NOT EXISTS bid_no                FLOAT;
ALTER TABLE signal_log ADD COLUMN IF NOT EXISTS complete_set_edge     FLOAT;
ALTER TABLE signal_log ADD COLUMN IF NOT EXISTS era                   TEXT;

-- 2) 24h blocker ratio view — active session only, sorted by frequency.
--    blocking_conditions is a comma-separated list; unnest() splits it so
--    each gate is counted once per row it blocked, not once per row.
CREATE OR REPLACE VIEW dashboard_signal_blockers_24h AS
WITH recent AS (
    SELECT blocking_conditions
    FROM signal_log
    WHERE session_tag = (SELECT tag FROM session_tag_current LIMIT 1)
      AND ts >= NOW() - INTERVAL '24 hours'
      AND blocking_conditions IS NOT NULL
      AND blocking_conditions <> ''
      AND NOT (blocking_conditions = '' OR blocking_conditions IS NULL)
      -- filter out rows that represent trades-that-fired (empty blocking list)
),
exploded AS (
    SELECT TRIM(unnest(string_to_array(blocking_conditions, ','))) AS gate
    FROM recent
)
SELECT
    gate                                AS name,
    COUNT(*)                            AS cnt,
    ROUND(100.0 * COUNT(*) /
          NULLIF((SELECT COUNT(*) FROM recent), 0), 1)  AS pct_of_blocked_signals
FROM exploded
WHERE gate IS NOT NULL AND gate <> ''
GROUP BY gate
ORDER BY cnt DESC;

-- 3) 24h signal volume summary — for the "X / Y met" header KPI.
CREATE OR REPLACE VIEW dashboard_signal_counts_24h AS
SELECT
    COUNT(*)                                                   AS total_signals,
    COUNT(*) FILTER (WHERE all_conditions_met = TRUE)          AS all_met,
    COUNT(*) FILTER (WHERE trade_fired = TRUE)                 AS trades_fired,
    COUNT(*) FILTER (WHERE blocking_conditions IS NOT NULL
                       AND blocking_conditions <> '')          AS blocked
FROM signal_log
WHERE session_tag = (SELECT tag FROM session_tag_current LIMIT 1)
  AND ts >= NOW() - INTERVAL '24 hours';

-- 4) Supporting index (partial, only on recent rows would be ideal but we
--    avoid predicate-dependent expressions; the existing session_tag+ts
--    index is adequate — this is just a safety net).
CREATE INDEX IF NOT EXISTS idx_signal_log_blocking_conditions
  ON signal_log (session_tag, ts DESC)
  WHERE blocking_conditions IS NOT NULL;
