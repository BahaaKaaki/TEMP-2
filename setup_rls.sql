-- Enable RLS on workflow_entity
ALTER TABLE workflow_entity ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_entity FORCE ROW LEVEL SECURITY;

-- Drop existing policies
DROP POLICY IF EXISTS user_isolation_policy ON workflow_entity;
DROP POLICY IF EXISTS user_insert_policy ON workflow_entity;
DROP POLICY IF EXISTS user_modify_policy ON workflow_entity;
DROP POLICY IF EXISTS user_delete_policy ON workflow_entity;

-- CREATE SELECT POLICY: Users only see their own workflows
CREATE POLICY user_isolation_policy ON workflow_entity
FOR SELECT
USING ("createdById"::text = current_setting('app.current_user_id', true));

-- CREATE INSERT POLICY: Allow inserts (app sets correct createdById)
CREATE POLICY user_insert_policy ON workflow_entity
FOR INSERT
WITH CHECK (true);

-- CREATE UPDATE POLICY: Users can only update their own workflows
CREATE POLICY user_modify_policy ON workflow_entity
FOR UPDATE
USING ("createdById"::text = current_setting('app.current_user_id', true));

-- CREATE DELETE POLICY: Users can only delete their own workflows
CREATE POLICY user_delete_policy ON workflow_entity
FOR DELETE
USING ("createdById"::text = current_setting('app.current_user_id', true));

-- Verify policies were created
SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies
WHERE tablename = 'workflow_entity';
