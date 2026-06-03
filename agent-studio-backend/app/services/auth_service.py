"""
Authentication service for user management and authentication.

Handles user registration, login, token management, and profile operations.
"""
import secrets
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError

from db.models import AdGroup, MicrosoftOAuthToken, User, UserGroup, AuthProvider
from repositories.user_repository import UserRepository
from utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token
)
from core.exceptions import (
    DomainException,
    NotFoundException
)
from config.settings import settings

logger = logging.getLogger(__name__)

REFRESH_TOKEN_PREFIX = "refresh_jti:"


class AuthenticationException(DomainException):
    """Raised when authentication fails."""
    pass


class EmailAlreadyExistsException(DomainException):
    """Raised when attempting to register with an existing email."""
    pass


class InvalidCredentialsException(AuthenticationException):
    """Raised when login credentials are invalid."""
    pass


class InvalidTokenException(AuthenticationException):
    """Raised when token validation fails."""
    pass


class DisabledAccountException(AuthenticationException):
    """Raised when attempting to access a disabled account."""
    pass


class AuthService:
    """Service for authentication and user management operations."""
    
    def __init__(self, db: AsyncSession, user_repo: UserRepository):
        self.db = db
        self.user_repo = user_repo
    
    async def register(
        self,
        email: str,
        password: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None
    ) -> User:
        """
        Register a new user with email and password.
        
        Args:
            email: User's email address
            password: Plain text password (will be hashed)
            first_name: User's first name
            last_name: User's last name
            
        Returns:
            Created User entity
            
        Raises:
            EmailAlreadyExistsException: If email is already registered
        """
        # Check if email already exists
        if await self.user_repo.email_exists(email):
            raise EmailAlreadyExistsException(f"Email {email} is already registered")
        
        # Create new user
        user = User(
            id=str(uuid.uuid4()),
            email=email.lower(),
            password=hash_password(password),
            firstName=first_name,
            lastName=last_name,
            authProvider=AuthProvider.LOCAL,
            disabled=False,
            mfaEnabled=False,
            roleSlug='global:member',
            createdAt=datetime.utcnow(),
            updatedAt=datetime.utcnow()
        )
        
        created_user = await self.user_repo.create(user)
        await self.db.commit()
        
        return created_user
    
    async def authenticate(self, email: str, password: str) -> User:
        """
        Authenticate user with email and password.
        
        Args:
            email: User's email address
            password: Plain text password
            
        Returns:
            Authenticated User entity
            
        Raises:
            InvalidCredentialsException: If credentials are invalid
            DisabledAccountException: If account is disabled
        """
        # Get user by email
        user = await self.user_repo.get_by_email(email)
        
        if not user:
            raise InvalidCredentialsException("Invalid email or password")
        
        # Check if account is disabled
        if user.disabled:
            raise DisabledAccountException("Account is disabled")
        
        # Verify password (only for local auth users)
        if user.authProvider == AuthProvider.LOCAL:
            if not user.password or not verify_password(password, user.password):
                raise InvalidCredentialsException("Invalid email or password")
        else:
            raise InvalidCredentialsException(f"Please login with {user.authProvider.value}")
        
        # Update last active timestamp
        user.lastActiveAt = datetime.utcnow()
        await self.db.commit()
        
        return user
    
    async def create_tokens(
        self,
        user: User,
    ) -> Tuple[str, str]:
        """
        Create access and refresh tokens for a user.
        Stores the refresh token JTI in Redis for revocation tracking.

        NOTE: AD group memberships are intentionally NOT embedded in the JWT.
        Enterprise users can be members of hundreds of groups; embedding them
        would inflate the token past common Authorization-header size limits
        (~8KB on Azure Container Apps ingress, NGINX, etc.) and cause the
        token to be truncated mid-flight. Instead, ``get_db_with_user_context``
        looks them up from the ``user_group`` table on every request, which
        also means group-add/remove takes effect immediately rather than at
        the next token refresh.

        Returns:
            Tuple of (access_token, refresh_token)
        """
        token_data = {
            "sub": user.id,
            "email": user.email,
            "role": user.roleSlug,
        }

        jti = secrets.token_urlsafe(32)
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token({"sub": user.id}, jti=jti)
        
        try:
            from db.redis import get_redis
            redis = await get_redis()
            ttl = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
            await redis.set(f"{REFRESH_TOKEN_PREFIX}{jti}", user.id, ex=ttl)
        except Exception:
            logger.warning("Redis unavailable — refresh token stored without server-side tracking")
        
        return access_token, refresh_token
    
    async def refresh_access_token(self, refresh_token: str) -> Tuple[str, str]:
        """
        Validate a refresh token, rotate it, and return new tokens.
        
        Returns:
            Tuple of (new_access_token, new_refresh_token)
            
        Raises:
            InvalidTokenException: If refresh token is invalid or revoked
        """
        try:
            payload = verify_token(refresh_token, token_type="refresh")
            user_id = payload.get("sub")
            old_jti = payload.get("jti")
            
            if not user_id:
                raise InvalidTokenException("Invalid token payload")
            
            if old_jti:
                try:
                    from db.redis import get_redis
                    redis = await get_redis()
                    stored = await redis.get(f"{REFRESH_TOKEN_PREFIX}{old_jti}")
                    if stored is None:
                        raise InvalidTokenException("Refresh token has been revoked")
                    await redis.delete(f"{REFRESH_TOKEN_PREFIX}{old_jti}")
                except InvalidTokenException:
                    raise
                except Exception:
                    logger.warning("Redis unavailable — skipping server-side revocation check")
            
            user = await self.user_repo.get_by_id(user_id)
            if not user:
                raise InvalidTokenException("User not found")
            if user.disabled:
                raise DisabledAccountException("Account is disabled")
            
            # Group memberships are NOT embedded in the JWT (see note in
            # create_tokens). RLS context is populated per-request from
            # the user_group table by get_db_with_user_context.
            token_data = {
                "sub": user.id,
                "email": user.email,
                "role": user.roleSlug,
            }

            new_jti = secrets.token_urlsafe(32)
            new_access_token = create_access_token(token_data)
            new_refresh_token = create_refresh_token({"sub": user.id}, jti=new_jti)
            
            try:
                from db.redis import get_redis
                redis = await get_redis()
                ttl = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
                await redis.set(f"{REFRESH_TOKEN_PREFIX}{new_jti}", user.id, ex=ttl)
            except Exception:
                logger.warning("Redis unavailable — new refresh token stored without server-side tracking")
            
            return new_access_token, new_refresh_token
            
        except (InvalidTokenException, DisabledAccountException):
            raise
        except JWTError as e:
            raise InvalidTokenException(f"Invalid refresh token: {str(e)}")

    async def revoke_refresh_token(self, refresh_token: str) -> None:
        """Revoke a refresh token by deleting its JTI from Redis."""
        try:
            payload = verify_token(refresh_token, token_type="refresh")
            jti = payload.get("jti")
            if jti:
                from db.redis import get_redis
                redis = await get_redis()
                await redis.delete(f"{REFRESH_TOKEN_PREFIX}{jti}")
        except Exception:
            pass
    
    async def get_user_by_id(self, user_id: str) -> User:
        """
        Get user by ID.
        
        Args:
            user_id: User UUID
            
        Returns:
            User entity
            
        Raises:
            NotFoundException: If user not found
        """
        user = await self.user_repo.get_by_id(user_id)
        
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        
        return user
    
    async def update_password(self, user_id: str, current_password: str, new_password: str) -> None:
        """
        Update user password.
        
        Args:
            user_id: User UUID
            current_password: Current password for verification
            new_password: New password to set
            
        Raises:
            InvalidCredentialsException: If current password is incorrect
        """
        user = await self.get_user_by_id(user_id)
        
        # Verify current password
        if not user.password or not verify_password(current_password, user.password):
            raise InvalidCredentialsException("Current password is incorrect")
        
        # Update password
        user.password = hash_password(new_password)
        user.updatedAt = datetime.utcnow()
        
        await self.db.commit()
    
    async def find_or_create_microsoft_user(
        self,
        external_id: str,
        email: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        groups: Optional[List[Tuple[str, Optional[str]]]] = None,
    ) -> User:
        """
        Find an existing user by Microsoft external ID or email, or create a new one.

        Lookup order:
        1. By externalId (returning Microsoft user)
        2. By email (link Microsoft identity to existing local account)
        3. Create new user with authProvider=MICROSOFT

        If `groups` is provided (list of ``(group_id, display_name)`` tuples
        from Microsoft Graph), the user_group / ad_group tables are
        replace-all-synced for this user so RLS sees the latest membership.
        """
        user = await self.user_repo.get_by_external_id(AuthProvider.MICROSOFT, external_id)
        if user:
            if user.disabled:
                raise DisabledAccountException("Account is disabled")
            user.lastActiveAt = datetime.utcnow()
            if groups is not None:
                await self._sync_user_groups(user.id, groups)
            await self.db.commit()
            return user

        user = await self.user_repo.get_by_email(email.lower())
        if user:
            if user.disabled:
                raise DisabledAccountException("Account is disabled")
            user.authProvider = AuthProvider.MICROSOFT
            user.externalId = external_id
            user.lastActiveAt = datetime.utcnow()
            if groups is not None:
                await self._sync_user_groups(user.id, groups)
            await self.db.commit()
            return user

        user = User(
            id=str(uuid.uuid4()),
            email=email.lower(),
            password=None,
            firstName=first_name,
            lastName=last_name,
            authProvider=AuthProvider.MICROSOFT,
            externalId=external_id,
            disabled=False,
            mfaEnabled=False,
            roleSlug='global:member',
            createdAt=datetime.utcnow(),
            updatedAt=datetime.utcnow(),
        )
        created_user = await self.user_repo.create(user)
        if groups is not None:
            await self._sync_user_groups(created_user.id, groups)
        await self.db.commit()
        return created_user

    async def _get_user_group_ids(self, user_id: str) -> List[str]:
        """Return the cached AD group GUIDs for a user (for token claims)."""
        result = await self.db.execute(
            select(UserGroup.groupId).where(UserGroup.userId == user_id)
        )
        return [row[0] for row in result.all()]

    async def _sync_user_groups(
        self,
        user_id: str,
        groups: List[Tuple[str, Optional[str]]],
    ) -> None:
        """
        Replace-all sync of a user's AD group memberships.

        Args:
            user_id:  the local user.id
            groups:   list of ``(group_id, display_name)`` from MS Graph.
                      ``display_name`` is optional — if None, we keep
                      whatever cached display name we already have.
        """
        # Validate / dedupe ids early so we don't crash deep in commit().
        seen: set[str] = set()
        clean: List[Tuple[str, Optional[str]]] = []
        for gid, name in groups:
            if not gid:
                continue
            try:
                uuid.UUID(str(gid))
            except (ValueError, TypeError):
                logger.warning("Dropping malformed AD group id %r", gid)
                continue
            if gid in seen:
                continue
            seen.add(gid)
            clean.append((str(gid), name))

        # 1. Upsert ad_group cache rows
        if clean:
            existing = await self.db.execute(
                select(AdGroup).where(AdGroup.id.in_([g for g, _ in clean]))
            )
            existing_by_id = {ag.id: ag for ag in existing.scalars().all()}
            now = datetime.utcnow()
            for gid, name in clean:
                if gid in existing_by_id:
                    if name and existing_by_id[gid].displayName != name:
                        existing_by_id[gid].displayName = name
                    existing_by_id[gid].lastSyncedAt = now
                else:
                    self.db.add(AdGroup(
                        id=gid,
                        displayName=name,
                        lastSyncedAt=now,
                        createdAt=now,
                    ))
            # Flush so the user_group FK targets exist before we insert.
            await self.db.flush()

        # 2. Replace-all the user's memberships
        await self.db.execute(
            delete(UserGroup).where(UserGroup.userId == user_id)
        )
        for gid, _ in clean:
            self.db.add(UserGroup(
                userId=user_id,
                groupId=gid,
                addedAt=datetime.utcnow(),
            ))

    # ------------------------------------------------------------------
    # Microsoft OAuth refresh-token storage
    # ------------------------------------------------------------------
    # We persist each user's MS refresh token so that delegated Graph calls
    # (e.g. share-dialog group typeahead) can mint a fresh access token on
    # demand without having to redirect the user through SSO again.
    #
    # The plaintext refresh token is wrapped via Fernet (utils.token_crypto)
    # before being stored, and the ms_oauth_token table has owner-only RLS
    # without an admin override. See db/init_security.py.

    async def upsert_ms_refresh_token(
        self,
        user_id: str,
        refresh_token: str,
        scopes: List[str],
    ) -> None:
        """
        Encrypt and persist (or replace) the Microsoft OAuth refresh token
        for ``user_id``. Callers MUST have already set the RLS context
        (app.current_user_id) for this user, otherwise the INSERT/UPDATE
        will be rejected by the owner-only policy.
        """
        from utils.token_crypto import get_token_crypto

        if not refresh_token:
            return

        try:
            crypto = get_token_crypto()
        except RuntimeError as e:
            # MS_TOKEN_ENCRYPTION_KEY not set — log loudly but don't crash
            # the login flow. Group typeahead simply won't work for this
            # user; everything else (login, group-based RLS, sharing UI)
            # still functions because we already have the groups in JWT.
            logger.error(
                "Cannot persist MS refresh token for user %s: %s",
                user_id, e,
            )
            return

        encrypted = crypto.encrypt(refresh_token)
        scopes_str = ",".join(sorted(set(scopes)))
        now = datetime.utcnow()

        existing = await self.db.execute(
            select(MicrosoftOAuthToken).where(
                MicrosoftOAuthToken.userId == user_id
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            self.db.add(MicrosoftOAuthToken(
                userId=user_id,
                refreshTokenEncrypted=encrypted,
                scopes=scopes_str,
                createdAt=now,
                updatedAt=now,
            ))
        else:
            row.refreshTokenEncrypted = encrypted
            row.scopes = scopes_str
            row.updatedAt = now
        await self.db.commit()

    async def get_ms_refresh_token(self, user_id: str) -> Optional[str]:
        """
        Return the decrypted Microsoft refresh token for ``user_id``, or
        None if the user has none stored / decryption fails / encryption
        key isn't configured.
        """
        from utils.token_crypto import get_token_crypto

        result = await self.db.execute(
            select(MicrosoftOAuthToken).where(
                MicrosoftOAuthToken.userId == user_id
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None

        try:
            crypto = get_token_crypto()
        except RuntimeError as e:
            logger.error("MS_TOKEN_ENCRYPTION_KEY missing — cannot decrypt: %s", e)
            return None

        return crypto.decrypt(row.refreshTokenEncrypted)

    async def delete_ms_refresh_token(self, user_id: str) -> None:
        """Drop the user's stored MS refresh token (e.g. on logout)."""
        await self.db.execute(
            delete(MicrosoftOAuthToken).where(
                MicrosoftOAuthToken.userId == user_id
            )
        )
        await self.db.commit()

    async def update_profile(
        self,
        user_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None
    ) -> User:
        """
        Update user profile information.
        
        Args:
            user_id: User UUID
            first_name: New first name (optional)
            last_name: New last name (optional)
            
        Returns:
            Updated User entity
        """
        user = await self.get_user_by_id(user_id)
        
        if first_name is not None:
            user.firstName = first_name
        
        if last_name is not None:
            user.lastName = last_name
        
        user.updatedAt = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(user)
        
        return user
