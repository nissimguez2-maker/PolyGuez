-- Migration: add missing indexes (views were already on V5 via prior migration)
-- Applied: 2026-04-19

-- Dedup check in log_trade: WHERE signal_id = $1
CREATE INDEX IF NOT EXISTS idx_trade_log_signal_id
  ON trade_log (signal_id);

-- settle_shadow_trades(): WHERE market_id = $1 AND settled = FALSE
CREATE INDEX IF NOT EXISTS idx_shadow_market_settled
  ON shadow_trade_log (market_id, settled);

-- Per-market signal history lookups
CREATE INDEX IF NOT EXISTS idx_signal_log_market_ts
  ON signal_log (market_id, ts DESC);
