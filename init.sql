-- init.sql
-- Content Automation DB schema (Postgres)
-- Auto-executed on first container start

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- 1) Runs / logging (observability)
-- ============================================================
CREATE TABLE IF NOT EXISTS runs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_id      TEXT NOT NULL,
  run_key          TEXT UNIQUE,
  status           TEXT NOT NULL,
  started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at      TIMESTAMPTZ,
  error_message    TEXT,
  meta             JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs(workflow_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, started_at DESC);

-- ============================================================
-- 2) Content ideas (source of truth)
-- ============================================================
CREATE TABLE IF NOT EXISTS content_ideas (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idea_hash       TEXT UNIQUE NOT NULL,
  niche           TEXT,
  title           TEXT NOT NULL,
  premise         TEXT NOT NULL,
  sources         JSONB NOT NULL DEFAULT '[]'::jsonb,
  freshness_score NUMERIC NOT NULL DEFAULT 0,
  potential_score NUMERIC NOT NULL DEFAULT 0,
  status          TEXT NOT NULL DEFAULT 'new',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ideas_status_created ON content_ideas(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ideas_scores ON content_ideas(potential_score DESC, freshness_score DESC);
CREATE INDEX IF NOT EXISTS idx_ideas_hash ON content_ideas(idea_hash);

-- ============================================================
-- 3) Scripts (3 variants per idea: A/B/C)
-- ============================================================
CREATE TABLE IF NOT EXISTS scripts (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idea_id              UUID NOT NULL REFERENCES content_ideas(id) ON DELETE CASCADE,
  variant              TEXT NOT NULL,
  variant_name         TEXT,
  hook                 TEXT NOT NULL,
  script_text          TEXT NOT NULL,
  pacing_notes         TEXT,
  broll_cues           JSONB DEFAULT '[]'::jsonb,
  onscreen_text        JSONB DEFAULT '[]'::jsonb,
  ending               TEXT,
  word_count           INTEGER,
  estimated_duration_seconds INTEGER,
  status               TEXT NOT NULL DEFAULT 'draft',
  qa_feedback          TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (idea_id, variant)
);

CREATE INDEX IF NOT EXISTS idx_scripts_idea ON scripts(idea_id);
CREATE INDEX IF NOT EXISTS idx_scripts_status ON scripts(status, updated_at DESC);

-- ============================================================
-- 4) Assets (production outputs)
-- ============================================================
CREATE TABLE IF NOT EXISTS assets (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idea_id         UUID NOT NULL REFERENCES content_ideas(id) ON DELETE CASCADE,
  script_id       UUID REFERENCES scripts(id) ON DELETE CASCADE,
  asset_type      TEXT NOT NULL,
  storage_url     TEXT,
  payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_assets_idea_type ON assets(idea_id, asset_type);
CREATE INDEX IF NOT EXISTS idx_assets_script ON assets(script_id);

-- ============================================================
-- 5) QA results
-- ============================================================
CREATE TABLE IF NOT EXISTS qa_results (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idea_id         UUID NOT NULL REFERENCES content_ideas(id) ON DELETE CASCADE,
  script_id       UUID REFERENCES scripts(id) ON DELETE CASCADE,
  passed          BOOLEAN NOT NULL,
  issues          JSONB NOT NULL DEFAULT '[]'::jsonb,
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_qa_idea ON qa_results(idea_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qa_passed ON qa_results(passed, created_at DESC);

-- ============================================================
-- 6) Human approvals
-- ============================================================
CREATE TABLE IF NOT EXISTS approvals (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idea_id         UUID NOT NULL REFERENCES content_ideas(id) ON DELETE CASCADE,
  script_id       UUID REFERENCES scripts(id) ON DELETE CASCADE,
  decision        TEXT NOT NULL,
  notes           TEXT,
  decided_by      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_approvals_idea_created ON approvals(idea_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_approvals_decision ON approvals(decision, created_at DESC);

-- ============================================================
-- 7) Publish queue
-- ============================================================
CREATE TABLE IF NOT EXISTS publish_queue (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idea_id          UUID NOT NULL REFERENCES content_ideas(id) ON DELETE CASCADE,
  platform         TEXT NOT NULL,
  scheduled_at     TIMESTAMPTZ,
  status           TEXT NOT NULL DEFAULT 'queued',
  publish_pack     JSONB NOT NULL DEFAULT '{}'::jsonb,
  external_post_id TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (idea_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_queue_status_time ON publish_queue(status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_queue_platform ON publish_queue(platform, status);
CREATE INDEX IF NOT EXISTS idx_queue_external ON publish_queue(external_post_id);

-- ============================================================
-- 8) Analytics (daily metrics)
-- ============================================================
CREATE TABLE IF NOT EXISTS analytics_daily (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform         TEXT NOT NULL,
  external_post_id TEXT NOT NULL,
  date             DATE NOT NULL,
  metrics          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(platform, external_post_id, date)
);

CREATE INDEX IF NOT EXISTS idx_analytics_platform_date ON analytics_daily(platform, date DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_post ON analytics_daily(external_post_id, date DESC);

-- ============================================================
-- 9) Content library (hooks)
-- ============================================================
CREATE TABLE IF NOT EXISTS hooks_library (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hook_text    TEXT NOT NULL,
  tags         JSONB NOT NULL DEFAULT '[]'::jsonb,
  performance  JSONB NOT NULL DEFAULT '{}'::jsonb,
  usage_count  INTEGER DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  archived_at  TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hooks_performance ON hooks_library((performance->>'avg_views') DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_hooks_archived ON hooks_library(archived_at) WHERE archived_at IS NULL;

-- ============================================================
-- 10) Content library (patterns)
-- ============================================================
CREATE TABLE IF NOT EXISTS patterns_library (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pattern_name TEXT NOT NULL UNIQUE,
  description  TEXT NOT NULL,
  do_use       BOOLEAN NOT NULL DEFAULT true,
  success_rate NUMERIC DEFAULT 0,
  examples     JSONB NOT NULL DEFAULT '[]'::jsonb,
  first_seen_at TIMESTAMPTZ DEFAULT now(),
  last_seen_at TIMESTAMPTZ DEFAULT now(),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_patterns_do_use ON patterns_library(do_use, success_rate DESC);
CREATE INDEX IF NOT EXISTS idx_patterns_last_seen ON patterns_library(last_seen_at);

-- ============================================================
-- Verification
-- ============================================================
DO $$
BEGIN
  RAISE NOTICE 'Content Automation schema initialized successfully';
  RAISE NOTICE 'Tables created: runs, content_ideas, scripts, assets, qa_results, approvals, publish_queue, analytics_daily, hooks_library, patterns_library';
END $$;
