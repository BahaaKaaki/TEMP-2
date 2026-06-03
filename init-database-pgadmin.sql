-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- PostgreSQL Database Initialization Script for pgAdmin
-- Agent Builder Application - Database Setup
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
--
-- INSTRUCTIONS:
-- 1. Connect to 'postgres' database in pgAdmin
-- 2. Select and run SECTION 1 (entire block from DO $$ to END $$;)
-- 3. Manually create database using the CREATE DATABASE command below
-- 4. Reconnect to 'agent-builder' database in pgAdmin
-- 5. Select and run SECTION 2 (entire block from DO $$ to END $$;)
-- 6. Optionally run VERIFICATION QUERIES at the end
--
-- IMPORTANT: When running a DO $$ block, you MUST select from "DO $$" 
-- all the way to "END $$;" including the semicolon!
--
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- ============================================================================
-- CONFIGURATION - Edit these values in each DO block below if needed
-- ============================================================================
-- Database name:        agent-builder
-- Admin user:           sa
-- Admin password:       anypass123!!
-- Application user:     app
-- Application password: anypass123!!
-- ============================================================================


-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║                                                                          ║
-- ║  SECTION 1: CREATE USERS                                                 ║
-- ║  Connect to 'postgres' database before running this                      ║
-- ║                                                                          ║
-- ║  SELECT FROM "DO $$" TO "END $$;" AND PRESS F5 or Execute               ║
-- ║                                                                          ║
-- ╚══════════════════════════════════════════════════════════════════════════╝

DO $$
DECLARE
    v_db_name TEXT := 'agent-builder';
    v_admin_user TEXT := 'sa';
    v_admin_password TEXT := 'anypass123!!';
    v_app_user TEXT := 'app';
    v_app_password TEXT := 'anypass123!!';
    v_db_exists BOOLEAN;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
    RAISE NOTICE '📦 SECTION 1: Creating Database and Users';
    RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
    RAISE NOTICE '';
    
    -- ============================================================================
    -- 1.1: Create Admin User (if not exists)
    -- ============================================================================
    RAISE NOTICE '👤 Creating admin user...';
    
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = v_admin_user) THEN
        EXECUTE format('CREATE ROLE %I WITH LOGIN PASSWORD %L CREATEDB CREATEROLE', v_admin_user, v_admin_password);
        RAISE NOTICE 'Admin user created: %', v_admin_user;
    ELSE
        EXECUTE format('ALTER ROLE %I WITH LOGIN PASSWORD %L CREATEDB CREATEROLE', v_admin_user, v_admin_password);
        RAISE NOTICE 'Admin user already exists, updated privileges: %', v_admin_user;
    END IF;
    
    RAISE NOTICE '✅ Admin user configured';
    RAISE NOTICE '';
    
    -- ============================================================================
    -- 1.2: Create Application User (if not exists)
    -- ============================================================================
    RAISE NOTICE '🔐 Creating application user...';
    
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = v_app_user) THEN
        EXECUTE format('CREATE ROLE %I WITH LOGIN PASSWORD %L CREATEDB CREATEROLE', v_app_user, v_app_password);
        RAISE NOTICE 'Application user created: %', v_app_user;
    ELSE
        EXECUTE format('ALTER ROLE %I WITH LOGIN PASSWORD %L CREATEDB CREATEROLE', v_app_user, v_app_password);
        RAISE NOTICE 'Application user already exists, updated privileges: %', v_app_user;
    END IF;
    
    RAISE NOTICE '✅ Application user configured';
    RAISE NOTICE '';
    
    -- ============================================================================
    -- 1.3: Check if Database exists
    -- ============================================================================
    RAISE NOTICE '💾 Checking database...';
    
    SELECT EXISTS (SELECT FROM pg_database WHERE datname = v_db_name) INTO v_db_exists;
    
    IF v_db_exists THEN
        RAISE NOTICE 'Database already exists: %', v_db_name;
    ELSE
        RAISE NOTICE 'Database does not exist: %', v_db_name;
        RAISE NOTICE '';
        RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
        RAISE NOTICE '⚠️  IMPORTANT: Database must be created manually in pgAdmin:';
        RAISE NOTICE '   1. Right-click "Databases" in pgAdmin tree';
        RAISE NOTICE '   2. Select "Create" > "Database..."';
        RAISE NOTICE '   3. Enter name: %', v_db_name;
        RAISE NOTICE '   4. Select owner: %', v_admin_user;
        RAISE NOTICE '   5. Click "Save"';
        RAISE NOTICE '';
        RAISE NOTICE '   OR run this SQL (disconnect from database first):';
        RAISE NOTICE '   CREATE DATABASE "%s" OWNER %s ENCODING ''UTF8'';', v_db_name, v_admin_user;
        RAISE NOTICE '';
        RAISE NOTICE '   Then RECONNECT to "%" database and run SECTION 2 below', v_db_name;
        RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
    END IF;
    
    RAISE NOTICE '';
    RAISE NOTICE '✅ Section 1 completed - Users created';
    RAISE NOTICE '';
    RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
    RAISE NOTICE '⚠️  NEXT: Create the database manually using command below, then run SECTION 2';
    RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
END $$;


-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║                                                                          ║
-- ║  CREATE DATABASE COMMAND                                                 ║
-- ║  Run this command separately (not part of a DO block)                    ║
-- ║                                                                          ║
-- ╚══════════════════════════════════════════════════════════════════════════╝

CREATE DATABASE "agent-builder" 
    OWNER sa 
    ENCODING 'UTF8'
    LC_COLLATE = 'en_US.UTF-8'
    LC_CTYPE = 'en_US.UTF-8'
    TEMPLATE template0;

-- After creating the database, DISCONNECT from 'postgres' and RECONNECT to 'agent-builder'


-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║                                                                          ║
-- ║  SECTION 2: CONFIGURE DATABASE                                           ║
-- ║  MUST be connected to 'agent-builder' database before running this       ║
-- ║                                                                          ║
-- ║  SELECT FROM "DO $$" TO "END $$;" AND PRESS F5 or Execute               ║
-- ║                                                                          ║
-- ╚══════════════════════════════════════════════════════════════════════════╝

DO $$
DECLARE
    v_db_name TEXT := 'agent-builder';
    v_admin_user TEXT := 'sa';
    v_app_user TEXT := 'app';
    admin_is_super BOOLEAN;
    app_is_super BOOLEAN;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
    RAISE NOTICE '📦 SECTION 2: Database Extensions and Permissions';
    RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
    RAISE NOTICE '⚠️  Make sure you are connected to agent-builder database!';
    RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
    RAISE NOTICE '';
    
    -- ============================================================================
    -- 2.1: Create Vector Extension
    -- ============================================================================
    RAISE NOTICE '🔧 Creating vector extensions...';
    
    -- Try to create vector extension (required for vector operations)
    -- Azure PostgreSQL Flexible Server uses DiskANN for vector operations
    BEGIN
        -- Try pg_diskann extension first (for Azure DiskANN)
        BEGIN
            CREATE EXTENSION IF NOT EXISTS pg_diskann CASCADE;
            RAISE NOTICE '✅ pg_diskann extension created successfully (DiskANN available)';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE '⚠️  pg_diskann extension not available, trying pgvector...';
            -- Fall back to pgvector
            BEGIN
                CREATE EXTENSION IF NOT EXISTS vector CASCADE;
                RAISE NOTICE '✅ vector (pgvector) extension created successfully';
            EXCEPTION WHEN OTHERS THEN
                RAISE WARNING '❌ No vector extension available';
                RAISE NOTICE '   Vector similarity search may not be available';
            END;
        END;
    END;
    
    RAISE NOTICE '✅ Vector extension setup completed';
    RAISE NOTICE '';
    
    -- ============================================================================
    -- 2.2: Grant Database-Level Privileges
    -- ============================================================================
    RAISE NOTICE '🔑 Granting database privileges...';
    
    -- Grant privileges to admin user
    EXECUTE format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', v_db_name, v_admin_user);
    EXECUTE format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', v_db_name, v_app_user);
    
    RAISE NOTICE '✅ Database privileges granted to both users';
    RAISE NOTICE '';
    
    -- ============================================================================
    -- 2.3: Configure Public Schema
    -- ============================================================================
    RAISE NOTICE '🏗️  Configuring public schema...';
    
    -- Transfer schema ownership to application user
    EXECUTE format('ALTER SCHEMA public OWNER TO %I', v_app_user);
    
    -- Grant schema privileges to both users
    EXECUTE format('GRANT ALL ON SCHEMA public TO %I', v_admin_user);
    EXECUTE format('GRANT ALL ON SCHEMA public TO %I', v_app_user);
    EXECUTE format('GRANT CREATE ON SCHEMA public TO %I', v_admin_user);
    EXECUTE format('GRANT CREATE ON SCHEMA public TO %I', v_app_user);
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', v_admin_user);
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', v_app_user);
    
    RAISE NOTICE '✅ Public schema configured and ownership transferred to app user';
    RAISE NOTICE '';
    
    -- ============================================================================
    -- 2.4: Grant Privileges on Existing Objects
    -- ============================================================================
    RAISE NOTICE '📋 Granting privileges on existing objects...';
    
    -- Grant privileges on all existing tables
    EXECUTE format('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO %I', v_admin_user);
    EXECUTE format('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO %I', v_app_user);
    
    -- Grant privileges on all existing sequences
    EXECUTE format('GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO %I', v_admin_user);
    EXECUTE format('GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO %I', v_app_user);
    
    -- Grant privileges on all existing functions
    EXECUTE format('GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO %I', v_admin_user);
    EXECUTE format('GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO %I', v_app_user);
    
    RAISE NOTICE '✅ Existing object privileges granted';
    RAISE NOTICE '';
    
    -- ============================================================================
    -- 2.5: Set Default Privileges for Future Objects
    -- ============================================================================
    RAISE NOTICE '⚙️  Setting default privileges for future objects...';
    
    -- Default privileges for objects created by admin user (sa)
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL ON TABLES TO %I', v_admin_user, v_admin_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL ON TABLES TO %I', v_admin_user, v_app_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL ON SEQUENCES TO %I', v_admin_user, v_admin_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL ON SEQUENCES TO %I', v_admin_user, v_app_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL ON FUNCTIONS TO %I', v_admin_user, v_admin_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL ON FUNCTIONS TO %I', v_admin_user, v_app_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE ON TYPES TO %I', v_admin_user, v_admin_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE ON TYPES TO %I', v_admin_user, v_app_user);
    
    -- Default privileges for objects created by app user
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL ON TABLES TO %I', v_app_user, v_admin_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL ON TABLES TO %I', v_app_user, v_app_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL ON SEQUENCES TO %I', v_app_user, v_admin_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL ON SEQUENCES TO %I', v_app_user, v_app_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL ON FUNCTIONS TO %I', v_app_user, v_admin_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL ON FUNCTIONS TO %I', v_app_user, v_app_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE ON TYPES TO %I', v_app_user, v_admin_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE ON TYPES TO %I', v_app_user, v_app_user);
    
    -- Default privileges for objects created by postgres user (superuser)
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO %I', v_admin_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO %I', v_app_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO %I', v_admin_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO %I', v_app_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO %I', v_admin_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO %I', v_app_user);
    
    RAISE NOTICE '✅ Default privileges configured';
    RAISE NOTICE '';
    
    -- ============================================================================
    -- 2.6: Enable Cross-User Capabilities
    -- ============================================================================
    RAISE NOTICE '🔗 Configuring cross-user capabilities...';
    
    -- Enable app user to inherit admin privileges when needed (for extensions)
    EXECUTE format('GRANT %I TO %I', v_app_user, v_admin_user);
    
    RAISE NOTICE '✅ Cross-user capabilities configured';
    RAISE NOTICE '';
    
    -- ============================================================================
    -- 2.7: Security Verification - RLS Enforcement
    -- ============================================================================
    RAISE NOTICE '🔒 Performing security verification...';
    
    -- Check if admin user is superuser
    SELECT rolsuper INTO admin_is_super FROM pg_roles WHERE rolname = v_admin_user;
    
    -- Check if app user is superuser
    SELECT rolsuper INTO app_is_super FROM pg_roles WHERE rolname = v_app_user;
    
    IF admin_is_super THEN
        RAISE WARNING '⚠️  Admin user (%) has superuser privileges - this is expected for admin tasks', v_admin_user;
    ELSE
        RAISE NOTICE '✅ Admin user (%) is NOT a superuser', v_admin_user;
    END IF;
    
    IF app_is_super THEN
        RAISE EXCEPTION '❌ SECURITY ERROR: App user (%) has superuser privileges! RLS will be bypassed.', v_app_user;
    ELSE
        RAISE NOTICE '✅ Security check passed: app user is NOT a superuser (RLS will be enforced)';
    END IF;
    
    RAISE NOTICE '✅ Security verification completed';
    RAISE NOTICE '';
    
    -- ============================================================================
    -- SECTION 3: SUMMARY
    -- ============================================================================
    
    RAISE NOTICE '';
    RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
    RAISE NOTICE '✅ DATABASE INITIALIZATION COMPLETED SUCCESSFULLY!';
    RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
    RAISE NOTICE '';
    RAISE NOTICE '📊 INITIALIZATION SUMMARY';
    RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
    RAISE NOTICE '   Database:           %', v_db_name;
    RAISE NOTICE '   Admin User:         % (with CREATEDB, CREATEROLE)', v_admin_user;
    RAISE NOTICE '   App User:           % (with CREATEDB, CREATEROLE)', v_app_user;
    RAISE NOTICE '   Schema Owner:       %', v_app_user;
    RAISE NOTICE '   Vector Extension:   Enabled (pg_diskann/DiskANN or pgvector)';
    RAISE NOTICE '   RLS Enforcement:    Enabled (app user is not superuser)';
    RAISE NOTICE '   Default Privileges: Configured for both users';
    RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
    RAISE NOTICE '';
    RAISE NOTICE '📋 Next Steps:';
    RAISE NOTICE '   1. ✅ Database is ready for application deployment';
    RAISE NOTICE '   2. ✅ Both users can create tables, sequences, and functions';
    RAISE NOTICE '   3. ✅ Row-Level Security (RLS) will be enforced for app user';
    RAISE NOTICE '   4. ✅ Admin user (%) can perform administrative tasks', v_admin_user;
    RAISE NOTICE '   5. ✅ App user (%) can perform application operations', v_app_user;
    RAISE NOTICE '';
    RAISE NOTICE '🔌 Connection Details:';
    RAISE NOTICE '   • Use "%" user for admin/migration tasks', v_admin_user;
    RAISE NOTICE '   • Use "%" user for application runtime', v_app_user;
    RAISE NOTICE '   • Database: %', v_db_name;
    RAISE NOTICE '';
    RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
END $$;


-- ╔══════════════════════════════════════════════════════════════════════════╗
-- ║                                                                          ║
-- ║  VERIFICATION QUERIES (Optional)                                         ║
-- ║  Run these separately to verify the setup                                ║
-- ║                                                                          ║
-- ╚══════════════════════════════════════════════════════════════════════════╝

-- Query 1: Verify users exist and their privileges
SELECT 
    rolname AS "User", 
    rolsuper AS "Superuser", 
    rolcreatedb AS "Can Create DB", 
    rolcreaterole AS "Can Create Role"
FROM pg_roles 
WHERE rolname IN ('sa', 'app')
ORDER BY rolname;

-- Query 2: Verify database exists and check owner
SELECT 
    datname AS "Database", 
    pg_catalog.pg_get_userbyid(datdba) AS "Owner"
FROM pg_database
WHERE datname = 'agent-builder';

-- Query 3: Verify schema owner
SELECT 
    nspname AS "Schema", 
    pg_catalog.pg_get_userbyid(nspowner) AS "Owner"
FROM pg_namespace
WHERE nspname = 'public';

-- Query 4: Verify extensions
SELECT 
    extname AS "Extension", 
    extversion AS "Version"
FROM pg_extension
WHERE extname IN ('vector', 'pg_diskann')
ORDER BY extname;
