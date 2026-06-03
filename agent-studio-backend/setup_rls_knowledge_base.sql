-- Row-Level Security policies for knowledge_base table
-- This script must be run as the table owner (sa) to enable RLS

-- Enable RLS on knowledge_base table
ALTER TABLE knowledge_base ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if any
DROP POLICY IF EXISTS user_isolation_policy ON knowledge_base;
DROP POLICY IF EXISTS user_insert_policy ON knowledge_base;
DROP POLICY IF EXISTS user_modify_policy ON knowledge_base;
DROP POLICY IF EXISTS user_delete_policy ON knowledge_base;

-- Create SELECT policy: Users can only see their own knowledge bases
CREATE POLICY user_isolation_policy ON knowledge_base
FOR SELECT
USING ("createdBy"::text = current_setting('app.current_user_id', true));

-- Create INSERT policy: Allow users to create knowledge bases (createdBy will be set by application)
CREATE POLICY user_insert_policy ON knowledge_base
FOR INSERT
WITH CHECK (true);

-- Create UPDATE policy: Users can only modify their own knowledge bases
CREATE POLICY user_modify_policy ON knowledge_base
FOR UPDATE
USING ("createdBy"::text = current_setting('app.current_user_id', true));

-- Create DELETE policy: Users can only delete their own knowledge bases
CREATE POLICY user_delete_policy ON knowledge_base
FOR DELETE
USING ("createdBy"::text = current_setting('app.current_user_id', true));

-- Verify policies were created
SELECT schemaname, tablename, policyname, cmd, qual, with_check
FROM pg_policies
WHERE tablename = 'knowledge_base'
ORDER BY policyname;
