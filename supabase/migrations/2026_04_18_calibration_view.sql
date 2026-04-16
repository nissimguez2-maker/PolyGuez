-- MODEL-03: calibration infrastructure.
--
-- Creates two views and one RPC function:
--
-- 1. `signal_outcome_matched` — joins each fired signal to its resolved
--    trade via signal_id, exposing a binary outcome column suitable for
--    Brier-score and calibration-slope calculations. Only rows where
--    `trade_fired=TRUE` (i.e. the bot actually took the signal) and the
--    trade has resolved (outcome IN ('win','loss','emergency-exit')) are
--    included.
--
-- 2. `session_brier_scores` — per-(session_tag, era) aggregate that
--    computes Brier score, avg predicted probability, realized rate,
--    PnL total, and maker/taker breakdown. Brier ranges from 0 (perfect)
--    through 0.25 (random) to 1.0 (always wrong).
--
-- 3. `get_session_brier(p_session_tag TEXT)` — SQL-language RPC callable
--    from PostgREST via `client.rpc("get_session_brier", {...})`.
--    Required by MODEL-01's programmatic live-mode gate.
--
-- Until MODEL-02 lands, `fee_paid` and `taker_maker` are NULL on every
-- trade_log row, so the maker_fills/taker_fills counts will be zero.
-- The Brier score itself is computable as soon as any V5 trade has a
-- resolved outcome.

CREATE OR REPLACE VIEW signal_outcome_matched AS
SELECT
    sl.signal_id,
    sl.session_tag,
    sl.era,
    sl.ts,
    sl.terminal_probability,
    sl.entry_side,
    sl.net_edge,
    CASE
        WHEN tl.outcome = 'win'                        THEN 1.0
        WHEN tl.outcome IN ('loss', 'emergency-exit')  THEN 0.0
        ELSE NULL
    END AS outcome_bin,
    tl.outcome,
    tl.fee_paid,
    tl.taker_maker,
    tl.pnl
FROM signal_log sl
INNER JOIN trade_log tl ON tl.signal_id = sl.signal_id
WHERE sl.trade_fired = TRUE;

CREATE OR REPLACE VIEW session_brier_scores AS
SELECT
    session_tag,
    era,
    COUNT(*)                                                              AS n_trades,
    ROUND(AVG(POWER(outcome_bin - terminal_probability, 2))::numeric, 4)   AS brier_score,
    ROUND(AVG(terminal_probability)::numeric, 4)                          AS avg_predicted_prob,
    ROUND(AVG(outcome_bin)::numeric, 4)                                   AS avg_realized_rate,
    ROUND(COALESCE(SUM(pnl), 0)::numeric, 4)                              AS total_pnl,
    COUNT(*) FILTER (WHERE taker_maker = 'maker')                         AS maker_fills,
    COUNT(*) FILTER (WHERE taker_maker = 'taker')                         AS taker_fills
FROM signal_outcome_matched
WHERE outcome_bin IS NOT NULL
GROUP BY session_tag, era
ORDER BY era DESC, session_tag;

-- RPC callable from Python for the live-mode gate.
CREATE OR REPLACE FUNCTION get_session_brier(p_session_tag TEXT)
RETURNS TABLE(
    session_tag TEXT,
    brier FLOAT,
    n_trades INT,
    avg_predicted FLOAT,
    avg_realized FLOAT
)
LANGUAGE SQL STABLE AS $$
    SELECT
        session_tag::TEXT,
        brier_score::FLOAT,
        n_trades::INT,
        avg_predicted_prob::FLOAT,
        avg_realized_rate::FLOAT
    FROM session_brier_scores
    WHERE session_tag = p_session_tag
    ORDER BY era DESC
    LIMIT 1;
$$;
