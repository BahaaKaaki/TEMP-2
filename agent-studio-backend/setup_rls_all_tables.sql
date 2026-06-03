-- Row-Level Security policies for all user-specific tables
-- This script must be run as the table owner (sa) to enable RLS
-- Run this after all services have been updated to use get_db_with_user_context

-- ============================================================================
-- KNOWLEDGE_BASE TABLE
-- ============================================================================

ALTER TABLE knowledge_base ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_isolation_policy ON knowledge_base;
DROP POLICY IF EXISTS user_insert_policy ON knowledge_base;
DROP POLICY IF EXISTS user_modify_policy ON knowledge_base;
DROP POLICY IF EXISTS user_delete_policy ON knowledge_base;

CREATE POLICY user_isolation_policy ON knowledge_base
FOR SELECT USING ("createdBy"::text = current_setting('app.current_user_id', true));

CREATE POLICY user_insert_policy ON knowledge_base
FOR INSERT WITH CHECK (true);

CREATE POLICY user_modify_policy ON knowledge_base
FOR UPDATE USING ("createdBy"::text = current_setting('app.current_user_id', true));

CREATE POLICY user_delete_policy ON knowledge_base
FOR DELETE USING ("createdBy"::text = current_setting('app.current_user_id', true));

-- ============================================================================
-- RAG_DOCUMENT TABLE
-- ============================================================================

ALTER TABLE rag_document ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_isolation_policy ON rag_document;
DROP POLICY IF EXISTS user_insert_policy ON rag_document;
DROP POLICY IF EXISTS user_modify_policy ON rag_document;
DROP POLICY IF EXISTS user_delete_policy ON rag_document;

CREATE POLICY user_isolation_policy ON rag_document
FOR SELECT USING ("uploadedBy"::text = current_setting('app.current_user_id', true));

CREATE POLICY user_insert_policy ON rag_document
FOR INSERT WITH CHECK (true);

CREATE POLICY user_modify_policy ON rag_document
FOR UPDATE USING ("uploadedBy"::text = current_setting('app.current_user_id', true));

CREATE POLICY user_delete_policy ON rag_document
FOR DELETE USING ("uploadedBy"::text = current_setting('app.current_user_id', true));

-- ============================================================================
-- EXECUTION_ENTITY TABLE
-- ============================================================================

ALTER TABLE execution_entity ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_isolation_policy ON execution_entity;
DROP POLICY IF EXISTS user_insert_policy ON execution_entity;
DROP POLICY IF EXISTS user_modify_policy ON execution_entity;
DROP POLICY IF EXISTS user_delete_policy ON execution_entity;

CREATE POLICY user_isolation_policy ON execution_entity
FOR SELECT USING ("triggeredById"::text = current_setting('app.current_user_id', true));

CREATE POLICY user_insert_policy ON execution_entity
FOR INSERT WITH CHECK (true);

CREATE POLICY user_modify_policy ON execution_entity
FOR UPDATE USING ("triggeredById"::text = current_setting('app.current_user_id', true));

CREATE POLICY user_delete_policy ON execution_entity
FOR DELETE USING ("triggeredById"::text = current_setting('app.current_user_id', true));

-- ============================================================================
-- CHAT_SESSION TABLE
-- ============================================================================

ALTER TABLE chat_session ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_isolation_policy ON chat_session;
DROP POLICY IF EXISTS user_insert_policy ON chat_session;
DROP POLICY IF EXISTS user_modify_policy ON chat_session;
DROP POLICY IF EXISTS user_delete_policy ON chat_session;

CREATE POLICY user_isolation_policy ON chat_session
FOR SELECT USING ("userId"::text = current_setting('app.current_user_id', true));

CREATE POLICY user_insert_policy ON chat_session
FOR INSERT WITH CHECK (true);

CREATE POLICY user_modify_policy ON chat_session
FOR UPDATE USING ("userId"::text = current_setting('app.current_user_id', true));

CREATE POLICY user_delete_policy ON chat_session
FOR DELETE USING ("userId"::text = current_setting('app.current_user_id', true));

-- ============================================================================
-- AGENT_DELIVERABLE TABLE
-- ============================================================================

ALTER TABLE agent_deliverable ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_isolation_policy ON agent_deliverable;
DROP POLICY IF EXISTS user_insert_policy ON agent_deliverable;
DROP POLICY IF EXISTS user_modify_policy ON agent_deliverable;
DROP POLICY IF EXISTS user_delete_policy ON agent_deliverable;

CREATE POLICY user_isolation_policy ON agent_deliverable
FOR SELECT USING ("createdById"::text = current_setting('app.current_user_id', true));

CREATE POLICY user_insert_policy ON agent_deliverable
FOR INSERT WITH CHECK (true);

CREATE POLICY user_modify_policy ON agent_deliverable
FOR UPDATE USING ("createdById"::text = current_setting('app.current_user_id', true));

CREATE POLICY user_delete_policy ON agent_deliverable
FOR DELETE USING ("createdById"::text = current_setting('app.current_user_id', true));

-- ============================================================================
-- CHAT_FILE TABLE
-- ============================================================================

ALTER TABLE chat_file ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_isolation_policy ON chat_file;
DROP POLICY IF EXISTS user_insert_policy ON chat_file;
DROP POLICY IF EXISTS user_modify_policy ON chat_file;
DROP POLICY IF EXISTS user_delete_policy ON chat_file;

CREATE POLICY user_isolation_policy ON chat_file
FOR SELECT USING ("uploadedBy"::text = current_setting('app.current_user_id', true));

CREATE POLICY user_insert_policy ON chat_file
FOR INSERT WITH CHECK (true);

CREATE POLICY user_modify_policy ON chat_file
FOR UPDATE USING ("uploadedBy"::text = current_setting('app.current_user_id', true));

CREATE POLICY user_delete_policy ON chat_file
FOR DELETE USING ("uploadedBy"::text = current_setting('app.current_user_id', true));

-- ============================================================================
-- VERIFY ALL POLICIES
-- ============================================================================

SELECT 
    tablename,
    policyname,
    cmd,
    qual,
    with_check
FROM pg_policies
WHERE tablename IN (
    'workflow_entity',
    'knowledge_base',
    'rag_document',
    'execution_entity',
    'chat_session',
    'agent_deliverable',
    'chat_file'
)
ORDER BY tablename, policyname;
