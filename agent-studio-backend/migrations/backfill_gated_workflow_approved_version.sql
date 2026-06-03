-- Backfill approvedVersionId for workflows already shared via AD groups or 16+ users.
-- Safe to re-run.

UPDATE workflow_entity w
SET "approvedVersionId" = w."versionId",
    "updatedAt" = NOW()
WHERE w."versionId" IS NOT NULL
  AND (w."approvedVersionId" IS NULL OR w."approvedVersionId" = '')
  AND (
    EXISTS (
      SELECT 1 FROM workflow_share ws
      WHERE ws."workflowId" = w.id
        AND ws."principalType" = 'group'
    )
    OR (
      SELECT COUNT(*) FROM workflow_share ws
      WHERE ws."workflowId" = w.id
        AND ws."principalType" = 'user'
    ) >= 16
  );
