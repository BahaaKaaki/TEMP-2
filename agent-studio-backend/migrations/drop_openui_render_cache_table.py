"""
Drop openui_render_cache table.

PR #20's earlier iteration cached translated OpenUI Lang in a separate
content-hashed table. The cache lifecycle has been replaced by an
``openuiLang`` column on ``agent_deliverable`` (see
``add_openui_lang_column.py``); this migration removes the now-unused
table for environments that already created it. Idempotent.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from sqlalchemy import text
from app.db.pgsql import get_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def upgrade():
    """Drop the openui_render_cache table if it exists."""
    engine = await get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT 1
            FROM information_schema.tables
            WHERE table_name='openui_render_cache'
        """))

        if not result.fetchone():
            logger.info("✓ openui_render_cache table not present, skipping migration")
            return

        logger.info("Dropping openui_render_cache table...")
        await conn.execute(text('DROP TABLE IF EXISTS openui_render_cache CASCADE'))
        logger.info("✓ Successfully dropped openui_render_cache table")


async def downgrade():
    """No-op. The table's contents cannot be reconstructed."""
    logger.info("downgrade() is a no-op for drop_openui_render_cache_table")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "downgrade":
        asyncio.run(downgrade())
    else:
        asyncio.run(upgrade())
