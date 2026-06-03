"""
Migration script to add knowledge_base table and update rag_document.
"""
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from db.pgsql import get_write_db
from sqlalchemy import text


async def add_knowledge_base_table():
    """Add knowledge_base table and update rag_document."""
    
    create_extension_sql = """
    CREATE EXTENSION IF NOT EXISTS vchord CASCADE;
    """
    
    create_kb_table_sql = """
    CREATE TABLE IF NOT EXISTS knowledge_base (
        id VARCHAR(36) PRIMARY KEY NOT NULL,
        "sessionId" VARCHAR(36) NOT NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        "azureFolderPath" VARCHAR(512) NOT NULL UNIQUE,
        "chunkTableName" VARCHAR(128) NOT NULL UNIQUE,
        "chunkingConfig" TEXT NOT NULL,
        "embeddingModel" VARCHAR(50) NOT NULL,
        "vectorDimension" INTEGER NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'creating',
        "documentCount" INTEGER NOT NULL DEFAULT 0,
        "chunkCount" INTEGER NOT NULL DEFAULT 0,
        "totalSizeBytes" BIGINT NOT NULL DEFAULT 0,
        metadata TEXT,
        "createdBy" VARCHAR(36),
        "createdAt" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        "updatedAt" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        "deletedAt" TIMESTAMP
    );
    """
    
    
    alter_document_table_sql = """
    ALTER TABLE rag_document 
    ADD COLUMN IF NOT EXISTS "kbId" VARCHAR(36);
    """
    
    try:
        async for db in get_write_db():
            print("Creating VectorChord extension...")
            await db.execute(text(create_extension_sql))
            
            print("Creating knowledge_base table...")
            await db.execute(text(create_kb_table_sql))
            
            print("Creating indexes...")
            await db.execute(text('CREATE INDEX IF NOT EXISTS idx_knowledge_base_session ON knowledge_base("sessionId");'))
            await db.execute(text('CREATE INDEX IF NOT EXISTS idx_knowledge_base_status ON knowledge_base(status);'))
            await db.execute(text('CREATE INDEX IF NOT EXISTS idx_knowledge_base_name ON knowledge_base(name);'))
            
            print("Updating rag_document table...")
            await db.execute(text(alter_document_table_sql))
            await db.execute(text('CREATE INDEX IF NOT EXISTS idx_rag_document_kb ON rag_document("kbId");'))
            
            await db.commit()
            
            print("✅ Successfully created knowledge_base table and updated rag_document")
            break
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise


async def main():
    """Run the migration."""
    print("=" * 60)
    print("Knowledge Base Table Migration")
    print("=" * 60)
    
    await add_knowledge_base_table()
    
    print("\n✅ Migration completed successfully")
    print("\nNote: Dynamic chunk tables will be created per knowledge base")


if __name__ == "__main__":
    asyncio.run(main())

