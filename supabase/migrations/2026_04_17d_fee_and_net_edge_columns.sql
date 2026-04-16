-- Phase 1.6 / 1.1 (log-only variant per user decision 2026-04-16): add the
-- columns needed to track fees and fee-adjusted edge, plus the composite
-- indexes the audit flagged as missing.
--
-- The decision on Phase 1.1 was to *log* net_edge but NOT yet gate on it
-- (CLAUDE.md says no signal-gate changes without calibrated outcome data,
-- and the k-recalibration plan is to observe V5 live trades unchanged).
-- The schema additions below keep the data channel ready so the gate change
-- in Phase 4.1 (post-100-live-trades k-recal) doesn't need another migration.

-- ---------------------------------------------------------------------------
-- signal_log: add net_edge (fee-adjusted edge, logged for calibration)
-- ---------------------------------------------------------------------------
ALTER TABLE signal_log
    ADD COLUMN IF NOT EXISTS net_edge DOUBLE PRECISION;

COMMENT ON COLUMN signal_log.net_edge IS
    'terminal_edge - taker_fee_coefficient * token_price * (1 - token_price). '
    'Logged for post-hoc calibration of live-realistic profitability. Not yet '
    'a gate as of 2026-04-16 — will be once k-recal Phase 4 lands.';

-- ---------------------------------------------------------------------------
-- trade_log: add fee_paid, taker_maker, and terminal_edge (dashboard reads it)
-- ---------------------------------------------------------------------------
ALTER TABLE trade_log
    ADD COLUMN IF NOT EXISTS fee_paid DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS taker_maker TEXT,
    ADD COLUMN IF NOT EXISTS terminal_edge DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS net_edge DOUBLE PRECISION;

COMMENT ON COLUMN trade_log.fee_paid IS
    'Polymarket fee actually paid on this trade (negative = rebate on maker '
    'fills). NULL in dry-run.';
COMMENT ON COLUMN trade_log.taker_maker IS
    '"maker" when a GTD limit order rested and filled passively; "taker" when '
    'the FOK market-order fallback executed. NULL in dry-run.';

-- ---------------------------------------------------------------------------
-- Composite indexes flagged by the audit as missing
-- ---------------------------------------------------------------------------
-- trade_log (session_tag, ts DESC): dashboard's pollSlow runs
--   ORDER BY ts DESC LIMIT 20 scoped to the active session.
CREATE INDEX IF NOT EXISTS idx_trade_log_session_tag_ts
    ON trade_log (session_tag, ts DESC);

-- shadow_trade_log (settled, market_id): settlement loop queries
--   WHERE market_id = ? AND settled = FALSE repeatedly.
CREATE INDEX IF NOT EXISTS idx_shadow_trade_log_settled_market
    ON shadow_trade_log (settled, market_id);
