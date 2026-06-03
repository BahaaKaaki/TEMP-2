"""
Add vizMetadata column to agent_deliverable table

This migration adds support for storing visualization metadata
with deliverables to enable smart data visualization in the UI.
"""
import asyncio
import logging
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text
from app.db.pgsql import get_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def upgrade():
    """Add vizMetadata column to agent_deliverable table."""
    engine = await get_engine()
    
    async with engine.begin() as conn:
        # Check if column already exists
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='agent_deliverable' 
            AND column_name='vizMetadata'
        """))
        
        if result.fetchone():
            logger.info("✓ vizMetadata column already exists, skipping migration")
            return
        
        logger.info("Adding vizMetadata column to agent_deliverable table...")
        
        await conn.execute(text("""
            ALTER TABLE agent_deliverable
            ADD COLUMN "vizMetadata" TEXT NULL
        """))
        
        logger.info("✓ Successfully added vizMetadata column")


async def downgrade():
    """Remove vizMetadata column from agent_deliverable table."""
    engine = await get_engine()
    
    async with engine.begin() as conn:
        logger.info("Removing vizMetadata column from agent_deliverable table...")
        
        await conn.execute(text("""
            ALTER TABLE agent_deliverable
            DROP COLUMN IF EXISTS "vizMetadata"
        """))
        
        logger.info("✓ Successfully removed vizMetadata column")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "downgrade":
        asyncio.run(downgrade())
    else:
        asyncio.run(upgrade())

