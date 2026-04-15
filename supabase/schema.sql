-- PolyGuez Supabase Schema
-- Tables, views, and RLS policies for the trading bot
-- Last updated: 2026-04-15
--
-- IMPORTANT: Dashboard views filter on session_tag = 'V4'.
-- The bot config default is SESSION_TAG='v1.1' (set via env var).
-- To see data on dashboards, deploy with SESSION_TAG=V4 or update
-- the views below to match your chosen session tag.

-- ==========================================================================
-- TABLES
-- ==========================================================================

CREATE TABLE IF NOT EXISTS signal_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ DEFAULT now(),
    market_id   TEXT,
    market_question TEXT,
    elapsed_seconds FLOAT,
    btc_price   FLOAT,
    chainlink_price FLOAT,
    strike_delta FLOAT,
    terminal_probability FLOAT,
    terminal_edge FLOAT,
    entry_side  TEXT,
    yes_price   FLOAT,
    no_price    FLOAT,
    spread      FLOAT,
    conditions_met INT,
    all_conditions_met BOOLEAN,
    trade_fired BOOLEAN,
    mode        TEXT,
    session_tag TEXT DEFAULT 'v1.1',
    sigma_realized FLOAT,
    implied_vol FLOAT,
    clob_spread FLOAT,
    depth_at_ask FLOAT,
    signal_id   TEXT
);

CREATE TABLE IF NOT EXISTS trade_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ DEFAULT now(),
    market_id   TEXT,
    market_question TEXT,
    side        TEXT,
    entry_price FLOAT,
    exit_price  FLOAT,
    size_usdc   FLOAT,
    pnl         FLOAT,
    llm_verdict TEXT,
    outcome     TEXT,
    mode        TEXT,
    session_tag TEXT DEFAULT 'v1.1',
    signal_id   TEXT
);

CREATE TABLE IF NOT EXISTS shadow_trade_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ DEFAULT now(),
    market_id   TEXT,
    market_question TEXT,
    direction   TEXT,
    entry_price FLOAT,
    size_usdc   FLOAT,
    exit_price  FLOAT,
    edge        FLOAT,
    terminal_edge FLOAT,
    terminal_probability FLOAT,
    strike_delta FLOAT,
    chainlink_price FLOAT,
    btc_price   FLOAT,
    elapsed_seconds FLOAT,
    conditions_met INT,
    conditions_total INT,
    blocking_conditions TEXT,
    pnl         FLOAT,
    outcome     TEXT,
    settled     BOOLEAN DEFAULT FALSE,
    session_tag TEXT DEFAULT 'v2'
);

CREATE TABLE IF NOT EXISTS rolling_stats (
    id          TEXT PRIMARY KEY DEFAULT 'singleton',
    data        JSONB,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trade_archive (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ,
    data        JSONB
);

-- ==========================================================================
-- DASHBOARD VIEWS (V4 session-filtered)
-- ==========================================================================

CREATE OR REPLACE VIEW dashboard_trade_summary AS
SELECT
    COUNT(*) FILTER (WHERE outcome = 'win')  AS wins,
    COUNT(*) FILTER (WHERE outcome = 'loss') AS losses,
    COALESCE(SUM(pnl), 0)                   AS total_pnl,
    ROUND(AVG(pnl)::numeric, 4)             AS avg_pnl,
    COUNT(*)                                 AS total_trades
FROM trade_log
WHERE session_tag = 'V4';

CREATE OR REPLACE VIEW dashboard_shadow_summary AS
SELECT
    COUNT(*)                                 AS total,
    COUNT(*) FILTER (WHERE settled = TRUE)   AS settled,
    COUNT(*) FILTER (WHERE settled = TRUE AND outcome = 'win' AND size_usdc IS NOT NULL)  AS wins,
    COUNT(*) FILTER (WHERE settled = TRUE AND outcome = 'loss' AND size_usdc IS NOT NULL) AS losses,
    COALESCE(SUM(pnl) FILTER (WHERE settled = TRUE AND size_usdc IS NOT NULL), 0)::FLOAT AS total_pnl,
    COUNT(*) FILTER (WHERE settled = FALSE)  AS pending
FROM shadow_trade_log;

CREATE OR REPLACE VIEW dashboard_blockers AS
SELECT
    blocking_conditions AS name,
    COUNT(*)            AS cnt,
    COUNT(*) FILTER (WHERE outcome = 'win')  AS would_win,
    COUNT(*) FILTER (WHERE outcome = 'loss') AS would_lose,
    COALESCE(SUM(pnl), 0)                   AS missed_pnl
FROM shadow_trade_log
WHERE session_tag = 'V4'
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
WHERE session_tag = 'V4'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 48;

-- ==========================================================================
-- INDEXES
-- ==========================================================================

CREATE INDEX IF NOT EXISTS idx_signal_log_session_tag_ts
  ON signal_log (session_tag, ts DESC);

-- ==========================================================================
-- ROW-LEVEL SECURITY
-- ==========================================================================
-- anon role: SELECT only
-- service_role: ALL (used by bot for writes)

ALTER TABLE signal_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE shadow_trade_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE rolling_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_archive ENABLE ROW LEVEL SECURITY;

-- anon: read-only
CREATE POLICY IF NOT EXISTS "anon_select_signal_log" ON signal_log FOR SELECT TO anon USING (true);
CREATE POLICY IF NOT EXISTS "anon_select_trade_log" ON trade_log FOR SELECT TO anon USING (true);
CREATE POLICY IF NOT EXISTS "anon_select_shadow_trade_log" ON shadow_trade_log FOR SELECT TO anon USING (true);
CREATE POLICY IF NOT EXISTS "anon_select_rolling_stats" ON rolling_stats FOR SELECT TO anon USING (true);
CREATE POLICY IF NOT EXISTS "anon_select_trade_archive" ON trade_archive FOR SELECT TO anon USING (true);

-- service_role: full access
CREATE POLICY IF NOT EXISTS "service_all_signal_log" ON signal_log FOR ALL TO service_role USING (true);
CREATE POLICY IF NOT EXISTS "service_all_trade_log" ON trade_log FOR ALL TO service_role USING (true);
CREATE POLICY IF NOT EXISTS "service_all_shadow_trade_log" ON shadow_trade_log FOR ALL TO service_role USING (true);
CREATE POLICY IF NOT EXISTS "service_all_rolling_stats" ON rolling_stats FOR ALL TO service_role USING (true);
CREATE POLICY IF NOT EXISTS "service_all_trade_archive" ON trade_archive FOR ALL TO service_role USING (true);
