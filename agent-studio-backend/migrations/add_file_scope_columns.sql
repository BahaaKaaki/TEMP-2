-- Migration: Add per-agent file scope columns to chat_file table
-- Date: 2026-04-30
-- Description: Track which agent the user was talking to at upload time
--              and whether the file is visible only to that agent (local)
--              or to every agent in the workflow (global).

ALTER TABLE chat_file
ADD COLUMN IF NOT EXISTS "uploadedAtAgentId" VARCHAR(64),
ADD COLUMN IF NOT EXISTS "uploadedAtAgentLabel" VARCHAR(255),
ADD COLUMN IF NOT EXISTS "scope" VARCHAR(20) NOT NULL DEFAULT 'global';

-- Index the agent id for the local-files-by-agent query that runs on every chat send.
CREATE INDEX IF NOT EXISTS idx_chat_file_uploaded_at_agent_id
    ON chat_file ("uploadedAtAgentId");

-- Index scope so the global-files lookup at agent execution stays fast.
CREATE INDEX IF NOT EXISTS idx_chat_file_scope
    ON chat_file ("scope");

-- Backfill: existing rows have no agent stamp. Treat them as global so
-- nothing currently working changes (today's behaviour effectively makes
-- every file visible everywhere via the user-message glue path).
UPDATE chat_file
SET "scope" = 'global'
WHERE "scope" IS NULL;

COMMENT ON COLUMN chat_file."uploadedAtAgentId" IS
    'Workflow node id of the agent that was active when the user uploaded this file.';
COMMENT ON COLUMN chat_file."uploadedAtAgentLabel" IS
    'Human-readable label of the uploading agent at upload time (snapshot).';
COMMENT ON COLUMN chat_file."scope" IS
    'File visibility scope: ''local'' (only the uploading agent) or ''global'' (every agent).';
