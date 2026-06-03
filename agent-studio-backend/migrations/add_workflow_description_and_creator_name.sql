-- Migration: Add description and createdByName columns to workflow_entity table
-- Date: 2026-01-20
-- Description: Adds description field for workflows and createdByName for displaying creator info

-- Add description column
ALTER TABLE workflow_entity 
ADD COLUMN IF NOT EXISTS description VARCHAR(512);

-- Add createdByName column
ALTER TABLE workflow_entity 
ADD COLUMN IF NOT EXISTS "createdByName" VARCHAR(128);

-- Populate createdByName with existing user data
UPDATE workflow_entity w
SET "createdByName" = COALESCE(
    NULLIF(CONCAT(u."firstName", ' ', u."lastName"), ' '),
    u.email
)
FROM "user" u
WHERE w."createdById" = u.id
AND w."createdByName" IS NULL;

-- Add comment to columns
COMMENT ON COLUMN workflow_entity.description IS 'Workflow description text';
COMMENT ON COLUMN workflow_entity."createdByName" IS 'Name of user who created this workflow';
