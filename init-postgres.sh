#!/bin/bash
set -e

# This script runs on postgres container startup to create the application user
# and grant necessary permissions

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create vector extension first (requires superuser)
    CREATE EXTENSION IF NOT EXISTS vchord CASCADE;
    \echo '✅ Vector extension created'

    -- Create application user if it doesn't exist with elevated privileges
    DO
    \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${APP_USER}') THEN
            CREATE ROLE ${APP_USER} WITH LOGIN PASSWORD '${APP_PASSWORD}' CREATEDB CREATEROLE;
            RAISE NOTICE 'Created user: ${APP_USER}';
        ELSE
            -- Update existing user with necessary privileges
            ALTER ROLE ${APP_USER} WITH LOGIN PASSWORD '${APP_PASSWORD}' CREATEDB CREATEROLE;
            RAISE NOTICE 'User ${APP_USER} already exists, updated privileges';
        END IF;
    END
    \$\$;

    -- Grant database privileges (quote database name to handle hyphens)
    GRANT ALL PRIVILEGES ON DATABASE "${POSTGRES_DB}" TO ${APP_USER};
    
    -- Make app user owner of public schema (required for creating types)
    ALTER SCHEMA public OWNER TO ${APP_USER};
    
    -- Grant all schema privileges
    GRANT ALL ON SCHEMA public TO ${APP_USER};
    GRANT CREATE ON SCHEMA public TO ${APP_USER};
    GRANT USAGE ON SCHEMA public TO ${APP_USER};
    
    -- Grant privileges on all existing tables
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ${APP_USER};
    
    -- Grant privileges on all existing sequences
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ${APP_USER};
    
    -- Grant privileges on all existing functions
    GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO ${APP_USER};
    
    -- Set default privileges for future objects created by admin
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ${APP_USER};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO ${APP_USER};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO ${APP_USER};
    
    -- Set default privileges for objects created by app user
    ALTER DEFAULT PRIVILEGES FOR ROLE ${APP_USER} IN SCHEMA public GRANT ALL ON TABLES TO ${APP_USER};
    ALTER DEFAULT PRIVILEGES FOR ROLE ${APP_USER} IN SCHEMA public GRANT ALL ON SEQUENCES TO ${APP_USER};
    ALTER DEFAULT PRIVILEGES FOR ROLE ${APP_USER} IN SCHEMA public GRANT ALL ON FUNCTIONS TO ${APP_USER};
    
    -- Enable app user to create extensions if needed
    GRANT ${APP_USER} TO ${POSTGRES_USER};
    
    -- Grant superuser-like capabilities for common extensions
    GRANT CREATE ON DATABASE "${POSTGRES_DB}" TO ${APP_USER};

    \echo '✅ Application user ${APP_USER} configured with elevated privileges and full access to ${POSTGRES_DB}'
EOSQL
