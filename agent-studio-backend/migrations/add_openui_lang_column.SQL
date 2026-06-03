-- Stores a JSON array of per-section OpenUI Lang strings, index-aligned to the
-- deliverable's sections[]. NULL until the background pretranslation completes.
ALTER TABLE agent_deliverable
ADD COLUMN IF NOT EXISTS "openuiLang" TEXT;
