-- ============================================================================
-- Migration: AD Group-based Sharing & RLS for workflows / knowledge bases
-- ============================================================================
-- ⚠️  IN MOST CASES YOU DO NOT NEED TO RUN THIS FILE MANUALLY.
--
-- The backend now self-bootstraps everything in this migration:
--   1. Tables (ad_group, user_group, workflow_share, knowledge_base_share)
--      are created automatically from SQLAlchemy models on startup
--      via Base.metadata.create_all() in db/pgsql.py.
--   2. The RLS policies and the app_current_user_groups() helper function
--      are installed/refreshed on every startup by db/init_security.py.
--
-- Run this script only if you want to apply the changes WITHOUT restarting
-- the backend (e.g. an ops one-shot against a hot DB).
--
-- Adds:
--   * ad_group              cache of Microsoft Entra ID security groups
--   * user_group            mirror of which AD groups each user belongs to
--   * workflow_share        sharing grants (group OR user) for workflows
--   * knowledge_base_share  sharing grants (group OR user) for KBs
--
-- And rewrites the SELECT/UPDATE/DELETE RLS policies on workflow_entity and
-- knowledge_base so they admit, in addition to the existing "owner only" rule:
--   * "isPublic = true" (already-shared marketplace items) for SELECT
--   * a matching row in workflow_share / knowledge_base_share for the
--     current user OR any of their AD groups
--
-- Reads two postgres session GUCs:
--   * app.current_user_id        -- existing
--   * app.current_user_groups    -- NEW, comma-separated list of AD group GUIDs
--
-- Idempotent / safe to re-run.
--
-- Usage:
--   psql -h <host> -U <admin_user> -d <database> -f add_ad_groups_and_sharing.sql
-- ============================================================================

-- ============================================================================
-- 1. ad_group: cached Microsoft Entra ID security group metadata
-- ============================================================================
CREATE TABLE IF NOT EXISTS ad_group (
    id              VARCHAR(36)  PRIMARY KEY NOT NULL,         -- AD object id (GUID)
    "displayName"   VARCHAR(255),
    description     TEXT,
    "lastSyncedAt"  TIMESTAMP    NOT NULL DEFAULT NOW(),
    "createdAt"     TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 2. user_group: which AD groups each user belongs to (refreshed at login)
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_group (
    "userId"   VARCHAR(36) NOT NULL REFERENCES "user"(id)    ON DELETE CASCADE,
    "groupId"  VARCHAR(36) NOT NULL REFERENCES ad_group(id)  ON DELETE CASCADE,
    "addedAt"  TIMESTAMP   NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("userId", "groupId")
);

CREATE INDEX IF NOT EXISTS idx_user_group_group ON user_group("groupId");

-- ============================================================================
-- 3. workflow_share: sharing grants for workflows (to a group OR a user)
-- ============================================================================
CREATE TABLE IF NOT EXISTS workflow_share (
    id               VARCHAR(36) PRIMARY KEY NOT NULL,
    "workflowId"     VARCHAR(36) NOT NULL REFERENCES workflow_entity(id) ON DELETE CASCADE,
    "principalType"  VARCHAR(10) NOT NULL CHECK ("principalType" IN ('group', 'user')),
    "principalId"    VARCHAR(36) NOT NULL,
    permission       VARCHAR(10) NOT NULL DEFAULT 'read' CHECK (permission IN ('read', 'write')),
    "grantedById"    VARCHAR(36) NOT NULL REFERENCES "user"(id),
    "grantedAt"      TIMESTAMP   NOT NULL DEFAULT NOW(),
    UNIQUE ("workflowId", "principalType", "principalId")
);

CREATE INDEX IF NOT EXISTS idx_workflow_share_principal
    ON workflow_share("principalType", "principalId");
CREATE INDEX IF NOT EXISTS idx_workflow_share_workflow
    ON workflow_share("workflowId");

-- ============================================================================
-- 3b. ms_oauth_token: per-user encrypted Microsoft refresh tokens
-- ============================================================================
-- Used so the backend can call Microsoft Graph "as the user" (delegated
-- Group.Read.All) for the share-dialog group typeahead. The plaintext
-- refresh token NEVER hits this column — utils/token_crypto.py wraps it
-- with Fernet before insert. RLS below restricts SELECT to the row's
-- owner with NO admin override.
CREATE TABLE IF NOT EXISTS ms_oauth_token (
    "userId"                  VARCHAR(36) PRIMARY KEY NOT NULL
        REFERENCES "user"(id) ON DELETE CASCADE,
    "refreshTokenEncrypted"   TEXT        NOT NULL,
    scopes                    TEXT        NOT NULL,
    "createdAt"               TIMESTAMP   NOT NULL DEFAULT NOW(),
    "updatedAt"               TIMESTAMP   NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 4. knowledge_base_share: sharing grants for KBs
-- ============================================================================
CREATE TABLE IF NOT EXISTS knowledge_base_share (
    id                  VARCHAR(36) PRIMARY KEY NOT NULL,
    "knowledgeBaseId"   VARCHAR(36) NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    "principalType"     VARCHAR(10) NOT NULL CHECK ("principalType" IN ('group', 'user')),
    "principalId"       VARCHAR(36) NOT NULL,
    permission          VARCHAR(10) NOT NULL DEFAULT 'read' CHECK (permission IN ('read', 'write')),
    "grantedById"       VARCHAR(36) NOT NULL REFERENCES "user"(id),
    "grantedAt"         TIMESTAMP   NOT NULL DEFAULT NOW(),
    UNIQUE ("knowledgeBaseId", "principalType", "principalId")
);

CREATE INDEX IF NOT EXISTS idx_kb_share_principal
    ON knowledge_base_share("principalType", "principalId");
CREATE INDEX IF NOT EXISTS idx_kb_share_kb
    ON knowledge_base_share("knowledgeBaseId");

-- ============================================================================
-- 5. Helper: parse the comma-separated app.current_user_groups GUC into UUIDs
-- ============================================================================
-- We stash the user's AD group GUIDs in a single GUC because postgres
-- session variables can't directly hold arrays. Defaults to empty array
-- when unset (logged-out / system context) so RLS still works.
CREATE OR REPLACE FUNCTION app_current_user_groups()
RETURNS TEXT[] AS $$
BEGIN
    RETURN string_to_array(
        NULLIF(current_setting('app.current_user_groups', true), ''),
        ','
    );
EXCEPTION WHEN OTHERS THEN
    RETURN ARRAY[]::TEXT[];
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- 6. Enable RLS on the new tables themselves
-- ============================================================================

-- ad_group: any signed-in user can read (so dropdowns and chips can resolve
-- group display names); only admins / the app should write.
ALTER TABLE ad_group ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ad_group_select_policy   ON ad_group;
DROP POLICY IF EXISTS ad_group_insert_policy   ON ad_group;
DROP POLICY IF EXISTS ad_group_modify_policy   ON ad_group;
DROP POLICY IF EXISTS ad_group_delete_policy   ON ad_group;

CREATE POLICY ad_group_select_policy ON ad_group
    FOR SELECT USING (true);

CREATE POLICY ad_group_insert_policy ON ad_group
    FOR INSERT WITH CHECK (true);

CREATE POLICY ad_group_modify_policy ON ad_group
    FOR UPDATE USING (true);

CREATE POLICY ad_group_delete_policy ON ad_group
    FOR DELETE USING (
        EXISTS (
            SELECT 1 FROM "user" u
            WHERE u.id = current_setting('app.current_user_id', true)
              AND u."roleSlug" LIKE '%admin%'
        )
    );

-- user_group: a user can only see their own membership rows.
ALTER TABLE user_group ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_group_select_policy ON user_group;
DROP POLICY IF EXISTS user_group_insert_policy ON user_group;
DROP POLICY IF EXISTS user_group_modify_policy ON user_group;
DROP POLICY IF EXISTS user_group_delete_policy ON user_group;

CREATE POLICY user_group_select_policy ON user_group
    FOR SELECT USING (
        "userId"::text = current_setting('app.current_user_id', true)
        OR EXISTS (
            SELECT 1 FROM "user" u
            WHERE u.id = current_setting('app.current_user_id', true)
              AND u."roleSlug" LIKE '%admin%'
        )
    );

CREATE POLICY user_group_insert_policy ON user_group
    FOR INSERT WITH CHECK (true);

CREATE POLICY user_group_modify_policy ON user_group
    FOR UPDATE USING (true);

CREATE POLICY user_group_delete_policy ON user_group
    FOR DELETE USING (true);

-- ms_oauth_token: refresh tokens are highly sensitive — strictly owner-only.
-- We deliberately DO NOT include the usual "admins see everything" carve-out
-- so an admin can never act *as* another user via Graph. FORCE RLS so even
-- the table owner role is subject to it.
ALTER TABLE ms_oauth_token ENABLE ROW LEVEL SECURITY;
ALTER TABLE ms_oauth_token FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ms_oauth_token_select_policy ON ms_oauth_token;
DROP POLICY IF EXISTS ms_oauth_token_insert_policy ON ms_oauth_token;
DROP POLICY IF EXISTS ms_oauth_token_modify_policy ON ms_oauth_token;
DROP POLICY IF EXISTS ms_oauth_token_delete_policy ON ms_oauth_token;

CREATE POLICY ms_oauth_token_select_policy ON ms_oauth_token
    FOR SELECT USING (
        "userId"::text = current_setting('app.current_user_id', true)
    );

CREATE POLICY ms_oauth_token_insert_policy ON ms_oauth_token
    FOR INSERT WITH CHECK (
        "userId"::text = current_setting('app.current_user_id', true)
    );

CREATE POLICY ms_oauth_token_modify_policy ON ms_oauth_token
    FOR UPDATE USING (
        "userId"::text = current_setting('app.current_user_id', true)
    );

CREATE POLICY ms_oauth_token_delete_policy ON ms_oauth_token
    FOR DELETE USING (
        "userId"::text = current_setting('app.current_user_id', true)
    );

-- workflow_share: visible to the resource owner, the share's grantee, or admins.
ALTER TABLE workflow_share ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS workflow_share_select_policy ON workflow_share;
DROP POLICY IF EXISTS workflow_share_insert_policy ON workflow_share;
DROP POLICY IF EXISTS workflow_share_modify_policy ON workflow_share;
DROP POLICY IF EXISTS workflow_share_delete_policy ON workflow_share;

CREATE POLICY workflow_share_select_policy ON workflow_share
    FOR SELECT USING (
        -- The share's grantor / workflow owner can always see it
        EXISTS (
            SELECT 1 FROM workflow_entity w
            WHERE w.id = workflow_share."workflowId"
              AND w."createdById"::text = current_setting('app.current_user_id', true)
        )
        -- The grantee (user) can see grants targeting them
        OR ("principalType" = 'user'
            AND "principalId" = current_setting('app.current_user_id', true))
        -- Members of a granted group can see grants for that group
        OR ("principalType" = 'group'
            AND "principalId" = ANY(app_current_user_groups()))
        -- Admins see everything
        OR EXISTS (
            SELECT 1 FROM "user" u
            WHERE u.id = current_setting('app.current_user_id', true)
              AND u."roleSlug" LIKE '%admin%'
        )
    );

-- Only the workflow owner can grant / revoke shares.
CREATE POLICY workflow_share_insert_policy ON workflow_share
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM workflow_entity w
            WHERE w.id = workflow_share."workflowId"
              AND w."createdById"::text = current_setting('app.current_user_id', true)
        )
    );

CREATE POLICY workflow_share_modify_policy ON workflow_share
    FOR UPDATE USING (
        EXISTS (
            SELECT 1 FROM workflow_entity w
            WHERE w.id = workflow_share."workflowId"
              AND w."createdById"::text = current_setting('app.current_user_id', true)
        )
    );

CREATE POLICY workflow_share_delete_policy ON workflow_share
    FOR DELETE USING (
        EXISTS (
            SELECT 1 FROM workflow_entity w
            WHERE w.id = workflow_share."workflowId"
              AND w."createdById"::text = current_setting('app.current_user_id', true)
        )
    );

-- knowledge_base_share: same shape as workflow_share.
ALTER TABLE knowledge_base_share ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS kb_share_select_policy ON knowledge_base_share;
DROP POLICY IF EXISTS kb_share_insert_policy ON knowledge_base_share;
DROP POLICY IF EXISTS kb_share_modify_policy ON knowledge_base_share;
DROP POLICY IF EXISTS kb_share_delete_policy ON knowledge_base_share;

CREATE POLICY kb_share_select_policy ON knowledge_base_share
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM knowledge_base kb
            WHERE kb.id = knowledge_base_share."knowledgeBaseId"
              AND kb."createdBy"::text = current_setting('app.current_user_id', true)
        )
        OR ("principalType" = 'user'
            AND "principalId" = current_setting('app.current_user_id', true))
        OR ("principalType" = 'group'
            AND "principalId" = ANY(app_current_user_groups()))
        OR EXISTS (
            SELECT 1 FROM "user" u
            WHERE u.id = current_setting('app.current_user_id', true)
              AND u."roleSlug" LIKE '%admin%'
        )
    );

CREATE POLICY kb_share_insert_policy ON knowledge_base_share
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM knowledge_base kb
            WHERE kb.id = knowledge_base_share."knowledgeBaseId"
              AND kb."createdBy"::text = current_setting('app.current_user_id', true)
        )
    );

CREATE POLICY kb_share_modify_policy ON knowledge_base_share
    FOR UPDATE USING (
        EXISTS (
            SELECT 1 FROM knowledge_base kb
            WHERE kb.id = knowledge_base_share."knowledgeBaseId"
              AND kb."createdBy"::text = current_setting('app.current_user_id', true)
        )
    );

CREATE POLICY kb_share_delete_policy ON knowledge_base_share
    FOR DELETE USING (
        EXISTS (
            SELECT 1 FROM knowledge_base kb
            WHERE kb.id = knowledge_base_share."knowledgeBaseId"
              AND kb."createdBy"::text = current_setting('app.current_user_id', true)
        )
    );

-- ============================================================================
-- 7. Rewrite RLS on workflow_entity to admit owner / public / shares
-- ============================================================================
ALTER TABLE workflow_entity ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_isolation_policy ON workflow_entity;
DROP POLICY IF EXISTS user_insert_policy    ON workflow_entity;
DROP POLICY IF EXISTS user_modify_policy    ON workflow_entity;
DROP POLICY IF EXISTS user_delete_policy    ON workflow_entity;

-- SELECT: owner OR isPublic OR a matching share row for me / one of my groups
CREATE POLICY user_isolation_policy ON workflow_entity
    FOR SELECT USING (
        "createdById"::text = current_setting('app.current_user_id', true)
        OR "isPublic" = true
        OR EXISTS (
            SELECT 1 FROM workflow_share ws
            WHERE ws."workflowId" = workflow_entity.id
              AND (
                  (ws."principalType" = 'user'
                   AND ws."principalId" = current_setting('app.current_user_id', true))
                  OR
                  (ws."principalType" = 'group'
                   AND ws."principalId" = ANY(app_current_user_groups()))
              )
        )
    );

CREATE POLICY user_insert_policy ON workflow_entity
    FOR INSERT WITH CHECK (true);

-- UPDATE: owner only, OR a 'write' share that targets me / one of my groups
CREATE POLICY user_modify_policy ON workflow_entity
    FOR UPDATE USING (
        "createdById"::text = current_setting('app.current_user_id', true)
        OR EXISTS (
            SELECT 1 FROM workflow_share ws
            WHERE ws."workflowId" = workflow_entity.id
              AND ws.permission = 'write'
              AND (
                  (ws."principalType" = 'user'
                   AND ws."principalId" = current_setting('app.current_user_id', true))
                  OR
                  (ws."principalType" = 'group'
                   AND ws."principalId" = ANY(app_current_user_groups()))
              )
        )
    );

-- DELETE: owner only.
CREATE POLICY user_delete_policy ON workflow_entity
    FOR DELETE USING (
        "createdById"::text = current_setting('app.current_user_id', true)
    );

-- ============================================================================
-- 8. Rewrite RLS on knowledge_base to admit owner / public / shares
-- ============================================================================
ALTER TABLE knowledge_base ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_isolation_policy ON knowledge_base;
DROP POLICY IF EXISTS user_insert_policy    ON knowledge_base;
DROP POLICY IF EXISTS user_modify_policy    ON knowledge_base;
DROP POLICY IF EXISTS user_delete_policy    ON knowledge_base;

CREATE POLICY user_isolation_policy ON knowledge_base
    FOR SELECT USING (
        "createdBy"::text = current_setting('app.current_user_id', true)
        OR "isPublic" = true
        OR EXISTS (
            SELECT 1 FROM knowledge_base_share kbs
            WHERE kbs."knowledgeBaseId" = knowledge_base.id
              AND (
                  (kbs."principalType" = 'user'
                   AND kbs."principalId" = current_setting('app.current_user_id', true))
                  OR
                  (kbs."principalType" = 'group'
                   AND kbs."principalId" = ANY(app_current_user_groups()))
              )
        )
    );

CREATE POLICY user_insert_policy ON knowledge_base
    FOR INSERT WITH CHECK (true);

CREATE POLICY user_modify_policy ON knowledge_base
    FOR UPDATE USING (
        "createdBy"::text = current_setting('app.current_user_id', true)
        OR EXISTS (
            SELECT 1 FROM knowledge_base_share kbs
            WHERE kbs."knowledgeBaseId" = knowledge_base.id
              AND kbs.permission = 'write'
              AND (
                  (kbs."principalType" = 'user'
                   AND kbs."principalId" = current_setting('app.current_user_id', true))
                  OR
                  (kbs."principalType" = 'group'
                   AND kbs."principalId" = ANY(app_current_user_groups()))
              )
        )
    );

CREATE POLICY user_delete_policy ON knowledge_base
    FOR DELETE USING (
        "createdBy"::text = current_setting('app.current_user_id', true)
    );

-- ============================================================================
-- 9. rag_document: also admit docs that belong to a KB the user has access to
-- ============================================================================
-- Existing public_kb_document_policy already admits docs from isPublic KBs.
-- Add a sister policy for KB shares.
ALTER TABLE rag_document ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS shared_kb_document_policy ON rag_document;

CREATE POLICY shared_kb_document_policy ON rag_document
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM knowledge_base_share kbs
            WHERE kbs."knowledgeBaseId" = rag_document."kbId"
              AND (
                  (kbs."principalType" = 'user'
                   AND kbs."principalId" = current_setting('app.current_user_id', true))
                  OR
                  (kbs."principalType" = 'group'
                   AND kbs."principalId" = ANY(app_current_user_groups()))
              )
        )
    );

-- ============================================================================
-- 10. Verify
-- ============================================================================
SELECT
    tablename,
    policyname,
    cmd
FROM pg_policies
WHERE tablename IN (
    'workflow_entity',
    'knowledge_base',
    'rag_document',
    'workflow_share',
    'knowledge_base_share',
    'ad_group',
    'user_group',
    'ms_oauth_token'
)
ORDER BY tablename, policyname;

SELECT 'AD groups + sharing migration completed successfully!' AS status;
