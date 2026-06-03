-- Migration: Add isPinned and lastAccessedAt to workflow_entity, chat_session, knowledge_base
-- Supports pin-to-top and last-accessed-first ordering for user items.
-- All statements are idempotent (safe to re-run).

-- ============================================================================
-- 1. workflow_entity
-- ============================================================================

ALTER TABLE workflow_entity ADD COLUMN IF NOT EXISTS "isPinned" BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE workflow_entity ADD COLUMN IF NOT EXISTS "lastAccessedAt" TIMESTAMP NULL;

-- ============================================================================
-- 2. chat_session
-- ============================================================================

ALTER TABLE chat_session ADD COLUMN IF NOT EXISTS "isPinned" BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE chat_session ADD COLUMN IF NOT EXISTS "lastAccessedAt" TIMESTAMP NULL;

-- ============================================================================
-- 3. knowledge_base
-- ============================================================================

ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS "isPinned" BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS "lastAccessedAt" TIMESTAMP NULL;

-- ============================================================================
-- 4. Composite indexes for ORDER BY isPinned DESC, lastAccessedAt DESC
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_workflow_pin_accessed
    ON workflow_entity ("isPinned" DESC, "lastAccessedAt" DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_session_pin_accessed
    ON chat_session ("isPinned" DESC, "lastAccessedAt" DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_kb_pin_accessed
    ON knowledge_base ("isPinned" DESC, "lastAccessedAt" DESC NULLS LAST);
