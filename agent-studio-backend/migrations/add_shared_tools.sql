-- ============================================================================
-- Migration: Shared External Tools
-- ============================================================================
-- Adds:
--   * shared_tool              external tool links visible in storefront
--   * shared_tool_permission   AD group / user grants for shared tools
--   * shared_tool_audit_log    audit trail for admin operations
--   * submission_type column on marketplace_submission
--
-- RLS policies are installed/refreshed on startup by db/init_security.py.
-- Run this script only if you want to apply changes without restarting.
--
-- Idempotent / safe to re-run.
-- ============================================================================

-- ============================================================================
-- 1. shared_tool: external tool links
-- ============================================================================
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

-- ============================================================================
-- 2. shared_tool_permission: group / user grants
-- ============================================================================
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

-- ============================================================================
-- 3. shared_tool_audit_log: full audit trail
-- ============================================================================
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

-- ============================================================================
-- 4. Add submission_type to marketplace_submission
-- ============================================================================
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

-- Add meta JSONB column for storing submission metadata (sharing targets etc.)
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

-- Make workflowId nullable (shared_tool submissions don't have a workflow)
ALTER TABLE marketplace_submission
    ALTER COLUMN "workflowId" DROP NOT NULL;

-- ============================================================================
-- 5. RLS on shared_tool
-- ============================================================================
ALTER TABLE shared_tool ENABLE ROW LEVEL SECURITY;
ALTER TABLE shared_tool FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS shared_tool_select_policy ON shared_tool;
DROP POLICY IF EXISTS shared_tool_insert_policy ON shared_tool;
DROP POLICY IF EXISTS shared_tool_modify_policy ON shared_tool;
DROP POLICY IF EXISTS shared_tool_delete_policy ON shared_tool;

-- SELECT: approved+public, or approved+permission match, or admin, or own pending
CREATE POLICY shared_tool_select_policy ON shared_tool
    FOR SELECT USING (
        -- Admins see everything
        EXISTS (
            SELECT 1 FROM "user" u
            WHERE u.id = current_setting('app.current_user_id', true)
              AND u."roleSlug" LIKE '%admin%'
        )
        -- Creator can see their own pending submissions
        OR (created_by = current_setting('app.current_user_id', true))
        -- Approved + public
        OR (status = 'approved' AND is_public = true)
        -- Approved + user permission
        OR (status = 'approved' AND EXISTS (
            SELECT 1 FROM shared_tool_permission p
            WHERE p.shared_tool_id = shared_tool.id
              AND p.principal_type = 'user'
              AND p.principal_id = current_setting('app.current_user_id', true)
        ))
        -- Approved + group permission
        OR (status = 'approved' AND EXISTS (
            SELECT 1 FROM shared_tool_permission p
            WHERE p.shared_tool_id = shared_tool.id
              AND p.principal_type = 'group'
              AND p.principal_id = ANY(app_current_user_groups())
        ))
    );

CREATE POLICY shared_tool_insert_policy ON shared_tool
    FOR INSERT WITH CHECK (true);

-- UPDATE/DELETE: admin only
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

-- ============================================================================
-- 6. RLS on shared_tool_permission
-- ============================================================================
ALTER TABLE shared_tool_permission ENABLE ROW LEVEL SECURITY;
ALTER TABLE shared_tool_permission FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS shared_tool_perm_select_policy ON shared_tool_permission;
DROP POLICY IF EXISTS shared_tool_perm_insert_policy ON shared_tool_permission;
DROP POLICY IF EXISTS shared_tool_perm_modify_policy ON shared_tool_permission;
DROP POLICY IF EXISTS shared_tool_perm_delete_policy ON shared_tool_permission;

-- Anyone can read permissions (needed for RLS subqueries on shared_tool)
CREATE POLICY shared_tool_perm_select_policy ON shared_tool_permission
    FOR SELECT USING (true);

-- Admin only mutations
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

-- ============================================================================
-- 7. RLS on shared_tool_audit_log
-- ============================================================================
ALTER TABLE shared_tool_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE shared_tool_audit_log FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS shared_tool_audit_select_policy ON shared_tool_audit_log;
DROP POLICY IF EXISTS shared_tool_audit_insert_policy ON shared_tool_audit_log;

-- Only admins can read audit logs
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
-- 8. Verify
-- ============================================================================
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

SELECT 'Shared tools migration completed successfully!' AS status;
