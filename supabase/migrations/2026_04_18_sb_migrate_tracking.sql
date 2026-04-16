-- Tracking table for scripts/ops/sb_migrate.py.
--
-- Each row = one applied migration file. sb_migrate.py queries this
-- table, skips anything already present, and inserts on successful
-- apply. Makes migrations re-runnable (idempotent at the runner level,
-- independent of whether the SQL itself is idempotent — necessary since
-- Postgres `CREATE POLICY` has no `IF NOT EXISTS` clause).
--
-- Seeded with the 10 migrations applied via MCP before this table
-- existed (up to and including 2026_04_18_signal_eval_prices.sql).
--
-- Applied to prod via MCP on 2026-04-16. This file is kept in the
-- migrations directory so a fresh deploy builds the table + seeds it
-- in one step.

CREATE TABLE IF NOT EXISTS _sb_migrate_applied (
    filename   TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_by TEXT NOT NULL DEFAULT current_user
);

INSERT INTO _sb_migrate_applied (filename) VALUES
    ('2026_04_align_session_tag.sql'),
    ('2026_04_blocker_ratio_24h.sql'),
    ('2026_04_17_restrict_anon_to_dry_run.sql'),
    ('2026_04_17b_drop_legacy_anon_read_policies.sql'),
    ('2026_04_17c_hygiene_revoke_anon_writes.sql'),
    ('2026_04_17d_fee_and_net_edge_columns.sql'),
    ('2026_04_18_calibration_view.sql'),
    ('2026_04_18_cleanse_pre_v5.sql'),
    ('2026_04_18_fill_price.sql'),
    ('2026_04_18_signal_eval_prices.sql')
ON CONFLICT (filename) DO NOTHING;
