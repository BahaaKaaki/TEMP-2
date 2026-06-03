import sys
import asyncio
import logging
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from db.pgsql import admin_engine, primary_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

STATEMENTS = [
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'knowledge_base' AND column_name = 'metadataSchema'
        ) THEN
            ALTER TABLE knowledge_base ADD COLUMN "metadataSchema" TEXT;
        END IF;
    END $$
    """,

    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'knowledge_base' AND column_name = 'hasStructuredData'
        ) THEN
            ALTER TABLE knowledge_base ADD COLUMN "hasStructuredData" BOOLEAN NOT NULL DEFAULT false;
        END IF;
    END $$
    """,

    """ALTER TABLE rag_document ALTER COLUMN status TYPE VARCHAR(30)""",

    """
    CREATE TABLE IF NOT EXISTS structured_table (
        id              VARCHAR(36) PRIMARY KEY NOT NULL,
        kb_id           VARCHAR(36) NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
        document_id     VARCHAR(36) NOT NULL REFERENCES rag_document(id) ON DELETE CASCADE,
        schema_name     VARCHAR(128) NOT NULL,
        table_name      VARCHAR(128) NOT NULL,
        display_name    VARCHAR(255) NOT NULL,
        description     TEXT,
        row_count       INTEGER NOT NULL DEFAULT 0,
        source_sheet    VARCHAR(255),
        status          VARCHAR(20) NOT NULL DEFAULT 'pending_review',
        created_by      VARCHAR(36),
        created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,

    """CREATE INDEX IF NOT EXISTS idx_structured_table_kb  ON structured_table(kb_id)""",
    """CREATE INDEX IF NOT EXISTS idx_structured_table_doc ON structured_table(document_id)""",

    """
    CREATE TABLE IF NOT EXISTS structured_column (
        id              VARCHAR(36) PRIMARY KEY NOT NULL,
        table_id        VARCHAR(36) NOT NULL REFERENCES structured_table(id) ON DELETE CASCADE,
        column_name     VARCHAR(128) NOT NULL,
        display_name    VARCHAR(255) NOT NULL,
        data_type       VARCHAR(20) NOT NULL DEFAULT 'text',
        description     TEXT,
        column_order    INTEGER NOT NULL DEFAULT 0,
        nullable        BOOLEAN NOT NULL DEFAULT true,
        created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,

    """CREATE INDEX IF NOT EXISTS idx_structured_column_table ON structured_column(table_id)""",

    """
    CREATE TABLE IF NOT EXISTS structured_relationship (
        id                VARCHAR(36) PRIMARY KEY NOT NULL,
        kb_id             VARCHAR(36) NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
        source_table_id   VARCHAR(36) NOT NULL REFERENCES structured_table(id) ON DELETE CASCADE,
        source_column_id  VARCHAR(36) NOT NULL REFERENCES structured_column(id) ON DELETE CASCADE,
        target_table_id   VARCHAR(36) NOT NULL REFERENCES structured_table(id) ON DELETE CASCADE,
        target_column_id  VARCHAR(36) NOT NULL REFERENCES structured_column(id) ON DELETE CASCADE,
        relationship_type VARCHAR(20) NOT NULL DEFAULT 'one_to_many',
        created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_relationship_columns UNIQUE (source_column_id, target_column_id),
        CONSTRAINT chk_different_tables   CHECK  (source_table_id != target_table_id)
    )
    """,

    """CREATE INDEX IF NOT EXISTS idx_structured_rel_kb ON structured_relationship(kb_id)""",
]


async def apply_migration():
    engine = admin_engine or primary_engine
    logger.info("Applying structured data tables migration...")
    async with engine.begin() as conn:
        for i, stmt in enumerate(STATEMENTS, 1):
            await conn.execute(text(stmt))
            logger.info(f"  Statement {i}/{len(STATEMENTS)} done.")
    logger.info("Migration applied successfully.")


if __name__ == "__main__":
    asyncio.run(apply_migration())
