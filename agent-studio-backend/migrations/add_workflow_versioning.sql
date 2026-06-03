-- Migration: Workflow Versioning
-- Creates the workflow_history table and adds version-pinning column to chat_session.

-- 1. Create the workflow_history table
CREATE TABLE IF NOT EXISTS workflow_history (
    "versionId"            VARCHAR(36) PRIMARY KEY,
    "workflowId"           VARCHAR(36) NOT NULL REFERENCES workflow_entity(id) ON DELETE CASCADE,
    "versionNumber"        INTEGER NOT NULL,
    authors                VARCHAR(255) NOT NULL,
    nodes                  TEXT NOT NULL,
    connections            TEXT NOT NULL,
    settings               TEXT,
    description            TEXT,
    "isPublishedSnapshot"  BOOLEAN NOT NULL DEFAULT FALSE,
    event                  VARCHAR(50) NOT NULL,
    "createdAt"            TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wh_workflow_version   ON workflow_history ("workflowId", "versionNumber");
CREATE INDEX IF NOT EXISTS idx_wh_workflow_published ON workflow_history ("workflowId", "isPublishedSnapshot");
CREATE INDEX IF NOT EXISTS idx_wh_workflow_created   ON workflow_history ("workflowId", "createdAt");

-- 2. Add version-pinning column to chat_session
ALTER TABLE chat_session ADD COLUMN IF NOT EXISTS "workflowVersionId" VARCHAR(36);

-- 3. Grant permissions to app user (same pattern as other migrations)
GRANT ALL PRIVILEGES ON workflow_history TO app;
