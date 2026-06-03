"""
Create Langfuse database in existing PostgreSQL instance
Run this before starting langfuse service
"""
import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def create_langfuse_database():
    """Create langfuse database if it doesn't exist"""
    
    # Connect to default postgres database
    conn = await asyncpg.connect(
        host=os.getenv('DATABASE_HOST', 'localhost'),
        port=5432,
        user=os.getenv('POSTGRES_USER', 'sa'),
        password=os.getenv('POSTGRES_PASSWORD'),
        database='postgres'
    )
    
    try:
        # Check if langfuse database exists
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'langfuse'"
        )
        
        if not exists:
            print("Creating langfuse database...")
            await conn.execute("CREATE DATABASE langfuse")
            print("✓ Langfuse database created successfully")
        else:
            print("✓ Langfuse database already exists")
            
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(create_langfuse_database())

