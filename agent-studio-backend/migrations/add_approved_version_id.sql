-- Add approvedVersionId to workflow_entity.
-- This column tracks the last admin-approved version snapshot for marketplace
-- workflows. Marketplace endpoints serve data from this snapshot instead of
-- the live row, ensuring re-publishes require admin re-approval.

ALTER TABLE workflow_entity
  ADD COLUMN IF NOT EXISTS "approvedVersionId" VARCHAR(36);

-- Backfill: existing marketplace workflows already passed approval,
-- so seed approvedVersionId = versionId for workflows that are isPublic=true.
UPDATE workflow_entity
   SET "approvedVersionId" = "versionId"
 WHERE "isPublic" = true AND "versionId" IS NOT NULL;
