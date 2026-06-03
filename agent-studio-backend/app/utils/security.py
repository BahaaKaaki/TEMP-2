"""
Authentication and security utilities.

Provides password hashing, JWT token generation and validation for user authentication.
"""
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt
from config.settings import settings

logger = logging.getLogger(__name__)

# Password hasher using Argon2id (modern, secure, no length limits)
ph = PasswordHasher()


def hash_password(password: str) -> str:
    """
    Hash a password using Argon2id.
    
    Args:
        password: Plain text password to hash
        
    Returns:
        Hashed password string
    """
    return ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.
    
    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to compare against
        
    Returns:
        True if password matches, False otherwise
    """
    try:
        ph.verify(hashed_password, plain_password)
        return True
    except VerifyMismatchError:
        return False


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Payload data to encode in the token (typically {"sub": user_id})
        expires_delta: Optional custom expiration time
        
    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(data: Dict[str, Any], jti: Optional[str] = None) -> str:
    """
    Create a JWT refresh token with longer expiration.
    
    Args:
        data: Payload data to encode in the token (typically {"sub": user_id})
        jti: Unique token identifier for revocation tracking
        
    Returns:
        Encoded JWT refresh token string
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    
    if jti is None:
        jti = secrets.token_urlsafe(32)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh",
        "jti": jti,
    })
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


_OAUTH_CODE_ATTEMPTS = 10


async def generate_oauth_code(user_id: str) -> str:
    """Generate a one-time authorization code and store the user_id in Redis.

    Azure Redis Enterprise (OSS cluster mode) may return MOVED errors for
    keys whose hash slot lives on another shard.  Each random code hashes
    to a different slot, so we retry with fresh codes until one lands on a
    reachable shard.
    """
    from db.redis import get_redis
    redis = await get_redis()
    last_err: Optional[Exception] = None
    for attempt in range(_OAUTH_CODE_ATTEMPTS):
        code = secrets.token_urlsafe(48)
        try:
            await redis.set(
                f"oauth_code:{code}",
                user_id,
                ex=settings.OAUTH_CODE_TTL_SECONDS,
            )
            return code
        except Exception as exc:
            last_err = exc
            if attempt < _OAUTH_CODE_ATTEMPTS - 1:
                logger.warning(
                    "OAuth code storage failed (attempt %d/%d), trying new code",
                    attempt + 1, _OAUTH_CODE_ATTEMPTS,
                )
            else:
                logger.exception("Failed to store OAuth code after %d attempts", _OAUTH_CODE_ATTEMPTS)
    raise last_err  # type: ignore[misc]


async def exchange_oauth_code(code: str) -> Optional[str]:
    """Pop a one-time authorization code from Redis and return the user_id.

    Returns None (treated as "invalid code") on Redis failure so the
    frontend can retry the login rather than seeing a raw 500.
    The delete is best-effort — the key has a short TTL anyway.
    """
    from db.redis import get_redis
    try:
        redis = await get_redis()
        key = f"oauth_code:{code}"
        user_id = await redis.get(key)
        if user_id:
            try:
                await redis.delete(key)
            except Exception:
                logger.warning("Failed to delete OAuth code key (TTL will expire it)")
        return user_id
    except Exception:
        logger.exception("Redis error while exchanging OAuth code")
        return None


def verify_token(token: str, token_type: str = "access") -> Optional[Dict[str, Any]]:
    """
    Verify and decode a JWT token.
    
    Args:
        token: JWT token string to verify
        token_type: Expected token type ("access" or "refresh")
        
    Returns:
        Decoded token payload if valid, None otherwise
        
    Raises:
        JWTError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        # Verify token type matches expected
        if payload.get("type") != token_type:
            raise JWTError(f"Invalid token type. Expected {token_type}, got {payload.get('type')}")
        
        return payload
    
    except JWTError as e:
        raise JWTError(f"Token validation failed: {str(e)}")


def get_user_id_from_token(token: str) -> Optional[str]:
    """
    Extract user ID from a JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        User ID if token is valid, None otherwise
    """
    try:
        payload = verify_token(token, token_type="access")
        user_id: str = payload.get("sub")
        return user_id
    except JWTError:
        return None
