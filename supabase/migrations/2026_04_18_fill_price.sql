-- MODEL-02: add fill_price column to trade_log.
--
-- The CLOB executor knows the actual fill price after a maker or FOK order
-- resolves, but that value was never persisted. Comparing fill_price to
-- the quote-at-signal price (already logged in signal_log) gives realized
-- slippage per trade, which matters as soon as live-mode trading starts.
--
-- Column is nullable. For dry-run rows it will be populated with the
-- simulated entry_price to keep the column non-NULL on every new row.

ALTER TABLE trade_log
    ADD COLUMN IF NOT EXISTS fill_price DOUBLE PRECISION;

COMMENT ON COLUMN trade_log.fill_price IS
    'Actual fill price returned by the CLOB order response. In dry-run/'
    'paper modes, populated with the simulated entry_price.';
