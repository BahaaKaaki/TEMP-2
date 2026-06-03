"""
Database initialization - automatically sets up RLS policies on startup.

This module ensures Row-Level Security is properly configured every time
the application starts, eliminating the need for manual migration scripts.
"""
import logging
from contextlib import asynccontextmanager
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _safe_step(session: AsyncSession, label: str):
    """
    Run a block of DDL inside a PostgreSQL SAVEPOINT.

    Any failure inside the ``async with`` rolls back only the savepoint,
    leaving the surrounding transaction healthy so the *next* RLS step still
    runs. This prevents one bad permission/policy from poisoning the entire
    init flow (which previously cascaded into "current transaction is aborted"
    errors and left the database with no policies installed at all).

    Usage:
        async with _safe_step(session, "RLS for workflow_entity"):
            await session.execute(text("..."))
            await session.execute(text("..."))
    """
    try:
        async with session.begin_nested():
            yield
    except Exception as e:  # noqa: BLE001 - we deliberately swallow per-step errors
        # Truncate so a giant Postgres error doesn't drown the log
        logger.warning("  ⚠️  %s failed: %s", label, str(e)[:250])


async def init_database_security(session: AsyncSession):
    """
    Initialize database security features (RLS policies).
    
    Called automatically on application startup to ensure proper data isolation.
    Idempotent - safe to run multiple times.
    
    Strategy:
    - SELECT: Strict filtering by user_id (users only see their own data)
    - INSERT/UPDATE/DELETE: Allow operations (application controls ownership)
    """
    logger.info("🔒 Initializing database security (RLS policies)...")
    
    # Check PostgreSQL version
    try:
        version_result = await session.execute(text("SELECT version()"))
        pg_version = version_result.scalar()
        logger.info(f"  PostgreSQL version: {pg_version[:100]}")
    except Exception as e:
        logger.warning(f"  Could not get PG version: {e}")
    
    # Check database user privileges
    try:
        result = await session.execute(text("SELECT current_user"))
        db_user = result.scalar()
        logger.info(f"  Current database user: {db_user}")
        
        # Check if user is superuser or has BYPASSRLS
        check_result = await session.execute(text(f"""
            SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = '{db_user}';
        """))
        role_info = check_result.fetchone()
        if role_info:
            has_bypassrls, is_superuser = role_info
            logger.info(f"  User privileges: bypassrls={has_bypassrls}, superuser={is_superuser}")
            
            if is_superuser:
                logger.error(f"  ❌ CRITICAL: {db_user} is SUPERUSER - RLS will be bypassed!")
                logger.error(f"  ❌ Create non-superuser role in .env: POSTGRES_USER=app")
            elif has_bypassrls:
                logger.warning(f"  ⚠️  User has BYPASSRLS - attempting to remove...")
                # SAVEPOINT: if the app role can't ALTER itself, we don't want
                # that error to poison the outer transaction (which would then
                # abort every RLS step that follows).
                try:
                    async with session.begin_nested():
                        await session.execute(text(f"ALTER USER {db_user} NOBYPASSRLS;"))
                    logger.info(f"  ✅ Removed BYPASSRLS from {db_user}")
                except Exception as e:
                    logger.error(f"  ❌ Could not remove BYPASSRLS: {e}")
            else:
                logger.info(f"  ✅ User {db_user} is properly configured for RLS")
    except Exception as e:
        logger.error(f"  ⚠️  Could not check user privileges: {str(e)}")
    
    # Install the helper function that turns the comma-separated
    # `app.current_user_groups` GUC into a TEXT[] for RLS clauses.
    # Defined before the per-table loop because the workflow / KB policies
    # reference it directly.
    #
    # NOTE: If this function was previously created by an admin role (e.g. via
    # the migration SQL run in psql), the app role won't be able to
    # CREATE OR REPLACE it. That's OK — the body is identical, so we just
    # leave the existing definition in place and continue.
    function_existed = False
    try:
        async with session.begin_nested():
            check = await session.execute(text(
                "SELECT 1 FROM pg_proc WHERE proname = 'app_current_user_groups' LIMIT 1;"
            ))
            function_existed = check.scalar() is not None
    except Exception:
        # Failed to even check — assume not installed and let the CREATE attempt run
        pass

    try:
        async with session.begin_nested():
            await session.execute(text("""
                CREATE OR REPLACE FUNCTION app_current_user_groups()
                RETURNS TEXT[] AS $$
                BEGIN
                    RETURN string_to_array(
                        NULLIF(current_setting('app.current_user_groups', true), ''),
                        ','
                    );
                EXCEPTION WHEN OTHERS THEN
                    RETURN ARRAY[]::TEXT[];
                END;
                $$ LANGUAGE plpgsql STABLE;
            """))
        logger.info("  ✅ app_current_user_groups() helper function installed/refreshed")
    except Exception as e:
        # Most common cause: the function exists and is owned by a different
        # role (e.g. the admin role from a manual migration run). The body
        # is the same, so we don't need to replace it.
        if function_existed and 'must be owner' in str(e).lower():
            logger.info(
                "  ℹ️  app_current_user_groups() already exists (owned by another "
                "role) — keeping the existing definition. To take ownership, run "
                "as the owning role: DROP FUNCTION IF EXISTS app_current_user_groups();"
            )
        else:
            logger.warning(
                "  ⚠️  Failed to create app_current_user_groups(): %s",
                str(e)[:250],
            )

    # Tables whose RLS depends on share tables (workflow_share / knowledge_base_share).
    # We handle these out-of-loop because the standard "owner OR isPublic" template
    # in `table_configs` isn't expressive enough — they need an additional EXISTS
    # subquery against the share table.
    SHARE_AWARE_TABLES = {'workflow_entity', 'knowledge_base'}

    # Table configurations: (table_name, user_id_column, supports_public)
    # Tables with supports_public=True have isPublic column for marketplace sharing
    table_configs = [
        ('workflow_entity', '"createdById"', True),       # Supports public marketplace sharing + group/user shares
        ('execution_entity', '"triggeredById"', False),
        ('chat_session', '"userId"', False),
        ('agent_deliverable', '"createdById"', False),
        ('chat_file', '"uploadedBy"', False),
        ('knowledge_base', '"createdBy"', True),          # Supports public KB sharing + group/user shares
        ('rag_document', '"uploadedBy"', False),
        ('marketplace_submission', '"submittedById"', False),  # Approval submissions
        ('project', '"userId"', False),                   # Personal session grouping
    ]
    
    for table_name, user_col, supports_public in table_configs:
        async with _safe_step(session, f"RLS policies for {table_name}"):
            # Enable RLS on table
            await session.execute(text(
                f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;"
            ))

            # CRITICAL: Force RLS even for table owners
            await session.execute(text(
                f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;"
            ))

            # Drop existing policies (idempotent)
            await session.execute(text(
                f"DROP POLICY IF EXISTS user_isolation_policy ON {table_name};"
            ))
            await session.execute(text(
                f"DROP POLICY IF EXISTS user_insert_policy ON {table_name};"
            ))
            await session.execute(text(
                f"DROP POLICY IF EXISTS user_modify_policy ON {table_name};"
            ))
            await session.execute(text(
                f"DROP POLICY IF EXISTS user_delete_policy ON {table_name};"
            ))
            await session.execute(text(
                f"DROP POLICY IF EXISTS public_access_policy ON {table_name};"
            ))
            await session.execute(text(
                f"DROP POLICY IF EXISTS admin_access_policy ON {table_name};"
            ))

            # Pick the right (share_table, fk_column) for share-aware tables.
            share_table = None
            share_fk_col = None
            if table_name == 'workflow_entity':
                share_table = 'workflow_share'
                share_fk_col = '"workflowId"'
            elif table_name == 'knowledge_base':
                share_table = 'knowledge_base_share'
                share_fk_col = '"knowledgeBaseId"'

            # CREATE SELECT POLICY: owner OR public OR (for share-aware tables)
            # a matching share row for the current user / one of their AD groups.
            if table_name in SHARE_AWARE_TABLES:
                await session.execute(text(f"""
                    CREATE POLICY user_isolation_policy ON {table_name}
                    FOR SELECT
                    USING (
                        {user_col}::text = current_setting('app.current_user_id', true)
                        OR "isPublic" = true
                        OR EXISTS (
                            SELECT 1 FROM {share_table} sh
                            WHERE sh.{share_fk_col} = {table_name}.id
                              AND (
                                  (sh."principalType" = 'user'
                                   AND sh."principalId" = current_setting('app.current_user_id', true))
                                  OR
                                  (sh."principalType" = 'group'
                                   AND sh."principalId" = ANY(app_current_user_groups()))
                              )
                        )
                    );
                """))
            elif supports_public:
                # For tables with isPublic column but no sharing: user sees own data OR public data
                await session.execute(text(f"""
                    CREATE POLICY user_isolation_policy ON {table_name}
                    FOR SELECT
                    USING (
                        {user_col} = current_setting('app.current_user_id', true)
                        OR "isPublic" = true
                    );
                """))
            else:
                # Standard policy: users only see their own data
                await session.execute(text(f"""
                    CREATE POLICY user_isolation_policy ON {table_name}
                    FOR SELECT
                    USING ({user_col} = current_setting('app.current_user_id', true));
                """))

            # CREATE INSERT POLICY: Allow all authenticated users to insert
            # Application ensures the correct user_id is set
            await session.execute(text(f"""
                CREATE POLICY user_insert_policy ON {table_name}
                FOR INSERT
                WITH CHECK (true);
            """))

            # CREATE UPDATE POLICY: owner OR (for share-aware tables) a 'write' share
            # targeting the current user / one of their AD groups.
            if table_name in SHARE_AWARE_TABLES:
                await session.execute(text(f"""
                    CREATE POLICY user_modify_policy ON {table_name}
                    FOR UPDATE
                    USING (
                        {user_col}::text = current_setting('app.current_user_id', true)
                        OR EXISTS (
                            SELECT 1 FROM {share_table} sh
                            WHERE sh.{share_fk_col} = {table_name}.id
                              AND sh.permission = 'write'
                              AND (
                                  (sh."principalType" = 'user'
                                   AND sh."principalId" = current_setting('app.current_user_id', true))
                                  OR
                                  (sh."principalType" = 'group'
                                   AND sh."principalId" = ANY(app_current_user_groups()))
                              )
                        )
                    );
                """))
            else:
                await session.execute(text(f"""
                    CREATE POLICY user_modify_policy ON {table_name}
                    FOR UPDATE
                    USING ({user_col} = current_setting('app.current_user_id', true));
                """))

            # CREATE DELETE POLICY: Users can only delete their own data
            await session.execute(text(f"""
                CREATE POLICY user_delete_policy ON {table_name}
                FOR DELETE
                USING ({user_col} = current_setting('app.current_user_id', true));
            """))

            extras = []
            if supports_public:
                extras.append("public access")
            if table_name in SHARE_AWARE_TABLES:
                extras.append("group/user shares")
            suffix = f" ({', '.join(extras)})" if extras else ""
            logger.info(f"  ✅ RLS policies configured for {table_name}{suffix}")
    
    # Special policy for rag_document: Allow users to view documents from public KBs
    async with _safe_step(session, "public_kb_document_policy on rag_document"):
        await session.execute(text("""
            DROP POLICY IF EXISTS public_kb_document_policy ON rag_document;
        """))
        await session.execute(text("""
            CREATE POLICY public_kb_document_policy ON rag_document
            FOR SELECT
            USING (
                EXISTS (
                    SELECT 1 FROM knowledge_base kb 
                    WHERE kb.id = "kbId"
                    AND kb."isPublic" = true
                )
            );
        """))
        logger.info("  ✅ Public KB document access policy configured for rag_document")

    # Sister policy for rag_document: also let users see docs from KBs that
    # were shared with them (directly or via an AD group). Sits alongside
    # public_kb_document_policy and the existing user_isolation_policy.
    async with _safe_step(session, "shared_kb_document_policy on rag_document"):
        await session.execute(text("""
            DROP POLICY IF EXISTS shared_kb_document_policy ON rag_document;
        """))
        await session.execute(text("""
            CREATE POLICY shared_kb_document_policy ON rag_document
            FOR SELECT
            USING (
                EXISTS (
                    SELECT 1 FROM knowledge_base_share kbs
                    WHERE kbs."knowledgeBaseId" = rag_document."kbId"
                      AND (
                          (kbs."principalType" = 'user'
                           AND kbs."principalId" = current_setting('app.current_user_id', true))
                          OR
                          (kbs."principalType" = 'group'
                           AND kbs."principalId" = ANY(app_current_user_groups()))
                      )
                )
            );
        """))
        logger.info("  ✅ Shared KB document access policy configured for rag_document")

    # KB owners see every document in their knowledge bases (including uploads
    # by write-shared collaborators). Without this, user_isolation_policy only
    # exposes rows where uploadedBy = current user.
    async with _safe_step(session, "kb_owner_document_policy on rag_document"):
        await session.execute(text("""
            DROP POLICY IF EXISTS kb_owner_document_select_policy ON rag_document;
        """))
        await session.execute(text("""
            CREATE POLICY kb_owner_document_select_policy ON rag_document
            FOR SELECT USING (
                EXISTS (
                    SELECT 1 FROM knowledge_base kb
                    WHERE kb.id = rag_document."kbId"
                      AND kb."createdBy"::text = current_setting('app.current_user_id', true)
                )
            );
        """))
        logger.info("  ✅ KB owner document access policy configured for rag_document")

    # ------------------------------------------------------------------
    # RLS for the AD-group / sharing tables themselves.
    # These are not in `table_configs` because their access rules differ
    # from the standard "owner only" template.
    # ------------------------------------------------------------------

    # ad_group: every authenticated user can SELECT (so dropdowns and chips
    # can resolve display names); writes happen via the app on login or via
    # admin-only management. We keep INSERT/UPDATE permissive because RLS is
    # only the second line of defense after FastAPI auth — the API itself
    # decides who can sync groups.
    async with _safe_step(session, "RLS policies for ad_group"):
        await session.execute(text("ALTER TABLE ad_group ENABLE ROW LEVEL SECURITY;"))
        for pol in ('ad_group_select_policy', 'ad_group_insert_policy',
                    'ad_group_modify_policy', 'ad_group_delete_policy'):
            await session.execute(text(f"DROP POLICY IF EXISTS {pol} ON ad_group;"))

        await session.execute(text("""
            CREATE POLICY ad_group_select_policy ON ad_group
            FOR SELECT USING (true);
        """))
        await session.execute(text("""
            CREATE POLICY ad_group_insert_policy ON ad_group
            FOR INSERT WITH CHECK (true);
        """))
        await session.execute(text("""
            CREATE POLICY ad_group_modify_policy ON ad_group
            FOR UPDATE USING (true);
        """))
        # Only admins can prune the cache.
        await session.execute(text("""
            CREATE POLICY ad_group_delete_policy ON ad_group
            FOR DELETE USING (
                EXISTS (
                    SELECT 1 FROM "user" u
                    WHERE u.id = current_setting('app.current_user_id', true)
                      AND u."roleSlug" LIKE '%admin%'
                )
            );
        """))
        logger.info("  ✅ RLS policies configured for ad_group")

    # user_group: a user can only SELECT their own membership rows.
    # Writes are always done by the auth service (sync_user_groups), so we
    # leave INSERT/UPDATE/DELETE permissive — the FastAPI layer is the gate.
    async with _safe_step(session, "RLS policies for user_group"):
        await session.execute(text("ALTER TABLE user_group ENABLE ROW LEVEL SECURITY;"))
        for pol in ('user_group_select_policy', 'user_group_insert_policy',
                    'user_group_modify_policy', 'user_group_delete_policy'):
            await session.execute(text(f"DROP POLICY IF EXISTS {pol} ON user_group;"))

        await session.execute(text("""
            CREATE POLICY user_group_select_policy ON user_group
            FOR SELECT USING (
                "userId"::text = current_setting('app.current_user_id', true)
                OR EXISTS (
                    SELECT 1 FROM "user" u
                    WHERE u.id = current_setting('app.current_user_id', true)
                      AND u."roleSlug" LIKE '%admin%'
                )
            );
        """))
        await session.execute(text("""
            CREATE POLICY user_group_insert_policy ON user_group
            FOR INSERT WITH CHECK (true);
        """))
        await session.execute(text("""
            CREATE POLICY user_group_modify_policy ON user_group
            FOR UPDATE USING (true);
        """))
        await session.execute(text("""
            CREATE POLICY user_group_delete_policy ON user_group
            FOR DELETE USING (true);
        """))
        logger.info("  ✅ RLS policies configured for user_group")

    # ms_oauth_token: refresh tokens are highly sensitive — strictly owner-only.
    # We deliberately do NOT include the usual "admins see everything" carve-out
    # because an admin should never be able to act *as* another user via Graph.
    # The application sets app.current_user_id before any query, so RLS is the
    # backstop if a future bug forgets to add a WHERE userId = ...
    async with _safe_step(session, "RLS policies for ms_oauth_token"):
        await session.execute(text("ALTER TABLE ms_oauth_token ENABLE ROW LEVEL SECURITY;"))
        await session.execute(text("ALTER TABLE ms_oauth_token FORCE ROW LEVEL SECURITY;"))
        for pol in ('ms_oauth_token_select_policy', 'ms_oauth_token_insert_policy',
                    'ms_oauth_token_modify_policy', 'ms_oauth_token_delete_policy'):
            await session.execute(text(f"DROP POLICY IF EXISTS {pol} ON ms_oauth_token;"))

        await session.execute(text("""
            CREATE POLICY ms_oauth_token_select_policy ON ms_oauth_token
            FOR SELECT USING (
                "userId"::text = current_setting('app.current_user_id', true)
            );
        """))
        await session.execute(text("""
            CREATE POLICY ms_oauth_token_insert_policy ON ms_oauth_token
            FOR INSERT WITH CHECK (
                "userId"::text = current_setting('app.current_user_id', true)
            );
        """))
        await session.execute(text("""
            CREATE POLICY ms_oauth_token_modify_policy ON ms_oauth_token
            FOR UPDATE USING (
                "userId"::text = current_setting('app.current_user_id', true)
            );
        """))
        await session.execute(text("""
            CREATE POLICY ms_oauth_token_delete_policy ON ms_oauth_token
            FOR DELETE USING (
                "userId"::text = current_setting('app.current_user_id', true)
            );
        """))
        logger.info("  ✅ RLS policies configured for ms_oauth_token (owner-only, no admin override)")

    # workflow_share / knowledge_base_share: only the resource owner, the
    # share grantee (user or group member), or admins can see grants.
    # Only the resource owner can mutate them.
    SHARE_TABLES = (
        ('workflow_share', 'workflow_entity', '"workflowId"', '"createdById"'),
        ('knowledge_base_share', 'knowledge_base', '"knowledgeBaseId"', '"createdBy"'),
    )

    for share_tbl, parent_tbl, fk_col, owner_col in SHARE_TABLES:
        async with _safe_step(session, f"RLS policies for {share_tbl}"):
            await session.execute(text(f"ALTER TABLE {share_tbl} ENABLE ROW LEVEL SECURITY;"))
            for pol in (f'{share_tbl}_select_policy', f'{share_tbl}_insert_policy',
                        f'{share_tbl}_modify_policy', f'{share_tbl}_delete_policy'):
                await session.execute(text(f"DROP POLICY IF EXISTS {pol} ON {share_tbl};"))

            await session.execute(text(f"""
                CREATE POLICY {share_tbl}_select_policy ON {share_tbl}
                FOR SELECT USING (
                    EXISTS (
                        SELECT 1 FROM {parent_tbl} p
                        WHERE p.id = {share_tbl}.{fk_col}
                          AND p.{owner_col}::text = current_setting('app.current_user_id', true)
                    )
                    OR ("principalType" = 'user'
                        AND "principalId" = current_setting('app.current_user_id', true))
                    OR ("principalType" = 'group'
                        AND "principalId" = ANY(app_current_user_groups()))
                    OR EXISTS (
                        SELECT 1 FROM "user" u
                        WHERE u.id = current_setting('app.current_user_id', true)
                          AND u."roleSlug" LIKE '%admin%'
                    )
                );
            """))

            for cmd, kw in (("INSERT", "WITH CHECK"), ("UPDATE", "USING"), ("DELETE", "USING")):
                pol_name = f"{share_tbl}_{cmd.lower()}_policy" \
                    if cmd != "UPDATE" else f"{share_tbl}_modify_policy"
                await session.execute(text(f"""
                    CREATE POLICY {pol_name} ON {share_tbl}
                    FOR {cmd} {kw} (
                        EXISTS (
                            SELECT 1 FROM {parent_tbl} p
                            WHERE p.id = {share_tbl}.{fk_col}
                              AND p.{owner_col}::text = current_setting('app.current_user_id', true)
                        )
                    );
                """))

            logger.info(f"  ✅ RLS policies configured for {share_tbl}")

    # Special policies for marketplace_submission: Admins can see AND update all submissions
    async with _safe_step(session, "Admin policies for marketplace_submission"):
        await session.execute(text("""
            DROP POLICY IF EXISTS admin_view_all_submissions ON marketplace_submission;
        """))
        await session.execute(text("""
            DROP POLICY IF EXISTS admin_modify_all_submissions ON marketplace_submission;
        """))

        # Admins can SELECT all submissions (OR'd with user_isolation_policy)
        await session.execute(text("""
            CREATE POLICY admin_view_all_submissions ON marketplace_submission
            FOR SELECT
            USING (
                "submittedById" = current_setting('app.current_user_id', true)
                OR EXISTS (
                    SELECT 1 FROM "user" u 
                    WHERE u.id = current_setting('app.current_user_id', true)
                    AND u."roleSlug" LIKE '%admin%'
                )
            );
        """))

        # Admins can UPDATE all submissions (needed for approve/reject)
        # OR'd with user_modify_policy so submitters can also update their own
        await session.execute(text("""
            CREATE POLICY admin_modify_all_submissions ON marketplace_submission
            FOR UPDATE
            USING (
                EXISTS (
                    SELECT 1 FROM "user" u 
                    WHERE u.id = current_setting('app.current_user_id', true)
                    AND u."roleSlug" LIKE '%admin%'
                )
            );
        """))

        logger.info("  ✅ Admin SELECT + UPDATE policies configured for marketplace_submission")

    # Admin UPDATE policies for workflow_entity and knowledge_base
    # Needed so admins can publish workflows/KBs to marketplace during approval
    for table_name in ['workflow_entity', 'knowledge_base']:
        async with _safe_step(session, f"Admin UPDATE policy for {table_name}"):
            policy_name = f"admin_modify_{table_name}"
            await session.execute(text(
                f"DROP POLICY IF EXISTS {policy_name} ON {table_name};"
            ))
            await session.execute(text(f"""
                CREATE POLICY {policy_name} ON {table_name}
                FOR UPDATE
                USING (
                    EXISTS (
                        SELECT 1 FROM "user" u 
                        WHERE u.id = current_setting('app.current_user_id', true)
                        AND u."roleSlug" LIKE '%admin%'
                    )
                );
            """))
            logger.info(f"  ✅ Admin UPDATE policy configured for {table_name}")

    # ── Shared tool tables RLS ──────────────────────────────────────────────
    async with _safe_step(session, "RLS policies for shared_tool"):
        await session.execute(text("ALTER TABLE shared_tool ENABLE ROW LEVEL SECURITY;"))
        await session.execute(text("ALTER TABLE shared_tool FORCE ROW LEVEL SECURITY;"))
        for pol in ('shared_tool_select_policy', 'shared_tool_insert_policy',
                    'shared_tool_modify_policy', 'shared_tool_delete_policy'):
            await session.execute(text(f"DROP POLICY IF EXISTS {pol} ON shared_tool;"))

        await session.execute(text("""
            CREATE POLICY shared_tool_select_policy ON shared_tool
            FOR SELECT USING (
                EXISTS (
                    SELECT 1 FROM "user" u
                    WHERE u.id = current_setting('app.current_user_id', true)
                      AND u."roleSlug" LIKE '%admin%'
                )
                OR (created_by = current_setting('app.current_user_id', true))
                OR (status = 'approved' AND is_public = true)
                OR (status = 'approved' AND EXISTS (
                    SELECT 1 FROM shared_tool_permission p
                    WHERE p.shared_tool_id = shared_tool.id
                      AND p.principal_type = 'user'
                      AND p.principal_id = current_setting('app.current_user_id', true)
                ))
                OR (status = 'approved' AND EXISTS (
                    SELECT 1 FROM shared_tool_permission p
                    WHERE p.shared_tool_id = shared_tool.id
                      AND p.principal_type = 'group'
                      AND p.principal_id = ANY(app_current_user_groups())
                ))
            );
        """))

        await session.execute(text("""
            CREATE POLICY shared_tool_insert_policy ON shared_tool
            FOR INSERT WITH CHECK (true);
        """))

        await session.execute(text("""
            CREATE POLICY shared_tool_modify_policy ON shared_tool
            FOR UPDATE USING (
                EXISTS (
                    SELECT 1 FROM "user" u
                    WHERE u.id = current_setting('app.current_user_id', true)
                      AND u."roleSlug" LIKE '%admin%'
                )
            );
        """))

        await session.execute(text("""
            CREATE POLICY shared_tool_delete_policy ON shared_tool
            FOR DELETE USING (
                EXISTS (
                    SELECT 1 FROM "user" u
                    WHERE u.id = current_setting('app.current_user_id', true)
                      AND u."roleSlug" LIKE '%admin%'
                )
            );
        """))
        logger.info("  ✅ RLS policies configured for shared_tool")

    async with _safe_step(session, "RLS policies for shared_tool_permission"):
        await session.execute(text("ALTER TABLE shared_tool_permission ENABLE ROW LEVEL SECURITY;"))
        await session.execute(text("ALTER TABLE shared_tool_permission FORCE ROW LEVEL SECURITY;"))
        for pol in ('shared_tool_perm_select_policy', 'shared_tool_perm_insert_policy',
                    'shared_tool_perm_modify_policy', 'shared_tool_perm_delete_policy'):
            await session.execute(text(f"DROP POLICY IF EXISTS {pol} ON shared_tool_permission;"))

        await session.execute(text("""
            CREATE POLICY shared_tool_perm_select_policy ON shared_tool_permission
            FOR SELECT USING (true);
        """))

        for cmd, kw in (("INSERT", "WITH CHECK"), ("UPDATE", "USING"), ("DELETE", "USING")):
            pol_name = f"shared_tool_perm_{cmd.lower()}_policy" \
                if cmd != "UPDATE" else "shared_tool_perm_modify_policy"
            await session.execute(text(f"""
                CREATE POLICY {pol_name} ON shared_tool_permission
                FOR {cmd} {kw} (
                    EXISTS (
                        SELECT 1 FROM "user" u
                        WHERE u.id = current_setting('app.current_user_id', true)
                          AND u."roleSlug" LIKE '%admin%'
                    )
                );
            """))
        logger.info("  ✅ RLS policies configured for shared_tool_permission")

    async with _safe_step(session, "RLS policies for shared_tool_audit_log"):
        await session.execute(text("ALTER TABLE shared_tool_audit_log ENABLE ROW LEVEL SECURITY;"))
        await session.execute(text("ALTER TABLE shared_tool_audit_log FORCE ROW LEVEL SECURITY;"))
        for pol in ('shared_tool_audit_select_policy', 'shared_tool_audit_insert_policy'):
            await session.execute(text(f"DROP POLICY IF EXISTS {pol} ON shared_tool_audit_log;"))

        await session.execute(text("""
            CREATE POLICY shared_tool_audit_select_policy ON shared_tool_audit_log
            FOR SELECT USING (
                EXISTS (
                    SELECT 1 FROM "user" u
                    WHERE u.id = current_setting('app.current_user_id', true)
                      AND u."roleSlug" LIKE '%admin%'
                )
            );
        """))

        await session.execute(text("""
            CREATE POLICY shared_tool_audit_insert_policy ON shared_tool_audit_log
            FOR INSERT WITH CHECK (true);
        """))
        logger.info("  ✅ RLS policies configured for shared_tool_audit_log")

    try:
        await session.commit()
        logger.info("✅ Database security initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to commit RLS changes: {e}")
        await session.rollback()
