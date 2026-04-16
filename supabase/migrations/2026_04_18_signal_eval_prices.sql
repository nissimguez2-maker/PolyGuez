-- MODEL-04: signal-eval price snapshots.
--
-- Adds `signal_eval_yes_price` and `signal_eval_no_price` columns to
-- signal_log. These are the YES/NO token prices observed at the moment
-- the bot evaluated the signal. signal_log already persists `yes_price`
-- and `no_price` with effectively the same values, but those field names
-- are ambiguous (is it decision-time? post-entry? realtime?). The new
-- columns make the semantic explicit so the post-live slippage analysis
-- can cleanly compute `fill_price (from trade_log) - signal_eval_yes_price`
-- without guessing which field is the quote-at-signal.
--
-- All new rows will populate these fields (see `run_polyguez.log_signal`
-- payload). Historical rows stay NULL.

ALTER TABLE signal_log
    ADD COLUMN IF NOT EXISTS signal_eval_yes_price DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS signal_eval_no_price  DOUBLE PRECISION;

COMMENT ON COLUMN signal_log.signal_eval_yes_price IS
    'YES token price at the moment the signal was evaluated. Semantic-'
    'explicit companion to `yes_price` for post-live slippage analysis.';
COMMENT ON COLUMN signal_log.signal_eval_no_price IS
    'NO token price at the moment the signal was evaluated. Semantic-'
    'explicit companion to `no_price` for post-live slippage analysis.';
