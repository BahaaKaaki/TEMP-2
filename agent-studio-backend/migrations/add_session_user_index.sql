-- Migration: Add composite index on chat_session(userId, deletedAt)
-- Optimises the new GET /api/chat/my-sessions endpoint and the
-- RLS user_isolation_policy which filters on "userId".
-- Idempotent — safe to re-run.

CREATE INDEX IF NOT EXISTS idx_session_user_deleted
    ON chat_session ("userId", "deletedAt");
