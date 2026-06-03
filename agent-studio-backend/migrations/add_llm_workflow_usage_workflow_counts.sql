-- Workflow-level usage counts (in addition to per-node field reference counts)

ALTER TABLE llm_model_workflow_usage
    ADD COLUMN IF NOT EXISTS live_workflows INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS live_field_refs INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS published_workflows INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS published_snapshots INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS published_field_refs INTEGER NOT NULL DEFAULT 0;

-- Backfill field refs from legacy columns where present
UPDATE llm_model_workflow_usage
SET
    live_field_refs = live_occurrences,
    published_field_refs = published_occurrences
WHERE live_field_refs = 0 AND published_field_refs = 0
  AND (live_occurrences > 0 OR published_occurrences > 0);
