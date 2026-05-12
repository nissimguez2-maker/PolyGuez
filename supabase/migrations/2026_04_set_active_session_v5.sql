-- Set active session tag to V5.
-- This fixes ALL dashboard views simultaneously:
--   dashboard_trade_summary, dashboard_blockers,
--   dashboard_signals_hourly, dashboard_signal_blockers_24h,
--   dashboard_signal_counts_24h
-- All of these use: WHERE session_tag = (SELECT tag FROM session_tag_current LIMIT 1)
UPDATE session_tag_current SET tag = 'V5' WHERE id = TRUE;
