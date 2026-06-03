-- Analytics pre-aggregated snapshot tables
-- Designed for on-demand refresh (admin "Refresh" button)
-- Avoids real-time computation overhead on the main server

-- Daily execution aggregates: one row per (date, workflow, user, status, mode)
CREATE TABLE IF NOT EXISTS analytics_execution_daily (
    id                  SERIAL PRIMARY KEY,
    date                DATE NOT NULL,
    workflow_id         VARCHAR(36) NOT NULL,
    workflow_name       VARCHAR(128),
    user_id             VARCHAR(36),
    user_email          VARCHAR(255),
    status              VARCHAR(30) NOT NULL,
    mode                VARCHAR(20) NOT NULL DEFAULT 'manual',

    -- Metrics
    execution_count     INTEGER NOT NULL DEFAULT 0,
    avg_duration_ms     DOUBLE PRECISION,
    min_duration_ms     DOUBLE PRECISION,
    max_duration_ms     DOUBLE PRECISION,
    total_duration_ms   DOUBLE PRECISION,

    -- Token/cost (populated from Langfuse)
    total_input_tokens  BIGINT DEFAULT 0,
    total_output_tokens BIGINT DEFAULT 0,
    total_tokens        BIGINT DEFAULT 0,
    total_cost_usd      DOUBLE PRECISION DEFAULT 0,
    llm_call_count      INTEGER DEFAULT 0,

    -- Snapshot metadata
    snapshot_version    INTEGER NOT NULL DEFAULT 1,
    computed_at         TIMESTAMP NOT NULL DEFAULT NOW(),

    UNIQUE(date, workflow_id, user_id, status, mode)
);

CREATE INDEX IF NOT EXISTS idx_analytics_exec_daily_date ON analytics_execution_daily (date DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_exec_daily_workflow ON analytics_execution_daily (workflow_id, date);
CREATE INDEX IF NOT EXISTS idx_analytics_exec_daily_user ON analytics_execution_daily (user_id, date);

-- Model-level daily consumption (from Langfuse)
CREATE TABLE IF NOT EXISTS analytics_model_daily (
    id                  SERIAL PRIMARY KEY,
    date                DATE NOT NULL,
    model_name          VARCHAR(128) NOT NULL,
    provider            VARCHAR(32),

    -- Metrics
    generation_count    INTEGER NOT NULL DEFAULT 0,
    total_input_tokens  BIGINT DEFAULT 0,
    total_output_tokens BIGINT DEFAULT 0,
    total_tokens        BIGINT DEFAULT 0,
    cache_read_tokens   BIGINT DEFAULT 0,
    cache_creation_tokens BIGINT DEFAULT 0,
    total_cost_usd      DOUBLE PRECISION DEFAULT 0,

    -- Snapshot metadata
    computed_at         TIMESTAMP NOT NULL DEFAULT NOW(),

    UNIQUE(date, model_name)
);

CREATE INDEX IF NOT EXISTS idx_analytics_model_daily_date ON analytics_model_daily (date DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_model_daily_model ON analytics_model_daily (model_name, date);

-- Service-level daily consumption (non-workflow: embeddings, code executor, OCR, etc.)
CREATE TABLE IF NOT EXISTS analytics_service_daily (
    id                  SERIAL PRIMARY KEY,
    date                DATE NOT NULL,
    service_name        VARCHAR(128) NOT NULL,  -- e.g. 'embedding', 'code_executor', 'ocr', 'image'
    binding_key         VARCHAR(128),           -- e.g. 'service.embedding', 'tool.code_executor'
    model_name          VARCHAR(128),
    user_id             VARCHAR(36),
    user_email          VARCHAR(255),

    -- Metrics
    call_count          INTEGER NOT NULL DEFAULT 0,
    total_input_tokens  BIGINT DEFAULT 0,
    total_output_tokens BIGINT DEFAULT 0,
    total_tokens        BIGINT DEFAULT 0,
    total_cost_usd      DOUBLE PRECISION DEFAULT 0,

    -- Snapshot metadata
    computed_at         TIMESTAMP NOT NULL DEFAULT NOW(),

    UNIQUE(date, service_name, binding_key, model_name, user_id)
);

CREATE INDEX IF NOT EXISTS idx_analytics_service_daily_date ON analytics_service_daily (date DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_service_daily_service ON analytics_service_daily (service_name, date);

-- Snapshot metadata: tracks when each refresh ran and its coverage
CREATE TABLE IF NOT EXISTS analytics_refresh_log (
    id                  SERIAL PRIMARY KEY,
    refresh_type        VARCHAR(32) NOT NULL,  -- 'full', 'incremental', 'langfuse_only'
    started_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMP,
    status              VARCHAR(20) NOT NULL DEFAULT 'running',  -- 'running', 'completed', 'failed'
    date_from           DATE,
    date_to             DATE,
    rows_upserted       INTEGER DEFAULT 0,
    langfuse_traces     INTEGER DEFAULT 0,
    error_message       TEXT,
    triggered_by        VARCHAR(36)  -- admin user id
);
