"""
Migration script to add rag_document table for RAG capabilities.
"""
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from db.pgsql import get_write_db
from sqlalchemy import text


async def add_rag_document_table():
    """Add rag_document table to the database."""
    
    create_table_sql = """
    CREATE EXTENSION IF NOT EXISTS vchord CASCADE;
    
    CREATE TABLE IF NOT EXISTS rag_document (
        id VARCHAR(36) PRIMARY KEY NOT NULL,
        "sessionId" VARCHAR(36) NOT NULL,
        "blobName" VARCHAR(512) NOT NULL UNIQUE,
        "containerName" VARCHAR(255) NOT NULL,
        "blobUrl" VARCHAR(1024),
        "fileName" VARCHAR(255) NOT NULL,
        "fileType" VARCHAR(50) NOT NULL,
        "fileSize" BIGINT NOT NULL,
        "mimeType" VARCHAR(100),
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        "processingError" TEXT,
        "extractedText" TEXT,
        "chunkCount" INTEGER DEFAULT 0,
        "embeddingStatus" VARCHAR(20),
        embedding vector(1536),
        metadata TEXT,
        "uploadedBy" VARCHAR(36),
        "createdAt" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        "updatedAt" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        "deletedAt" TIMESTAMP
    );
    """
    
    
    try:
        async for db in get_write_db():
            print("Creating rag_document table...")
            await db.execute(text(create_table_sql))
            
            print("Creating indexes...")
            await db.execute(text('CREATE INDEX IF NOT EXISTS idx_rag_document_session ON rag_document("sessionId");'))
            await db.execute(text('CREATE INDEX IF NOT EXISTS idx_rag_document_status ON rag_document(status);'))
            await db.execute(text('CREATE INDEX IF NOT EXISTS idx_rag_document_blob ON rag_document("blobName");'))
            
            await db.commit()
            
            print("✅ Successfully created rag_document table and indexes")
            break
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise


async def main():
    """Run the migration."""
    print("=" * 60)
    print("RAG Document Table Migration")
    print("=" * 60)
    
    await add_rag_document_table()
    
    print("\n✅ Migration completed successfully")


if __name__ == "__main__":
    asyncio.run(main())

