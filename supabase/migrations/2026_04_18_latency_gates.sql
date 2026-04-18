-- LATENCY-TASK-7: columns for latency + market-matching audit.
--
-- Every column is nullable and populated by the runner on new rows.
-- Existing rows keep NULL so this migration is safe to run on a live
-- table. See the PolyGuez LATENCY-TASK-{1..6} commits for the code
-- that writes these fields.

-- --- signal_log ---------------------------------------------------------

ALTER TABLE signal_log
    ADD COLUMN IF NOT EXISTS alignment_ok      BOOLEAN,
    ADD COLUMN IF NOT EXISTS p2b_ok            BOOLEAN,
    ADD COLUMN IF NOT EXISTS p2b_offset_seconds DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS feed_lag_ms       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS clob_msg_age_ms   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS required_edge     DOUBLE PRECISION;

COMMENT ON COLUMN signal_log.alignment_ok IS
    'LATENCY-TASK-1: true when MarketDiscovery accepted the current market as '
    'time-aligned (event_start <= now <= end_date with ±5s/±10s skew).';
COMMENT ON COLUMN signal_log.p2b_ok IS
    'LATENCY-TASK-2: true when the Chainlink sample used as Price-to-Beat '
    'was within max_p2b_chainlink_offset_seconds of eventStartTime and the '
    'cross-check against current Chainlink did not fail.';
COMMENT ON COLUMN signal_log.p2b_offset_seconds IS
    'LATENCY-TASK-2: distance in seconds between the Chainlink sample used '
    'as P2B and the market eventStartTime. NULL when the cycle was skipped '
    'for P2B quality.';
COMMENT ON COLUMN signal_log.feed_lag_ms IS
    'LATENCY-TASK-3: max(binance_msg_age, rtds_msg_age) in ms at the moment '
    'the signal was evaluated.';
COMMENT ON COLUMN signal_log.clob_msg_age_ms IS
    'LATENCY-TASK-4: seconds since the last CLOB WS message at the moment '
    'the signal was evaluated, in ms. NULL means WS has never delivered.';
COMMENT ON COLUMN signal_log.required_edge IS
    'LATENCY-TASK-6: effective fair-value edge threshold this signal was '
    'judged against. Varies with time-to-expiry under edge_scaling_mode=linear.';

-- --- trade_log ----------------------------------------------------------

ALTER TABLE trade_log
    ADD COLUMN IF NOT EXISTS latency_bucket    TEXT,
    ADD COLUMN IF NOT EXISTS hot_path_stale    BOOLEAN,
    ADD COLUMN IF NOT EXISTS feed_lag_ms       DOUBLE PRECISION;

COMMENT ON COLUMN trade_log.latency_bucket IS
    'LATENCY-TASK-5: coarse hot-path bucket: <200, 200-500, 500-1000, >1000 (ms).';
COMMENT ON COLUMN trade_log.hot_path_stale IS
    'LATENCY-TASK-5: true when total_latency_ms exceeded max_total_hot_path_ms '
    'at entry time. The order still went out; this flags it for analysis.';
COMMENT ON COLUMN trade_log.feed_lag_ms IS
    'LATENCY-TASK-7: BTC-feed lag in ms captured at entry time for later '
    'join with PnL. NULL on legacy rows.';

-- --- shadow_trade_log ---------------------------------------------------

ALTER TABLE shadow_trade_log
    ADD COLUMN IF NOT EXISTS cl_close_offset_seconds DOUBLE PRECISION;

COMMENT ON COLUMN shadow_trade_log.cl_close_offset_seconds IS
    'LATENCY-TASK-7: offset in seconds between the Chainlink tick used as '
    'settlement price and the market expiry timestamp. Large values flag '
    'bad-resolution windows that should be excluded from win-rate analysis.';
