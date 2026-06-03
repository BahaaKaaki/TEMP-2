"""
Migration: Add marketplace_submission table for approval workflow

This migration creates the marketplace_submission table to track workflow
submissions for marketplace approval.

Run with: python migrations/add_marketplace_submission_table.py
"""
import asyncio
import logging
import os
import sys
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config.settings import settings

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Construct database URL using ADMIN credentials for migration
def get_admin_database_url():
    """Get database URL with admin credentials."""
    user = os.getenv('POSTGRES_ADMIN_USER', os.getenv('POSTGRES_USER', 'sa'))
    password = os.getenv('POSTGRES_ADMIN_PASSWORD', os.getenv('POSTGRES_PASSWORD', 'anypass123!!'))
    host = os.getenv('POSTGRES_HOST', 'localhost')
    port = os.getenv('POSTGRES_PORT', '5432')
    db = os.getenv('POSTGRES_DB', 'agent-builder')
    
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


async def run_migration():
    """Run the migration to add marketplace_submission table."""
    
    database_url = get_admin_database_url()
    logger.info(f"Connecting to database...")
    
    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        try:
            # Check if table already exists
            result = await session.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'marketplace_submission'
                );
            """))
            exists = result.scalar()
            
            if exists:
                logger.info("✓ marketplace_submission table already exists, skipping creation")
            else:
                logger.info("Creating marketplace_submission table...")
                
                # Create the table
                await session.execute(text("""
                    CREATE TABLE marketplace_submission (
                        id VARCHAR(36) PRIMARY KEY NOT NULL,
                        "workflowId" VARCHAR(36) NOT NULL REFERENCES workflow_entity(id),
                        "submittedById" VARCHAR(36) NOT NULL REFERENCES "user"(id),
                        "marketplaceName" VARCHAR(255) NOT NULL,
                        "marketplaceDescription" TEXT,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        "reviewedById" VARCHAR(36) REFERENCES "user"(id),
                        "reviewedAt" TIMESTAMP,
                        "rejectionReason" TEXT,
                        "createdAt" TIMESTAMP NOT NULL DEFAULT NOW(),
                        "updatedAt" TIMESTAMP NOT NULL DEFAULT NOW()
                    );
                """))
                
                logger.info("✓ marketplace_submission table created")
                
                # Create indexes
                await session.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_marketplace_submission_workflow 
                    ON marketplace_submission("workflowId");
                """))
                
                await session.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_marketplace_submission_submitter 
                    ON marketplace_submission("submittedById");
                """))
                
                await session.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_marketplace_submission_status 
                    ON marketplace_submission(status);
                """))
                
                logger.info("✓ Indexes created")
            
            # Enable RLS on the table
            logger.info("Configuring RLS policies...")
            
            await session.execute(text("""
                ALTER TABLE marketplace_submission ENABLE ROW LEVEL SECURITY;
            """))
            
            await session.execute(text("""
                ALTER TABLE marketplace_submission FORCE ROW LEVEL SECURITY;
            """))
            
            # Drop existing policies if any
            await session.execute(text("""
                DROP POLICY IF EXISTS user_isolation_policy ON marketplace_submission;
            """))
            await session.execute(text("""
                DROP POLICY IF EXISTS user_insert_policy ON marketplace_submission;
            """))
            await session.execute(text("""
                DROP POLICY IF EXISTS user_modify_policy ON marketplace_submission;
            """))
            await session.execute(text("""
                DROP POLICY IF EXISTS user_delete_policy ON marketplace_submission;
            """))
            await session.execute(text("""
                DROP POLICY IF EXISTS admin_view_all_submissions ON marketplace_submission;
            """))
            
            # Create SELECT policy: Users see their own OR admins see all
            await session.execute(text("""
                CREATE POLICY user_isolation_policy ON marketplace_submission
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
            
            # Create INSERT policy
            await session.execute(text("""
                CREATE POLICY user_insert_policy ON marketplace_submission
                FOR INSERT
                WITH CHECK (true);
            """))
            
            # Create UPDATE policy: Users can update their own OR admins can update all
            await session.execute(text("""
                CREATE POLICY user_modify_policy ON marketplace_submission
                FOR UPDATE
                USING (
                    "submittedById" = current_setting('app.current_user_id', true)
                    OR EXISTS (
                        SELECT 1 FROM "user" u 
                        WHERE u.id = current_setting('app.current_user_id', true)
                        AND u."roleSlug" LIKE '%admin%'
                    )
                );
            """))
            
            # Create DELETE policy
            await session.execute(text("""
                CREATE POLICY user_delete_policy ON marketplace_submission
                FOR DELETE
                USING ("submittedById" = current_setting('app.current_user_id', true));
            """))
            
            logger.info("✓ RLS policies configured")
            
            await session.commit()
            logger.info("✓ Migration completed successfully!")
            
        except Exception as e:
            logger.error(f"Migration failed: {str(e)}")
            await session.rollback()
            raise
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
