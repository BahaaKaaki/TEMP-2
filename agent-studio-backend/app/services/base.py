"""
Base service with common patterns.
"""
from typing import TypeVar
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar('T')


class BaseService:
    """Base service with common patterns."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def commit(self) -> None:
        """Commit database transaction."""
        await self.db.commit()
    
    async def rollback(self) -> None:
        """Rollback database transaction."""
        await self.db.rollback()

