-- Data cleanse: delete all pre-V5 pollution.
--
-- Background: the bot has been writing to Supabase since V1 of the strategy.
-- V5 is the first clean era (session_tag='V5', era='V5'). Rows from older
-- sessions (v1.0, v1.1, V2, V3, V4, V4.1) have missing columns, wrong
-- calibration, and no usable signal_id linkage back to outcomes. Keeping
-- them in the hot tables inflates aggregate queries and distorts the
-- dashboard's session tables. This migration deletes them.
--
-- Applied to prod: 2026-04-16. Row counts removed (verified pre-delete):
--   signal_log: 202,995 rows (v1.0 110,149; v1.1 5,372; V2 23,387;
--               V3 20,497; V4 17,925; V4.1 25,665)
--   trade_log: 43 rows (v1.0 8; V2 3; V3 4; V4 5; V4.1 23)
--   shadow_trade_log: 88,331 rows (v1.1 44; V2 1,917; V3 2,009;
--                     V4 5,098; V4.1 79,263)
--   rolling_stats_archive: 1 row (pre-V5 snapshot)
--   trade_archive: 1 row (114 KB JSONB blob)
--
-- KEPT: everything with session_tag='V5', rolling_stats singleton
-- (reset_token='V5-CLEAN'), session_tag_current ('V5').
--
-- Post-cleanse state (verified):
--   signal_log: V5 only, 2,363 rows
--   trade_log: V5 only, 25 rows
--   shadow_trade_log: V5 only, 5,790 rows
--
-- Idempotent: re-running this migration on a V5-only DB is a no-op.

DELETE FROM signal_log
    WHERE session_tag IN ('v1.0','v1.1','V2','V3','V4','V4.1');

DELETE FROM trade_log
    WHERE session_tag IN ('v1.0','V2','V3','V4','V4.1');

DELETE FROM shadow_trade_log
    WHERE session_tag IN ('v1.1','V2','V3','V4','V4.1');

DELETE FROM rolling_stats_archive;
DELETE FROM trade_archive;

-- Autovacuum will reclaim dead tuples; manual VACUUM ANALYZE recommended
-- if running this against a live DB from psql:
--   VACUUM ANALYZE signal_log;
--   VACUUM ANALYZE trade_log;
--   VACUUM ANALYZE shadow_trade_log;
