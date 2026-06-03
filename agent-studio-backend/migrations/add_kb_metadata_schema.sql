-- ============================================================================
-- Migration: Add metadata schema column to knowledge_base table
-- ============================================================================
-- Adds the metadataSchema column that stores JSON-encoded metadata field
-- definitions (name, type, scope, description) for LLM-based inference.
-- Safe to re-run (uses IF NOT EXISTS checks).
--
-- Usage:  psql -h <host> -U <admin_user> -d <database> -f add_kb_metadata_schema.sql
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'knowledge_base' AND column_name = 'metadataSchema'
    ) THEN
        ALTER TABLE knowledge_base ADD COLUMN "metadataSchema" TEXT;
        RAISE NOTICE 'Added metadataSchema column to knowledge_base';
    ELSE
        RAISE NOTICE 'knowledge_base.metadataSchema already exists';
    END IF;
END $$;
