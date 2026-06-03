-- Migration: add project table and projectId FK on chat_session
-- Projects let users organise chat sessions into named groups.
-- Each project is personal (scoped to userId via RLS).

CREATE TABLE IF NOT EXISTS project (
    id              VARCHAR(36)   PRIMARY KEY,
    name            VARCHAR(255)  NOT NULL,
    description     VARCHAR(512),
    "userId"        VARCHAR(36)   NOT NULL REFERENCES "user"(id),
    "createdAt"     TIMESTAMP     NOT NULL DEFAULT NOW(),
    "updatedAt"     TIMESTAMP     NOT NULL DEFAULT NOW(),
    "isArchived"    BOOLEAN       NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_project_user
    ON project ("userId");

-- Nullable FK so sessions can exist without a project.
-- ON DELETE SET NULL ensures deleting a project unassigns its sessions.
ALTER TABLE chat_session
    ADD COLUMN IF NOT EXISTS "projectId" VARCHAR(36)
    REFERENCES project(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_session_project
    ON chat_session ("projectId");

-- RLS: users only see their own projects
ALTER TABLE project ENABLE ROW LEVEL SECURITY;
ALTER TABLE project FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_isolation_policy ON project;
CREATE POLICY user_isolation_policy ON project
    FOR SELECT
    USING ("userId"::text = current_setting('app.current_user_id', true));

DROP POLICY IF EXISTS user_insert_policy ON project;
CREATE POLICY user_insert_policy ON project
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS user_modify_policy ON project;
CREATE POLICY user_modify_policy ON project
    FOR UPDATE
    USING (true);

DROP POLICY IF EXISTS user_delete_policy ON project;
CREATE POLICY user_delete_policy ON project
    FOR DELETE
    USING (true);

-- Grant to app role
DO $$
BEGIN
    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON project TO %I',
        current_setting('app.migration_app_user', true)
    );
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Could not grant on project: %', SQLERRM;
END $$;
