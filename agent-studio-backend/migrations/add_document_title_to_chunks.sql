-- Migration: Add document_title column to existing chunk tables for enhanced BM25 search
-- This allows BM25 to match on document filenames (e.g., "Food_volume_estimation")

-- To apply to ALL existing KB chunk tables, run this script:
DO $$
DECLARE
    kb_record RECORD;
    doc_record RECORD;
BEGIN
    -- Loop through all knowledge bases
    FOR kb_record IN 
        SELECT id, "chunkTableName" FROM knowledge_base WHERE "deletedAt" IS NULL
    LOOP
        RAISE NOTICE 'Processing KB: % (table: %)', kb_record.id, kb_record."chunkTableName";
        
        -- Add document_title column if not exists
        EXECUTE format('
            ALTER TABLE %I 
            ADD COLUMN IF NOT EXISTS document_title TEXT
        ', kb_record."chunkTableName");
        
        RAISE NOTICE '  ✅ Added document_title column';
        
        -- Populate document_title from document table for existing chunks
        EXECUTE format('
            UPDATE %I c
            SET document_title = d."fileName"
            FROM rag_document d
            WHERE c.document_id = d.id
                AND c.document_title IS NULL
        ', kb_record."chunkTableName");
        
        RAISE NOTICE '  ✅ Populated document_title from existing documents';
        
        -- Drop and recreate tsvector column to include document_title
        EXECUTE format('
            ALTER TABLE %I 
            DROP COLUMN IF EXISTS chunk_text_tsv CASCADE
        ', kb_record."chunkTableName");
        
        EXECUTE format('
            ALTER TABLE %I 
            ADD COLUMN chunk_text_tsv tsvector 
            GENERATED ALWAYS AS (
                to_tsvector(''english'', COALESCE(document_title, '''') || '' '' || chunk_text)
            ) STORED
        ', kb_record."chunkTableName");
        
        RAISE NOTICE '  ✅ Recreated tsvector to include document_title';
        
        -- Recreate GIN index
        EXECUTE format('
            CREATE INDEX IF NOT EXISTS idx_%I_tsv 
            ON %I USING GIN (chunk_text_tsv)
        ', kb_record."chunkTableName", kb_record."chunkTableName");
        
        RAISE NOTICE '  ✅ Recreated GIN index';
        RAISE NOTICE '  ══════════════════════════════════════════════';
    END LOOP;
    
    RAISE NOTICE '🎉 Migration complete! All KB tables now include document titles in BM25 search.';
END $$;

