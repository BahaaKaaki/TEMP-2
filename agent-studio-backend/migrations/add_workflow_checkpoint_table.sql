-- ============================================================================
-- Migration: Add Workflow Checkpoint Table (Revert-to-State Feature)
-- ============================================================================
-- Stores full session state snapshots before each user message, enabling
-- atomic revert to any previous point in the conversation.
--
-- Safe to re-run (all statements use IF NOT EXISTS / IF EXISTS checks).
--
-- Usage:  psql -h <host> -U <admin_user> -d <database> -f add_workflow_checkpoint_table.sql
-- ============================================================================

-- ============================================================================
-- 1. Create workflow_checkpoint table
-- ============================================================================
CREATE TABLE IF NOT EXISTS workflow_checkpoint (
    id VARCHAR(36) PRIMARY KEY NOT NULL,
    "sessionId" VARCHAR(36) NOT NULL,
    "executionId" INTEGER,

    -- The user message this checkpoint is "before"
    "userMessageId" VARCHAR(36) NOT NULL,
    "userMessageText" TEXT NOT NULL,
    "userMessageDisplay" TEXT,

    -- Full state snapshot
    "workflowState" TEXT NOT NULL,
    "executionStatus" VARCHAR(30),
    "deliverableSnapshots" TEXT NOT NULL DEFAULT '[]',

    -- Ordering and metadata
    "stepIndex" INTEGER NOT NULL,
    "sessionMessageCount" INTEGER NOT NULL DEFAULT 0,
    "userId" VARCHAR(36) NOT NULL,
    "createdAt" TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 2. Indexes for efficient querying
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_workflow_checkpoint_session
    ON workflow_checkpoint("sessionId");
CREATE INDEX IF NOT EXISTS idx_workflow_checkpoint_user
    ON workflow_checkpoint("userId");
CREATE INDEX IF NOT EXISTS idx_workflow_checkpoint_session_step
    ON workflow_checkpoint("sessionId", "stepIndex");

-- ============================================================================
-- 3. RLS policies for workflow_checkpoint
-- ============================================================================
ALTER TABLE workflow_checkpoint ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_checkpoint FORCE ROW LEVEL SECURITY;

-- Drop existing policies (safe to re-run)
DROP POLICY IF EXISTS checkpoint_user_select ON workflow_checkpoint;
DROP POLICY IF EXISTS checkpoint_user_insert ON workflow_checkpoint;
DROP POLICY IF EXISTS checkpoint_user_delete ON workflow_checkpoint;

-- SELECT: Users see only their own checkpoints
CREATE POLICY checkpoint_user_select ON workflow_checkpoint
    FOR SELECT
    USING ("userId" = current_setting('app.current_user_id', true));

-- INSERT: Any authenticated user can create checkpoints
CREATE POLICY checkpoint_user_insert ON workflow_checkpoint
    FOR INSERT
    WITH CHECK (true);

-- DELETE: Users can delete only their own checkpoints
CREATE POLICY checkpoint_user_delete ON workflow_checkpoint
    FOR DELETE
    USING ("userId" = current_setting('app.current_user_id', true));

-- ============================================================================
-- 4. Add reverted status support to execution_entity
-- ============================================================================
-- No schema change needed: the status column is VARCHAR and already accepts
-- arbitrary strings. We will use status='reverted' for soft-deleted executions.

-- ============================================================================
-- Done!
-- ============================================================================
SELECT 'workflow_checkpoint table created successfully!' AS status;
