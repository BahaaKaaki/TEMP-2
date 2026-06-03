-- ============================================================================
-- Migration: Add structured data support tables for CSV/Excel KB uploads
-- ============================================================================
-- Creates metadata tables for tracking structured data tables and columns
-- within knowledge bases, and adds has_structured_data flag to knowledge_base.
-- Safe to re-run (uses IF NOT EXISTS checks).
--
-- Usage:  psql -h <host> -U <admin_user> -d <database> -f add_structured_data_tables.sql
-- ============================================================================

-- 1. Add has_structured_data column to knowledge_base
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'knowledge_base' AND column_name = 'hasStructuredData'
    ) THEN
        ALTER TABLE knowledge_base ADD COLUMN "hasStructuredData" BOOLEAN NOT NULL DEFAULT false;
        RAISE NOTICE 'Added hasStructuredData column to knowledge_base';
    ELSE
        RAISE NOTICE 'knowledge_base.hasStructuredData already exists';
    END IF;
END $$;

-- 2. Widen rag_document.status from VARCHAR(20) to VARCHAR(30) for 'pending_schema_review'
ALTER TABLE rag_document ALTER COLUMN status TYPE VARCHAR(30);

-- 3. Create structured_table metadata table
CREATE TABLE IF NOT EXISTS structured_table (
    id VARCHAR(36) PRIMARY KEY NOT NULL,
    kb_id VARCHAR(36) NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    document_id VARCHAR(36) NOT NULL REFERENCES rag_document(id) ON DELETE CASCADE,
    schema_name VARCHAR(128) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    row_count INTEGER NOT NULL DEFAULT 0,
    source_sheet VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'pending_review',
    created_by VARCHAR(36),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_structured_table_kb ON structured_table(kb_id);
CREATE INDEX IF NOT EXISTS idx_structured_table_doc ON structured_table(document_id);

-- 3. Create structured_column metadata table
CREATE TABLE IF NOT EXISTS structured_column (
    id VARCHAR(36) PRIMARY KEY NOT NULL,
    table_id VARCHAR(36) NOT NULL REFERENCES structured_table(id) ON DELETE CASCADE,
    column_name VARCHAR(128) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    data_type VARCHAR(20) NOT NULL DEFAULT 'text',
    description TEXT,
    column_order INTEGER NOT NULL DEFAULT 0,
    nullable BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_structured_column_table ON structured_column(table_id);

-- 4. Create structured_relationship table for FK links between tables
CREATE TABLE IF NOT EXISTS structured_relationship (
    id                VARCHAR(36) PRIMARY KEY NOT NULL,
    kb_id             VARCHAR(36) NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    source_table_id   VARCHAR(36) NOT NULL REFERENCES structured_table(id) ON DELETE CASCADE,
    source_column_id  VARCHAR(36) NOT NULL REFERENCES structured_column(id) ON DELETE CASCADE,
    target_table_id   VARCHAR(36) NOT NULL REFERENCES structured_table(id) ON DELETE CASCADE,
    target_column_id  VARCHAR(36) NOT NULL REFERENCES structured_column(id) ON DELETE CASCADE,
    relationship_type VARCHAR(20) NOT NULL DEFAULT 'one_to_many',
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_relationship_columns UNIQUE (source_column_id, target_column_id),
    CONSTRAINT chk_different_tables CHECK (source_table_id != target_table_id)
);

CREATE INDEX IF NOT EXISTS idx_structured_rel_kb ON structured_relationship(kb_id);

DO $$
BEGIN
    RAISE NOTICE 'Structured data tables migration complete';
END $$;
