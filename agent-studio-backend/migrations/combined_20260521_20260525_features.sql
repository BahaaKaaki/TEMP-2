-- ============================================================================
-- Combined migration (idempotent / safe to re-run)
-- ============================================================================
-- Merges (in order):
--   add_llm_model_catalog.sql              (2026-05-21)
--   add_llm_workflow_usage_workflow_counts.sql (2026-05-21)
--   add_analytics_snapshot.sql             (2026-05-25)
--   add_kb_owner_document_rls.sql          (2026-05-25)
--   add_llm_model_cache_pricing.sql        (2026-05-25)
--   add_llm_model_pricing.sql              (2026-05-25)
--   add_shared_tools.sql                   (2026-05-25)
--   seed_shared_tools_external_apps.sql    (2026-05-25)
-- ============================================================================

-- ============================================================================
-- 1. add_llm_model_catalog.sql
-- ============================================================================
-- Unified LLM model catalog (Task 0 central configuration)

CREATE TABLE IF NOT EXISTS llm_models (
    model_name              VARCHAR(128) PRIMARY KEY,
    provider                VARCHAR(32),
    display_label           VARCHAR(255),
    fallback_model_name     VARCHAR(128) REFERENCES llm_models(model_name) ON DELETE SET NULL,
    is_deprecated           BOOLEAN NOT NULL DEFAULT FALSE,
    discovered_in_proxy     BOOLEAN NOT NULL DEFAULT FALSE,
    "createdAt"             TIMESTAMP NOT NULL DEFAULT NOW(),
    "updatedAt"             TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_model_bindings (
    binding_key             VARCHAR(128) PRIMARY KEY,
    binding_type            VARCHAR(32) NOT NULL,
    primary_model_name      VARCHAR(128) NOT NULL REFERENCES llm_models(model_name),
    display_name            VARCHAR(255),
    description             TEXT,
    source_file             VARCHAR(512),
    enabled                 BOOLEAN NOT NULL DEFAULT TRUE,
    "updatedById"           VARCHAR(36) REFERENCES "user"(id) ON DELETE SET NULL,
    "createdAt"             TIMESTAMP NOT NULL DEFAULT NOW(),
    "updatedAt"             TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_model_bindings_type ON llm_model_bindings (binding_type);

CREATE TABLE IF NOT EXISTS llm_model_workflow_usage (
    model_name              VARCHAR(128) PRIMARY KEY REFERENCES llm_models(model_name) ON DELETE CASCADE,
    live_occurrences        INTEGER NOT NULL DEFAULT 0,
    published_occurrences   INTEGER NOT NULL DEFAULT 0,
    "lastScannedAt"         TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id                      VARCHAR(36) PRIMARY KEY,
    "adminUserId"           VARCHAR(36) REFERENCES "user"(id) ON DELETE SET NULL,
    action                  VARCHAR(64) NOT NULL,
    entity_type             VARCHAR(64),
    entity_id               VARCHAR(256),
    details                 TEXT,
    "createdAt"             TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created ON admin_audit_log ("createdAt" DESC);

-- ============================================================================
-- 2. add_llm_workflow_usage_workflow_counts.sql
-- ============================================================================
-- Workflow-level usage counts (in addition to per-node field reference counts)

ALTER TABLE llm_model_workflow_usage
    ADD COLUMN IF NOT EXISTS live_workflows INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS live_field_refs INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS published_workflows INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS published_snapshots INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS published_field_refs INTEGER NOT NULL DEFAULT 0;

-- Backfill field refs from legacy columns where present
UPDATE llm_model_workflow_usage
SET
    live_field_refs = live_occurrences,
    published_field_refs = published_occurrences
WHERE live_field_refs = 0 AND published_field_refs = 0
  AND (live_occurrences > 0 OR published_occurrences > 0);

-- ============================================================================
-- 3. add_analytics_snapshot.sql
-- ============================================================================
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

-- ============================================================================
-- 4. add_kb_owner_document_rls.sql
-- ============================================================================
-- KB owners can list documents uploaded by write-shared collaborators.
-- Safe to re-run (idempotent).

DROP POLICY IF EXISTS kb_owner_document_select_policy ON rag_document;

CREATE POLICY kb_owner_document_select_policy ON rag_document
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM knowledge_base kb
            WHERE kb.id = rag_document."kbId"
              AND kb."createdBy"::text = current_setting('app.current_user_id', true)
        )
    );

-- ============================================================================
-- 5. add_llm_model_cache_pricing.sql
-- ============================================================================
-- Cache read/write pricing for Langfuse cost tracking (USD per 1M tokens).

ALTER TABLE llm_models
    ADD COLUMN IF NOT EXISTS cache_read_price_per_1m_tokens NUMERIC(14, 6),
    ADD COLUMN IF NOT EXISTS cache_creation_price_per_1m_tokens NUMERIC(14, 6);

-- ============================================================================
-- 6. add_llm_model_pricing.sql
-- ============================================================================
-- Pricing and admin metadata on the canonical llm_models catalog (single source of truth).

ALTER TABLE llm_models
    ADD COLUMN IF NOT EXISTS input_price_per_1m_tokens NUMERIC(14, 6),
    ADD COLUMN IF NOT EXISTS output_price_per_1m_tokens NUMERIC(14, 6),
    ADD COLUMN IF NOT EXISTS admin_notes TEXT,
    ADD COLUMN IF NOT EXISTS langfuse_match_pattern VARCHAR(512),
    ADD COLUMN IF NOT EXISTS langfuse_last_synced_at TIMESTAMP;

-- ============================================================================
-- 7. add_shared_tools.sql
-- ============================================================================
-- Migration: Shared External Tools
-- Adds:
--   * shared_tool              external tool links visible in storefront
--   * shared_tool_permission   AD group / user grants for shared tools
--   * shared_tool_audit_log    audit trail for admin operations
--   * submission_type column on marketplace_submission
--
-- RLS policies are installed/refreshed on startup by db/init_security.py.
-- Run this script only if you want to apply changes without restarting.

CREATE TABLE IF NOT EXISTS shared_tool (
    id              VARCHAR(36)  PRIMARY KEY NOT NULL,
    tool_name       VARCHAR(255) NOT NULL,
    description     TEXT,
    url             TEXT         NOT NULL,
    is_public       BOOLEAN      NOT NULL DEFAULT false,
    status          VARCHAR(20)  NOT NULL DEFAULT 'approved',
    created_by      VARCHAR(36)  NOT NULL REFERENCES "user"(id),
    approved_by     VARCHAR(36)  REFERENCES "user"(id),
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_shared_tool_name_url UNIQUE (tool_name, url)
);

CREATE INDEX IF NOT EXISTS idx_shared_tool_status ON shared_tool(status);
CREATE INDEX IF NOT EXISTS idx_shared_tool_public ON shared_tool(is_public, status);
CREATE INDEX IF NOT EXISTS idx_shared_tool_created_by ON shared_tool(created_by);

CREATE TABLE IF NOT EXISTS shared_tool_permission (
    id               VARCHAR(36)  PRIMARY KEY NOT NULL,
    shared_tool_id   VARCHAR(36)  NOT NULL REFERENCES shared_tool(id) ON DELETE CASCADE,
    principal_type   VARCHAR(10)  NOT NULL CHECK (principal_type IN ('group', 'user')),
    principal_id     VARCHAR(36)  NOT NULL,
    created_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_shared_tool_perm_target UNIQUE (shared_tool_id, principal_type, principal_id)
);

CREATE INDEX IF NOT EXISTS idx_shared_tool_perm_tool ON shared_tool_permission(shared_tool_id);
CREATE INDEX IF NOT EXISTS idx_shared_tool_perm_principal ON shared_tool_permission(principal_type, principal_id);

CREATE TABLE IF NOT EXISTS shared_tool_audit_log (
    id               VARCHAR(36)  PRIMARY KEY NOT NULL,
    shared_tool_id   VARCHAR(36)  REFERENCES shared_tool(id) ON DELETE SET NULL,
    action           VARCHAR(50)  NOT NULL,
    performed_by     VARCHAR(36)  NOT NULL REFERENCES "user"(id),
    performed_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    details          JSONB
);

CREATE INDEX IF NOT EXISTS idx_shared_tool_audit_time
    ON shared_tool_audit_log(performed_at DESC);
CREATE INDEX IF NOT EXISTS idx_shared_tool_audit_tool
    ON shared_tool_audit_log(shared_tool_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'marketplace_submission'
          AND column_name = 'submission_type'
    ) THEN
        ALTER TABLE marketplace_submission
            ADD COLUMN submission_type VARCHAR(20) NOT NULL DEFAULT 'workflow';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'marketplace_submission'
          AND column_name = 'meta'
    ) THEN
        ALTER TABLE marketplace_submission
            ADD COLUMN meta JSONB;
    END IF;
END $$;

ALTER TABLE marketplace_submission
    ALTER COLUMN "workflowId" DROP NOT NULL;

ALTER TABLE shared_tool ENABLE ROW LEVEL SECURITY;
ALTER TABLE shared_tool FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS shared_tool_select_policy ON shared_tool;
DROP POLICY IF EXISTS shared_tool_insert_policy ON shared_tool;
DROP POLICY IF EXISTS shared_tool_modify_policy ON shared_tool;
DROP POLICY IF EXISTS shared_tool_delete_policy ON shared_tool;

CREATE POLICY shared_tool_select_policy ON shared_tool
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM "user" u
            WHERE u.id = current_setting('app.current_user_id', true)
              AND u."roleSlug" LIKE '%admin%'
        )
        OR (created_by = current_setting('app.current_user_id', true))
        OR (status = 'approved' AND is_public = true)
        OR (status = 'approved' AND EXISTS (
            SELECT 1 FROM shared_tool_permission p
            WHERE p.shared_tool_id = shared_tool.id
              AND p.principal_type = 'user'
              AND p.principal_id = current_setting('app.current_user_id', true)
        ))
        OR (status = 'approved' AND EXISTS (
            SELECT 1 FROM shared_tool_permission p
            WHERE p.shared_tool_id = shared_tool.id
              AND p.principal_type = 'group'
              AND p.principal_id = ANY(app_current_user_groups())
        ))
    );

CREATE POLICY shared_tool_insert_policy ON shared_tool
    FOR INSERT WITH CHECK (true);

CREATE POLICY shared_tool_modify_policy ON shared_tool
    FOR UPDATE USING (
        EXISTS (
            SELECT 1 FROM "user" u
            WHERE u.id = current_setting('app.current_user_id', true)
              AND u."roleSlug" LIKE '%admin%'
        )
    );

CREATE POLICY shared_tool_delete_policy ON shared_tool
    FOR DELETE USING (
        EXISTS (
            SELECT 1 FROM "user" u
            WHERE u.id = current_setting('app.current_user_id', true)
              AND u."roleSlug" LIKE '%admin%'
        )
    );

ALTER TABLE shared_tool_permission ENABLE ROW LEVEL SECURITY;
ALTER TABLE shared_tool_permission FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS shared_tool_perm_select_policy ON shared_tool_permission;
DROP POLICY IF EXISTS shared_tool_perm_insert_policy ON shared_tool_permission;
DROP POLICY IF EXISTS shared_tool_perm_modify_policy ON shared_tool_permission;
DROP POLICY IF EXISTS shared_tool_perm_delete_policy ON shared_tool_permission;

CREATE POLICY shared_tool_perm_select_policy ON shared_tool_permission
    FOR SELECT USING (true);

CREATE POLICY shared_tool_perm_insert_policy ON shared_tool_permission
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM "user" u
            WHERE u.id = current_setting('app.current_user_id', true)
              AND u."roleSlug" LIKE '%admin%'
        )
    );

CREATE POLICY shared_tool_perm_modify_policy ON shared_tool_permission
    FOR UPDATE USING (
        EXISTS (
            SELECT 1 FROM "user" u
            WHERE u.id = current_setting('app.current_user_id', true)
              AND u."roleSlug" LIKE '%admin%'
        )
    );

CREATE POLICY shared_tool_perm_delete_policy ON shared_tool_permission
    FOR DELETE USING (
        EXISTS (
            SELECT 1 FROM "user" u
            WHERE u.id = current_setting('app.current_user_id', true)
              AND u."roleSlug" LIKE '%admin%'
        )
    );

ALTER TABLE shared_tool_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE shared_tool_audit_log FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS shared_tool_audit_select_policy ON shared_tool_audit_log;
DROP POLICY IF EXISTS shared_tool_audit_insert_policy ON shared_tool_audit_log;

CREATE POLICY shared_tool_audit_select_policy ON shared_tool_audit_log
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM "user" u
            WHERE u.id = current_setting('app.current_user_id', true)
              AND u."roleSlug" LIKE '%admin%'
        )
    );

CREATE POLICY shared_tool_audit_insert_policy ON shared_tool_audit_log
    FOR INSERT WITH CHECK (true);

-- ============================================================================
-- 8. seed_shared_tools_external_apps.sql
-- ============================================================================
-- Migrate hardcoded EXTERNAL_APPS into shared_tool table.
-- Idempotent: uses ON CONFLICT DO NOTHING.
-- Requires at least one user (admin preferred).

DO $$
DECLARE
    v_admin_id VARCHAR(36);
BEGIN
    SELECT id INTO v_admin_id
    FROM "user"
    WHERE "roleSlug" LIKE '%admin%'
    LIMIT 1;

    IF v_admin_id IS NULL THEN
        SELECT id INTO v_admin_id FROM "user" LIMIT 1;
    END IF;

    IF v_admin_id IS NULL THEN
        RAISE NOTICE 'No users found — skipping seed. Run after first user signs in.';
        RETURN;
    END IF;

    INSERT INTO shared_tool (id, tool_name, description, url, is_public, status, created_by, approved_by, created_at, updated_at)
    VALUES
        (gen_random_uuid()::text, 'FDI Analyzer',
         'Provides a unified, data-driven view across FDI markets to support informed analysis',
         'https://fdi-tracker-app.azurewebsites.net/explore',
         true, 'approved', v_admin_id, v_admin_id, NOW(), NOW()),
        (gen_random_uuid()::text, 'Edwin Slide Creator',
         'Integrated app to generate PPT decks and slides',
         'https://app-edwin-slides.azurewebsites.net/',
         true, 'approved', v_admin_id, v_admin_id, NOW(), NOW()),
        (gen_random_uuid()::text, 'Business Case Assistant',
         'Structure and assess complex business opportunities more efficiently',
         'https://workflows.stage.agentstoolbox.mer.pwcinternal.com/dashboard',
         true, 'approved', v_admin_id, v_admin_id, NOW(), NOW()),
        (gen_random_uuid()::text, 'Agri-Food Intelligence',
         'Provides a unified, data-driven view across the agri-food value chain to support informed analysis',
         'https://eu.workbench.pwc.com/report-viewer/shared/0wMVQwOTozMjozNi42Nj',
         true, 'approved', v_admin_id, v_admin_id, NOW(), NOW()),
        (gen_random_uuid()::text, 'Policy Bot',
         'Conduct research and generate policy recommendations for any policy-related topics',
         'https://ca-policy-frontend.happycliff-41c6de54.eastus.azurecontainerapps.io/auth',
         true, 'approved', v_admin_id, v_admin_id, NOW(), NOW()),
        (gen_random_uuid()::text, 'Trade Intelligence',
         'Provides a unified, data-driven view across trade flows to support informed analysis',
         'https://trade-intelligence-platform.103-150-136-247.sslip.io/',
         true, 'approved', v_admin_id, v_admin_id, NOW(), NOW())
    ON CONFLICT (tool_name, url) DO NOTHING;

    RAISE NOTICE 'Seeded external apps into shared_tool table (admin: %)', v_admin_id;
END $$;

-- ============================================================================
-- Verify
-- ============================================================================
SELECT 'kb_owner_document_select_policy applied' AS status
WHERE EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'rag_document'
      AND policyname = 'kb_owner_document_select_policy'
);

SELECT
    tablename,
    policyname,
    cmd
FROM pg_policies
WHERE tablename IN (
    'shared_tool',
    'shared_tool_permission',
    'shared_tool_audit_log'
)
ORDER BY tablename, policyname;

SELECT 'combined_20260521_20260525_features migration completed successfully!' AS status;
