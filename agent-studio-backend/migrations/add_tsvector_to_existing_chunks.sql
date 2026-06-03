-- Migration: Add tsvector column to existing chunk tables for BM25 search
-- Run this for each existing KB chunk table

-- Example for a specific table (replace kb_XXXXX_chunks with your actual table name):
-- ALTER TABLE kb_d46b186d_chunks ADD COLUMN IF NOT EXISTS chunk_text_tsv tsvector 
--     GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED;
-- CREATE INDEX IF NOT EXISTS idx_kb_d46b186d_chunks_tsv ON kb_d46b186d_chunks USING GIN (chunk_text_tsv);

-- To apply to ALL existing KB chunk tables, use this script:
DO $$
DECLARE
    kb_record RECORD;
BEGIN
    -- Loop through all knowledge bases
    FOR kb_record IN 
        SELECT chunk_table_name FROM knowledge_base WHERE deleted_at IS NULL
    LOOP
        -- Add tsvector column if not exists
        EXECUTE format('
            ALTER TABLE %I 
            ADD COLUMN IF NOT EXISTS chunk_text_tsv tsvector 
            GENERATED ALWAYS AS (to_tsvector(''english'', chunk_text)) STORED
        ', kb_record.chunk_table_name);
        
        -- Create GIN index for full-text search
        EXECUTE format('
            CREATE INDEX IF NOT EXISTS idx_%I_tsv 
            ON %I USING GIN (chunk_text_tsv)
        ', kb_record.chunk_table_name, kb_record.chunk_table_name);
        
        RAISE NOTICE 'Added tsvector to table: %', kb_record.chunk_table_name;
    END LOOP;
END $$;

