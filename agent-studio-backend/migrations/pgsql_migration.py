from sqlalchemy import create_engine, inspect, MetaData, text
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects.postgresql import ENUM, DOUBLE_PRECISION
import sqlalchemy as sa
import logging
import datetime
import os
import uuid
import asyncio
from typing import Dict, Any
from dotenv import load_dotenv
from app.db.models import Base, User
# Load environment variables
load_dotenv()

# Get database connection info from environment variables
# Use ADMIN user for migrations (has permissions to create users, grant privileges, etc.)
ADMIN_USER = os.getenv("ADMIN_POSTGRES_USER", "sa")
ADMIN_PASSWORD = os.getenv("ADMIN_POSTGRES_PASSWORD")
DB_NAME = os.getenv("POSTGRES_DB")
DB_HOST = os.getenv("DATABASE_PRIMARY_HOST", "localhost")

# Application user (non-superuser for RLS)
APP_USER = os.getenv("POSTGRES_USER", "app")
APP_PASSWORD = os.getenv("POSTGRES_PASSWORD")

# Construct database URL using ADMIN credentials for migration
SQLALCHEMY_DATABASE_URL = f"postgresql://{ADMIN_USER}:{ADMIN_PASSWORD}@{DB_HOST}:5432/{DB_NAME}"

# Set up logging
def setup_logging():
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # Create a logger
    logger = logging.getLogger('database_migration')
    logger.setLevel(logging.INFO)
    
    # Create handlers
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    file_handler = logging.FileHandler(f'logs/db_migration_{timestamp}.log')
    console_handler = logging.StreamHandler()
    
    # Create formatters and add it to handlers
    log_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(log_format)
    console_handler.setFormatter(log_format)
    
    # Add handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

def get_engine():
    try:
        engine = create_engine(
            SQLALCHEMY_DATABASE_URL,
            echo=False,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        logger.info("Database engine created successfully")
        return engine
    except Exception as e:
        logger.error(f"Failed to create database engine: {str(e)}")
        raise

def create_tables_if_not_exist():
    """Create tables if they don't exist"""
    try:
        engine = get_engine()
        # Import Base here to avoid circular imports
        
        Base.metadata.create_all(engine)
        logger.info("Initial table creation completed successfully")
    except Exception as e:
        logger.error(f"Error during table creation: {str(e)}")
        raise

def get_existing_columns(table_name: str, engine) -> Dict[str, Any]:
    """Get existing columns for a table"""
    try:
        inspector = inspect(engine)
        columns = {col['name']: col for col in inspector.get_columns(table_name)}
        logger.debug(f"Retrieved existing columns for table {table_name}: {list(columns.keys())}")
        return columns
    except Exception as e:
        logger.error(f"Error getting columns for table {table_name}: {str(e)}")
        raise

def get_existing_tables(engine) -> list:
    """Get list of existing tables"""
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        logger.debug(f"Retrieved existing tables: {tables}")
        return tables
    except Exception as e:
        logger.error(f"Error getting existing tables: {str(e)}")
        raise

def handle_column_type_change(table_name: str, column_name: str, old_type: str, new_type: str, engine):
    """Handle column type changes with detailed logging"""
    try:
        with engine.begin() as conn:
            # Log the type change attempt
            logger.info(f"Attempting to change column type: {table_name}.{column_name}")
            logger.info(f"From: {old_type} To: {new_type}")
            
            # Try to alter the column type
            conn.execute(sa.text(f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE {new_type}"))
            
            logger.info(f"Successfully changed column type for {table_name}.{column_name}")
    except Exception as e:
        logger.error(f"Failed to change column type for {table_name}.{column_name}")
        logger.error(f"Error details: {str(e)}")
        # Log specific PostgreSQL error codes if available
        if hasattr(e, 'pgcode'):
            logger.error(f"PostgreSQL error code: {e.pgcode}")
        raise

def is_compatible_type(existing_type: str, new_type: str) -> bool:
    """Check if the existing database type is compatible with the new type"""
    # Normalize type strings
    existing_type = existing_type.upper()
    new_type = new_type.upper()
    
    # Define type compatibility mappings
    type_compatibility = {
        'DOUBLE PRECISION': ['FLOAT', 'DOUBLE PRECISION'],
        'FLOAT': ['FLOAT', 'DOUBLE PRECISION'],
    }
    
    # Check if types are compatible
    if existing_type in type_compatibility:
        return new_type in type_compatibility[existing_type]
    
    # For other types, require exact match
    return existing_type == new_type

def migrate_schema():
    """Handle schema modifications without dropping tables"""
    engine = get_engine()
    metadata = MetaData()
    
    try:
        # Get all existing tables
        existing_tables = get_existing_tables(engine)
        
        # Import Base here to avoid circular imports
 
        # For each model in Base.metadata.tables
        for table_name, table in Base.metadata.tables.items():
            if table_name not in existing_tables:
                # Create new table
                table.create(engine)
                logger.info(f"Created new table: {table_name}")
                continue
                
            # Get existing columns
            existing_columns = get_existing_columns(table_name, engine)
            
            # Compare and add new columns
            for column in table.columns:
                # PostgreSQL folds unquoted identifiers to lowercase, so
                # the inspector always returns lowercase keys.  We must
                # compare case-insensitively to avoid duplicate ADD attempts
                # for camelCase columns that already exist.
                existing_lower = {k.lower(): v for k, v in existing_columns.items()}
                col_exists = column.name.lower() in existing_lower

                if not col_exists:
                    # Add new column
                    column_type = column.type
                    if isinstance(column_type, ENUM):
                        # Handle ENUM type specially
                        try:
                            column_type.create(engine, checkfirst=True)
                            logger.info(f"Created ENUM type for {column.name}")
                        except Exception as e:
                            logger.error(f"Failed to create ENUM type for {column.name}: {str(e)}")
                            raise
                    
                    try:
                        with engine.begin() as conn:
                            # Quote column name to preserve camelCase in PostgreSQL
                            conn.execute(sa.text(f'ALTER TABLE {table_name} ADD COLUMN "{column.name}" {column_type}'))
                        logger.info(f"Added new column {column.name} to {table_name}")
                    except Exception as e:
                        logger.error(f"Failed to add column {column.name} to {table_name}")
                        logger.error(f"Error details: {str(e)}")
                        raise
                
                # Check for type changes
                elif column.name.lower() in existing_lower and not is_compatible_type(str(existing_lower[column.name.lower()]['type']), str(column.type)):
                    handle_column_type_change(
                        table_name,
                        f'"{column.name}"',
                        str(existing_lower[column.name.lower()]['type']),
                        str(column.type),
                        engine
                    )

    except Exception as e:
        logger.error(f"Error during schema migration: {str(e)}")
        raise

def backfill_workflow_versions():
    """
    One-time backfill: for each published workflow that has no version
    history rows yet, create an initial 'publish' snapshot and set versionId.
    Also creates a 'save' snapshot for draft workflows with no history.
    """
    logger.info("🔄 Checking for workflow version backfill...")
    engine = get_engine()

    try:
        with engine.begin() as conn:
            # Check if workflow_history table exists
            result = conn.execute(text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'workflow_history')"
            ))
            if not result.scalar():
                logger.info("  ℹ️  workflow_history table does not exist yet, skipping backfill")
                return

            # Find published workflows with no version history
            rows = conn.execute(text("""
                SELECT w.id, w.name, w.nodes, w.connections, w.settings,
                       w."isDraft", w."createdByName", w."createdById"
                FROM workflow_entity w
                LEFT JOIN workflow_history wh ON wh."workflowId" = w.id
                WHERE wh."versionId" IS NULL
                  AND w."isArchived" = false
            """)).fetchall()

            if not rows:
                logger.info("  ✅ All workflows already have version history, nothing to backfill")
                return

            backfilled = 0
            for row in rows:
                wf_id, wf_name, nodes, connections, settings, is_draft, author, creator_id = row
                version_id = str(uuid.uuid4())
                event = "save" if is_draft else "publish"
                is_published = not is_draft

                conn.execute(text("""
                    INSERT INTO workflow_history (
                        "versionId", "workflowId", "versionNumber", authors,
                        nodes, connections, settings,
                        "isPublishedSnapshot", event, "createdAt"
                    ) VALUES (
                        :vid, :wid, 1, :author,
                        :nodes, :connections, :settings,
                        :is_published, :event, NOW()
                    )
                """), {
                    "vid": version_id,
                    "wid": wf_id,
                    "author": author or "system",
                    "nodes": nodes or "[]",
                    "connections": connections or "{}",
                    "settings": settings,
                    "is_published": is_published,
                    "event": event,
                })

                if is_published:
                    conn.execute(text("""
                        UPDATE workflow_entity SET "versionId" = :vid
                        WHERE id = :wid
                    """), {"vid": version_id, "wid": wf_id})

                backfilled += 1
                logger.info(
                    "  📝 Backfilled v1 for workflow '%s' (%s) [event=%s]",
                    wf_name, wf_id, event,
                )

            logger.info("  ✅ Backfilled %d workflow(s) with initial version history", backfilled)

    except Exception as e:
        logger.error(f"❌ Failed to backfill workflow versions: {e}")
        logger.warning("  ℹ️  Backfill can be re-run safely (idempotent)")


def run_migrations():
    """Main function to run all migrations"""
    logger.info("Starting database migration process")
    logger.info(f"Running as database user: {ADMIN_USER}")
    start_time = datetime.datetime.now()
    
    try:
        # First setup application user with proper permissions
        setup_application_user()
        logger.info("Application user setup completed")
        
        # Create any missing tables
        create_tables_if_not_exist()
        logger.info("Initial table creation completed")
        
        # Then handle any schema modifications
        migrate_schema()
        logger.info("Schema modifications completed")
        
        # Grant permissions to application user
        grant_permissions_to_app_user()
        logger.info("Application user permissions granted")
        
        # Setup Row-Level Security policies
        setup_rls_policies()
        logger.info("RLS policies configured")
        
        logger.info("Default user setup skipped (manual creation required)")

        # Backfill workflow version history for existing workflows
        backfill_workflow_versions()
        logger.info("Workflow version backfill completed")
        
        end_time = datetime.datetime.now()
        duration = end_time - start_time
        logger.info(f"Migration completed successfully in {duration}")
        
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        logger.error("Stack trace:", exc_info=True)
        raise
    finally:
        logger.info("Migration process finished")


def setup_application_user():
    """
    Create application user (non-superuser) for RLS to work properly.
    This user should NOT have SUPERUSER or BYPASSRLS privileges.
    """
    logger.info(f"👤 Setting up application user: {APP_USER}")
    engine = get_engine()
    
    try:
        with engine.begin() as conn:
            # Check if user exists
            result = conn.execute(text(f"""
                SELECT 1 FROM pg_roles WHERE rolname = '{APP_USER}'
            """))
            user_exists = result.scalar() is not None
            
            if not user_exists:
                logger.info(f"  📝 Creating user: {APP_USER}")
                conn.execute(text(f"""
                    CREATE USER {APP_USER} WITH PASSWORD '{APP_PASSWORD}';
                """))
            else:
                logger.info(f"  ✅ User {APP_USER} already exists")
                # Update password in case it changed
                conn.execute(text(f"""
                    ALTER USER {APP_USER} WITH PASSWORD '{APP_PASSWORD}';
                """))
            
            # Ensure user is NOT superuser and does NOT have BYPASSRLS
            conn.execute(text(f"""
                ALTER USER {APP_USER} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            """))
            logger.info(f"  ✅ User {APP_USER} configured as regular user (no superuser, no bypassrls)")
            
            # Grant connect to database
            conn.execute(text(f"""
                GRANT CONNECT ON DATABASE "{DB_NAME}" TO {APP_USER};
            """))
            
            # Grant usage on public schema
            conn.execute(text(f"""
                GRANT USAGE, CREATE ON SCHEMA public TO {APP_USER};
            """))
            
            logger.info(f"  ✅ Basic permissions granted to {APP_USER}")
            
    except Exception as e:
        logger.error(f"❌ Failed to setup application user: {e}")
        raise


def grant_permissions_to_app_user():
    """
    Grant all necessary permissions to application user on all tables.
    """
    logger.info(f"🔑 Granting table permissions to {APP_USER}...")
    engine = get_engine()
    
    try:
        with engine.begin() as conn:
            # Grant all privileges on all tables in public schema
            conn.execute(text(f"""
                GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {APP_USER};
            """))
            
            # Grant all privileges on all sequences (for auto-increment IDs)
            conn.execute(text(f"""
                GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {APP_USER};
            """))
            
            # Grant default privileges for future tables
            conn.execute(text(f"""
                ALTER DEFAULT PRIVILEGES IN SCHEMA public 
                GRANT ALL PRIVILEGES ON TABLES TO {APP_USER};
            """))
            
            # Grant default privileges for future sequences
            conn.execute(text(f"""
                ALTER DEFAULT PRIVILEGES IN SCHEMA public 
                GRANT ALL PRIVILEGES ON SEQUENCES TO {APP_USER};
            """))
            
            logger.info(f"  ✅ All table and sequence permissions granted to {APP_USER}")
            
    except Exception as e:
        logger.error(f"❌ Failed to grant permissions: {e}")
        raise


def setup_rls_policies():
    """
    Setup Row-Level Security policies for all user tables.
    Ensures data isolation between users.
    """
    logger.info("🔒 Setting up Row-Level Security policies...")
    engine = get_engine()
    
    # Table configurations: (table_name, user_id_column)
    table_configs = [
        ('workflow_entity', '"createdById"'),
        ('execution_entity', '"triggeredById"'),
        ('chat_session', '"userId"'),
        ('agent_deliverable', '"createdById"'),
        ('chat_file', '"uploadedBy"'),
        ('knowledge_base', '"createdBy"'),
        ('rag_document', '"createdBy"'),
        ('project', '"userId"'),
    ]
    
    try:
        with engine.begin() as conn:
            for table_name, user_col in table_configs:
                try:
                    # Enable RLS on table
                    conn.execute(text(
                        f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;"
                    ))
                    
                    # Force RLS even for table owners
                    conn.execute(text(
                        f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;"
                    ))
                    
                    # Drop existing policies (idempotent)
                    conn.execute(text(
                        f"DROP POLICY IF EXISTS user_isolation_policy ON {table_name};"
                    ))
                    conn.execute(text(
                        f"DROP POLICY IF EXISTS user_insert_policy ON {table_name};"
                    ))
                    conn.execute(text(
                        f"DROP POLICY IF EXISTS user_modify_policy ON {table_name};"
                    ))
                    conn.execute(text(
                        f"DROP POLICY IF EXISTS user_delete_policy ON {table_name};"
                    ))
                    
                    # CREATE SELECT POLICY: Users only see their own data
                    conn.execute(text(f"""
                        CREATE POLICY user_isolation_policy ON {table_name}
                        FOR SELECT
                        USING ({user_col} = current_setting('app.current_user_id', true)::uuid);
                    """))
                    
                    # CREATE INSERT POLICY: Allow authenticated users to insert
                    conn.execute(text(f"""
                        CREATE POLICY user_insert_policy ON {table_name}
                        FOR INSERT
                        WITH CHECK (true);
                    """))
                    
                    # CREATE UPDATE POLICY: Users can only update their own data
                    conn.execute(text(f"""
                        CREATE POLICY user_modify_policy ON {table_name}
                        FOR UPDATE
                        USING ({user_col} = current_setting('app.current_user_id', true)::uuid);
                    """))
                    
                    # CREATE DELETE POLICY: Users can only delete their own data
                    conn.execute(text(f"""
                        CREATE POLICY user_delete_policy ON {table_name}
                        FOR DELETE
                        USING ({user_col} = current_setting('app.current_user_id', true)::uuid);
                    """))
                    
                    logger.info(f"  ✅ RLS policies configured for {table_name}")
                    
                except Exception as e:
                    logger.warning(f"  ⚠️  Failed to configure RLS for {table_name}: {str(e)[:150]}")
                    # Continue with other tables even if one fails
                    continue
        
        logger.info("✅ RLS policies setup completed")
        
    except Exception as e:
        logger.error(f"❌ Failed to setup RLS policies: {e}")
        raise



if __name__ == "__main__":
    run_migrations()