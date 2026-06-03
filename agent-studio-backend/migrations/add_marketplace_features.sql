-- ============================================================================
-- Migration: Add Marketplace & Approval Features
-- ============================================================================
-- Run this on any new environment to add marketplace submission/approval support.
-- Safe to re-run (all statements use IF NOT EXISTS / IF EXISTS checks).
--
-- Usage:  psql -h <host> -U <admin_user> -d <database> -f add_marketplace_features.sql
-- ============================================================================

-- ============================================================================
-- 1. Add marketplace columns to workflow_entity (if missing)
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'workflow_entity' AND column_name = 'isPublic'
    ) THEN
        ALTER TABLE workflow_entity ADD COLUMN "isPublic" BOOLEAN NOT NULL DEFAULT FALSE;
        RAISE NOTICE 'Added isPublic column to workflow_entity';
    ELSE
        RAISE NOTICE 'workflow_entity.isPublic already exists';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'workflow_entity' AND column_name = 'marketplaceName'
    ) THEN
        ALTER TABLE workflow_entity ADD COLUMN "marketplaceName" VARCHAR(255);
        RAISE NOTICE 'Added marketplaceName column to workflow_entity';
    ELSE
        RAISE NOTICE 'workflow_entity.marketplaceName already exists';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'workflow_entity' AND column_name = 'marketplaceDescription'
    ) THEN
        ALTER TABLE workflow_entity ADD COLUMN "marketplaceDescription" TEXT;
        RAISE NOTICE 'Added marketplaceDescription column to workflow_entity';
    ELSE
        RAISE NOTICE 'workflow_entity.marketplaceDescription already exists';
    END IF;
END $$;

-- ============================================================================
-- 2. Add marketplace columns to knowledge_base (if missing)
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'knowledge_base' AND column_name = 'isPublic'
    ) THEN
        ALTER TABLE knowledge_base ADD COLUMN "isPublic" BOOLEAN NOT NULL DEFAULT FALSE;
        RAISE NOTICE 'Added isPublic column to knowledge_base';
    ELSE
        RAISE NOTICE 'knowledge_base.isPublic already exists';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'knowledge_base' AND column_name = 'marketplaceName'
    ) THEN
        ALTER TABLE knowledge_base ADD COLUMN "marketplaceName" VARCHAR(255);
        RAISE NOTICE 'Added marketplaceName column to knowledge_base';
    ELSE
        RAISE NOTICE 'knowledge_base.marketplaceName already exists';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'knowledge_base' AND column_name = 'marketplaceDescription'
    ) THEN
        ALTER TABLE knowledge_base ADD COLUMN "marketplaceDescription" TEXT;
        RAISE NOTICE 'Added marketplaceDescription column to knowledge_base';
    ELSE
        RAISE NOTICE 'knowledge_base.marketplaceDescription already exists';
    END IF;
END $$;

-- ============================================================================
-- 3. Create marketplace_submission table (if not exists)
-- ============================================================================
CREATE TABLE IF NOT EXISTS marketplace_submission (
    id VARCHAR(36) PRIMARY KEY NOT NULL,
    "workflowId" VARCHAR(36) NOT NULL REFERENCES workflow_entity(id),
    "submittedById" VARCHAR(36) NOT NULL REFERENCES "user"(id),
    "marketplaceName" VARCHAR(255) NOT NULL,
    "marketplaceDescription" TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    "reviewedById" VARCHAR(36) REFERENCES "user"(id),
    "reviewedAt" TIMESTAMP,
    "rejectionReason" TEXT,
    "createdAt" TIMESTAMP NOT NULL DEFAULT NOW(),
    "updatedAt" TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_marketplace_submission_workflow 
    ON marketplace_submission("workflowId");
CREATE INDEX IF NOT EXISTS idx_marketplace_submission_submitter 
    ON marketplace_submission("submittedById");
CREATE INDEX IF NOT EXISTS idx_marketplace_submission_status 
    ON marketplace_submission(status);

-- ============================================================================
-- 4. RLS policies for marketplace_submission
-- ============================================================================
ALTER TABLE marketplace_submission ENABLE ROW LEVEL SECURITY;
ALTER TABLE marketplace_submission FORCE ROW LEVEL SECURITY;

-- Drop existing policies (safe to re-run)
DROP POLICY IF EXISTS user_isolation_policy ON marketplace_submission;
DROP POLICY IF EXISTS user_insert_policy ON marketplace_submission;
DROP POLICY IF EXISTS user_modify_policy ON marketplace_submission;
DROP POLICY IF EXISTS user_delete_policy ON marketplace_submission;
DROP POLICY IF EXISTS admin_view_all_submissions ON marketplace_submission;

-- SELECT: Users see their own submissions, admins see all
CREATE POLICY user_isolation_policy ON marketplace_submission
    FOR SELECT
    USING (
        "submittedById" = current_setting('app.current_user_id', true)
        OR EXISTS (
            SELECT 1 FROM "user" u 
            WHERE u.id = current_setting('app.current_user_id', true)
            AND u."roleSlug" LIKE '%admin%'
        )
    );

-- INSERT: Any authenticated user can submit
CREATE POLICY user_insert_policy ON marketplace_submission
    FOR INSERT
    WITH CHECK (true);

-- UPDATE: Users can update their own, admins can update all
CREATE POLICY user_modify_policy ON marketplace_submission
    FOR UPDATE
    USING (
        "submittedById" = current_setting('app.current_user_id', true)
        OR EXISTS (
            SELECT 1 FROM "user" u 
            WHERE u.id = current_setting('app.current_user_id', true)
            AND u."roleSlug" LIKE '%admin%'
        )
    );

-- DELETE: Only submitter can delete
CREATE POLICY user_delete_policy ON marketplace_submission
    FOR DELETE
    USING ("submittedById" = current_setting('app.current_user_id', true));

-- ============================================================================
-- 5. RLS policy for rag_document: allow viewing docs from public KBs
-- ============================================================================
DROP POLICY IF EXISTS public_kb_document_policy ON rag_document;
CREATE POLICY public_kb_document_policy ON rag_document
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM knowledge_base kb 
            WHERE kb.id = "kbId"
            AND kb."isPublic" = true
        )
    );

-- ============================================================================
-- 6. Make a user admin (uncomment and edit the email below)
-- ============================================================================
-- UPDATE "user" SET "roleSlug" = 'global:admin' WHERE email = 'admin@example.com';

-- ============================================================================
-- Done!
-- ============================================================================
SELECT 'Migration completed successfully!' AS status;
