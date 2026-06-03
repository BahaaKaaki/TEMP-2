-- KB owners can list documents uploaded by write-shared collaborators.
-- Safe to re-run (idempotent).

DROP POLICY IF EXISTS kb_owner_document_select_policy ON rag_document;

CREATE POLICY kb_owner_document_select_policy ON rag_document
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM knowledge_base kb
            WHERE kb.id = rag_document."kbId"
              AND kb."createdBy"::text = current_setting('app.current_user_id', true)
        )
    );

SELECT 'kb_owner_document_select_policy applied' AS status;
