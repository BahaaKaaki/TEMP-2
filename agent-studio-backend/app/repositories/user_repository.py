"""
User repository for database operations.

Handles CRUD operations for User entities following the existing repository pattern.
"""
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User, AuthProvider
from repositories.base import BaseRepository


class UserRepository(BaseRepository[User, User]):
    """Repository for User entity database operations."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, User)
    
    async def get_by_email(self, email: str) -> Optional[User]:
        """
        Get user by email address.
        
        Args:
            email: User's email address
            
        Returns:
            User entity if found, None otherwise
        """
        query = select(User).where(User.email == email.lower())
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_external_id(self, provider: AuthProvider, external_id: str) -> Optional[User]:
        """
        Get user by external provider ID (for OAuth users).
        
        Args:
            provider: Authentication provider enum
            external_id: External user ID from the provider
            
        Returns:
            User entity if found, None otherwise
        """
        query = select(User).where(
            User.authProvider == provider,
            User.externalId == external_id
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def email_exists(self, email: str) -> bool:
        """
        Check if an email is already registered.
        
        Args:
            email: Email address to check
            
        Returns:
            True if email exists, False otherwise
        """
        user = await self.get_by_email(email)
        return user is not None
    
    async def update_last_active(self, user_id: str) -> None:
        """
        Update user's last active timestamp.
        Only updates if more than 5 minutes have passed since last update
        to avoid database contention on high-frequency requests.
        
        Args:
            user_id: UUID of the user
        """
        from datetime import datetime, timedelta
        user = await self.get_by_id(user_id)
        if user:
            # Only update if last update was more than 5 minutes ago
            now = datetime.utcnow()
            if user.lastActiveAt is None or (now - user.lastActiveAt) > timedelta(minutes=5):
                user.lastActiveAt = now
                await self.db.flush()
