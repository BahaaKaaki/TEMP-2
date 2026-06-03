"""
Quick script to create User table if it doesn't exist.
"""
import asyncio
import os
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.models import Base, User

# Load environment variables
load_dotenv()

DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
DB_NAME = os.getenv("POSTGRES_DB", "agent_studio")
DB_HOST = os.getenv("DATABASE_PRIMARY_HOST", "postgres")

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:5432/{DB_NAME}"


async def main():
    """Create User table."""
    print("Creating User table...")
    print(f"Database URL: postgresql://{DB_USER}:***@{DB_HOST}:5432/{DB_NAME}")
    
    engine = create_async_engine(DATABASE_URL, echo=True)
    
    async with engine.begin() as conn:
        # Create only the User table
        await conn.run_sync(User.metadata.create_all)
    
    print("\nUser table created successfully!")
    print("\nChecking tables...")
    
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await session.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """))
        tables = result.scalars().all()
        print(f"\nExisting tables: {tables}")
        
        # Check if user table exists
        if 'user' in tables:
            result = await session.execute(text("SELECT COUNT(*) FROM \"user\""))
            count = result.scalar()
            print(f"\nUsers in database: {count}")
        else:
            print("\nWARNING: 'user' table not found!")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
