"""
Base repository with common CRUD operations.
"""
from typing import TypeVar, Generic, Optional, List, Type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

T = TypeVar('T')
DomainT = TypeVar('DomainT')


class BaseRepository(Generic[T, DomainT]):
    """Base repository with common database operations."""
    
    def __init__(self, db: AsyncSession, model: Type[T]):
        self.db = db
        self.model = model
    
    async def get_by_id(self, id: any) -> Optional[T]:
        """Get entity by ID."""
        query = select(self.model).where(self.model.id == id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100
    ) -> List[T]:
        """Get all entities with pagination."""
        query = select(self.model).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def count(self) -> int:
        """Count total entities."""
        query = select(func.count(self.model.id))
        result = await self.db.execute(query)
        return result.scalar()
    
    async def create(self, entity: T) -> T:
        """Create new entity."""
        self.db.add(entity)
        await self.db.flush()
        # Note: flush() ensures entity is persisted and IDs are populated
        # refresh() is not needed and can cause session state issues
        return entity
    
    async def update(self, entity: T) -> T:
        """Update existing entity."""
        await self.db.flush()
        # Note: flush() ensures changes are persisted
        # refresh() can cause session state issues
        return entity
    
    async def delete(self, entity: T) -> None:
        """Delete entity."""
        await self.db.delete(entity)
        await self.db.flush()
    
    async def commit(self) -> None:
        """Commit transaction."""
        await self.db.commit()
    
    async def rollback(self) -> None:
        """Rollback transaction."""
        await self.db.rollback()

