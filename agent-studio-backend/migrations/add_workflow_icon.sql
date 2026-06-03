-- Add icon column to workflow_entity.
-- Stores the blob path of an uploaded image chosen by the user to
-- visually identify the workflow in the builder, storefront, sessions,
-- and "my tools" views.  One icon per workflow (shared across versions).

ALTER TABLE workflow_entity
  ADD COLUMN IF NOT EXISTS "icon" VARCHAR(512);
