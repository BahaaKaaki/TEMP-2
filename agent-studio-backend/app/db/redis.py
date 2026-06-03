"""
Async Redis connector for managing Redis connections and operations.

Supports two authentication modes:
  - Password auth (local dev, Azure Redis with access keys)
  - Azure Entra ID / Managed Identity auth (Azure Managed Redis / Azure Redis Enterprise)

Set REDIS_USE_ENTRA_AUTH=true and AZURE_CLIENT_ID_REDIS=<client-id> to enable Entra auth.
"""
import os
import asyncio
import logging
from typing import Optional, Any, Dict, List, Tuple
from datetime import datetime, timedelta
from threading import Lock
from config.keyvault import cfg
import json
import ssl as ssl_module
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool, Connection, SSLConnection
from redis.credentials import CredentialProvider
from redis.exceptions import MovedError

logger = logging.getLogger(__name__)

# Import settings for timeout configuration
try:
    from config.settings import settings
    DEFAULT_TIMEOUT = settings.REDIS_TIMEOUT
except ImportError:
    DEFAULT_TIMEOUT = 5


class RedisTokenManager:
    """
    Caches Azure AD / Entra ID tokens for Redis authentication.

    A single in-process token cache backed by ``ManagedIdentityCredential``.
    Refreshes on demand when the cached token is within ``_refresh_buffer``
    of expiry. Thread-safe (sync access via ``Lock``) and async-safe (the
    async wrapper offloads the blocking IMDS call to a worker thread).

    The token is consumed by ``EntraIdCredentialProvider`` below, which
    redis-py invokes on every new connection's AUTH handshake — so a stale
    token is never sent to the server and the connection pool does not need
    to be mutated from a background task.
    """

    REDIS_SCOPE = "https://redis.azure.com/.default"

    def __init__(self, client_id: str = None):
        """
        Initialize the Redis token manager.

        Args:
            client_id: Client ID of the user-assigned managed identity for Redis.
                       Defaults to AZURE_CLIENT_ID_REDIS env var.
        """
        self._token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._credential = None
        self._lock = Lock()
        self._refresh_buffer = timedelta(minutes=5)

        client_id = client_id or os.environ.get("AZURE_CLIENT_ID_REDIS")
        if not client_id:
            logger.error("❌ AZURE_CLIENT_ID_REDIS not set, cannot initialize Redis Entra auth")
            return

        try:
            from azure.identity import ManagedIdentityCredential
            self._credential = ManagedIdentityCredential(client_id=client_id)
            logger.info("✅ Redis ManagedIdentityCredential initialized (client_id=%s)", client_id)
        except Exception as e:
            logger.error("❌ Failed to initialize Redis ManagedIdentityCredential: %s", e)

    def _is_token_expired(self) -> bool:
        """Check if current token is expired or will expire soon."""
        if self._token is None or self._token_expiry is None:
            return True
        return datetime.now() >= (self._token_expiry - self._refresh_buffer)

    def get_token(self) -> Optional[str]:
        """Get a valid Azure AD token, refreshing if necessary (blocking)."""
        with self._lock:
            if self._is_token_expired():
                self._refresh_token()
            return self._token

    async def get_token_async(self) -> Optional[str]:
        """Async wrapper around ``get_token``; offloads IMDS I/O to a thread."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_token)

    def _refresh_token(self):
        """Refresh the Azure AD token (caller holds ``self._lock``)."""
        if self._credential is None:
            logger.error("Redis ManagedIdentityCredential not initialized")
            return

        try:
            token_result = self._credential.get_token(self.REDIS_SCOPE)
            self._token = token_result.token
            self._token_expiry = datetime.fromtimestamp(token_result.expires_on)

            expires_in = (self._token_expiry - datetime.now()).total_seconds()
            logger.debug("🔐 Redis Entra token refreshed (expires in %.1f minutes)", expires_in / 60)
        except Exception as e:
            logger.error("❌ Redis Entra token refresh failed: %s", e)
            self._token = None
            self._token_expiry = None


class EntraIdCredentialProvider(CredentialProvider):
    """
    redis-py credential provider that yields fresh Entra tokens on demand.

    redis-py calls ``get_credentials`` (or ``get_credentials_async``) every
    time a new connection runs its AUTH handshake. By delegating to
    ``RedisTokenManager``, every new connection picks up the latest token —
    eliminating the "stale token poisons the pool" failure mode that the
    old background-refresh implementation suffered from when Azure Managed
    Redis closed an idle connection past the original token's expiry.
    """

    def __init__(self, principal_id: str, token_manager: RedisTokenManager):
        self._principal_id = principal_id
        self._token_manager = token_manager

    def get_credentials(self) -> Tuple[str, str]:
        token = self._token_manager.get_token()
        if not token:
            raise RuntimeError("Unable to acquire Azure Entra token for Redis")
        return (self._principal_id, token)

    async def get_credentials_async(self) -> Tuple[str, str]:
        token = await self._token_manager.get_token_async()
        if not token:
            raise RuntimeError("Unable to acquire Azure Entra token for Redis")
        return (self._principal_id, token)


class RedisConnector:
    """
    Async Redis connector with connection pooling and common operations.
    
    Supports two authentication modes:
      - Password auth: traditional password-based authentication (local dev, access keys)
      - Entra auth: Azure AD / Managed Identity token-based authentication (cloud)
    
    Set REDIS_USE_ENTRA_AUTH=true to enable Entra authentication.
    """
    
    def __init__(
        self,
        host: str = None,
        port: int = None,
        db: int = 0,
        password: str = None,
        max_connections: int = 10,
        decode_responses: bool = True,
        socket_timeout: int = None,
        socket_connect_timeout: int = None,
        ssl: bool = None,
        ssl_cert_reqs: str = None,
        ssl_ca_certs: str = None,
        use_entra_auth: bool = None,
        entra_client_id: str = None,
        entra_principal_id: str = None,
    ):
        """
        Initialize Redis connector.
        
        Args:
            host: Redis host (defaults to REDIS_HOST env var or 'localhost')
            port: Redis port (defaults to REDIS_PORT env var or 6379)
            db: Redis database number (defaults to REDIS_DB env var or 0)
            password: Redis password (defaults to REDIS_PASSWORD env var, ignored with Entra auth)
            max_connections: Maximum number of connections in the pool
            decode_responses: Whether to decode responses to strings
            socket_timeout: Socket timeout in seconds
            socket_connect_timeout: Socket connect timeout in seconds
            ssl: Enable SSL/TLS (defaults to REDIS_SSL env var)
            ssl_cert_reqs: SSL cert requirements - 'required', 'optional', 'none'
            ssl_ca_certs: Path to CA certificate bundle
            use_entra_auth: Use Azure Entra ID auth (defaults to REDIS_USE_ENTRA_AUTH env var)
            entra_client_id: Client ID of managed identity for Redis (defaults to AZURE_CLIENT_ID_REDIS)
            entra_principal_id: Object/Principal ID used as Redis username (defaults to REDIS_ENTRA_PRINCIPAL_ID)
        """
        self.host = host if host is not None else cfg.REDIS_HOST
        self.port = port if port is not None else cfg.REDIS_PORT
        self.db = db if db is not None else cfg.REDIS_DB
        self.max_connections = max_connections
        self.decode_responses = decode_responses
        self.socket_timeout = socket_timeout if socket_timeout is not None else DEFAULT_TIMEOUT
        self.socket_connect_timeout = socket_connect_timeout if socket_connect_timeout is not None else DEFAULT_TIMEOUT
        
        # Entra ID / Managed Identity authentication settings
        self.use_entra_auth = use_entra_auth if use_entra_auth is not None else cfg.REDIS_USE_ENTRA_AUTH
        self.entra_client_id = entra_client_id or cfg.AZURE_CLIENT_ID_REDIS
        self.entra_principal_id = entra_principal_id or cfg.REDIS_ENTRA_PRINCIPAL_ID
        
        # Password auth (used when Entra auth is disabled)
        if self.use_entra_auth:
            self.password = None
            self._token_manager = RedisTokenManager(client_id=self.entra_client_id)
        else:
            self.password = password if password is not None else cfg.REDIS_PASSWORD
            self._token_manager = None
        
        # SSL Configuration
        self.ssl = ssl if ssl is not None else cfg.REDIS_SSL
        self.ssl_cert_reqs = ssl_cert_reqs if ssl_cert_reqs is not None else (cfg.REDIS_SSL_CERT_REQS.lower() if cfg.REDIS_SSL_CERT_REQS else None)
        self.ssl_ca_certs = ssl_ca_certs if ssl_ca_certs is not None else cfg.REDIS_SSL_CA_CERTS
        
        self._pool: Optional[ConnectionPool] = None
        self._client = None
    
    _MOVED_RETRIES = 3
    _MOVED_RETRY_DELAY = 0.15

    async def connect(self) -> None:
        """
        Establish connection to Redis server.

        For Entra auth: registers a credential provider that yields a fresh
        ``(principal_id, token)`` pair on every new connection's AUTH
        handshake. The token is cached in ``RedisTokenManager`` and only
        re-acquired from IMDS when the cached one is within the refresh
        buffer of expiry. This avoids the "stale token poisons the pool"
        failure mode that occurs when Azure Managed Redis closes idle
        connections past the original token's expiry.

        For password auth: uses the configured password (or no auth if none set).

        Uses a standard Redis client. Azure Redis Enterprise (proxy mode)
        can occasionally leak MOVED redirections; those are handled
        transparently by ``_retry_on_moved`` in each operation method.
        """
        if self._client is not None:
            return

        # Build connection pool parameters
        pool_params = {
            "host": self.host,
            "port": self.port,
            "db": self.db,
            "max_connections": self.max_connections,
            "decode_responses": self.decode_responses,
            "socket_timeout": self.socket_timeout,
            "socket_connect_timeout": self.socket_connect_timeout,
        }

        # Auth: prefer credential provider for Entra, fall back to static password
        if self.use_entra_auth and self._token_manager and self.entra_principal_id:
            # Eagerly fetch one token so we fail fast at startup if IMDS or
            # the access policy is misconfigured, instead of on the first
            # request hours later.
            initial_token = self._token_manager.get_token()
            if not initial_token:
                logger.error(
                    "❌ Could not acquire initial Entra token for Redis "
                    "(client_id=%s); check UAMI assignment + REDIS_ENTRA_PRINCIPAL_ID",
                    self.entra_client_id,
                )
                raise RuntimeError("Failed to acquire Azure Entra token for Redis")

            pool_params["credential_provider"] = EntraIdCredentialProvider(
                self.entra_principal_id, self._token_manager,
            )
            logger.debug("🔐 Using Entra ID credential provider for Redis")
        else:
            # Local dev / access-key auth path
            pool_params["password"] = self.password

        if self.ssl:
            pool_params["connection_class"] = SSLConnection
            if self.ssl_cert_reqs == "required":
                pool_params["ssl_cert_reqs"] = "required"
            elif self.ssl_cert_reqs == "optional":
                pool_params["ssl_cert_reqs"] = "optional"
            else:
                pool_params["ssl_cert_reqs"] = "none"
            if self.ssl_ca_certs:
                pool_params["ssl_ca_certs"] = self.ssl_ca_certs

        self._pool = ConnectionPool(**pool_params)
        self._client = Redis(connection_pool=self._pool)

        # Test connection
        await self._client.ping()

        auth_mode = "Entra ID" if self.use_entra_auth else ("password" if self.password else "no auth")
        ssl_status = "SSL" if self.ssl else "no SSL"
        logger.info(
            "✅ Connected to Redis at %s:%s (db=%s, auth=%s, %s)",
            self.host, self.port, self.db, auth_mode, ssl_status,
        )

    async def _retry_on_moved(self, coro_factory):
        """Retry a Redis command when Azure's proxy leaks a MOVED redirect.

        Azure Redis Enterprise uses a proxy that normally routes commands
        to the correct shard.  Occasionally the proxy returns a MOVED
        error instead; retrying the same command on the same proxy
        connection succeeds because the proxy updates its routing table.
        """
        for attempt in range(self._MOVED_RETRIES):
            try:
                return await coro_factory()
            except MovedError:
                if attempt < self._MOVED_RETRIES - 1:
                    logger.warning(
                        "Redis MOVED redirect (attempt %d/%d), retrying…",
                        attempt + 1, self._MOVED_RETRIES,
                    )
                    await asyncio.sleep(self._MOVED_RETRY_DELAY * (attempt + 1))
                else:
                    raise
    
    async def disconnect(self) -> None:
        """
        Close Redis connection and cleanup resources.
        """
        if self._client:
            await self._client.close()
            self._client = None

        if self._pool:
            await self._pool.disconnect()
            self._pool = None

        logger.info("✅ Disconnected from Redis")
    
    @property
    def client(self) -> Redis:
        """
        Get the Redis client instance.
        
        Returns:
            Redis client instance
            
        Raises:
            RuntimeError: If not connected to Redis
        """
        if self._client is None:
            raise RuntimeError("Not connected to Redis. Call connect() first.")
        return self._client
    
    # Key-Value Operations
    
    async def get(self, key: str) -> Optional[str]:
        """Get value by key."""
        return await self._retry_on_moved(lambda: self.client.get(key))
    
    async def set(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        px: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """Set key to value with optional expiration."""
        return await self._retry_on_moved(
            lambda: self.client.set(key, value, ex=ex, px=px, nx=nx, xx=xx)
        )
    
    async def delete(self, *keys: str) -> int:
        """Delete one or more keys."""
        return await self._retry_on_moved(lambda: self.client.delete(*keys))
    
    async def exists(self, *keys: str) -> int:
        """Check if keys exist."""
        return await self._retry_on_moved(lambda: self.client.exists(*keys))
    
    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration time for a key."""
        return await self._retry_on_moved(lambda: self.client.expire(key, seconds))
    
    async def ttl(self, key: str) -> int:
        """Get time to live for a key."""
        return await self._retry_on_moved(lambda: self.client.ttl(key))
    
    # Hash Operations
    
    async def hget(self, name: str, key: str) -> Optional[str]:
        """
        Get value from hash field.
        
        Args:
            name: Hash name
            key: Field key
            
        Returns:
            Field value or None
        """
        return await self.client.hget(name, key)
    
    async def hset(self, name: str, key: str, value: Any) -> int:
        """
        Set hash field to value.
        
        Args:
            name: Hash name
            key: Field key
            value: Field value
            
        Returns:
            1 if new field, 0 if field was updated
        """
        return await self.client.hset(name, key, value)
    
    async def hgetall(self, name: str) -> Dict[str, str]:
        """
        Get all fields and values from hash.
        
        Args:
            name: Hash name
            
        Returns:
            Dictionary of field-value pairs
        """
        return await self.client.hgetall(name)
    
    async def hdel(self, name: str, *keys: str) -> int:
        """
        Delete hash fields.
        
        Args:
            name: Hash name
            keys: Field keys to delete
            
        Returns:
            Number of fields deleted
        """
        return await self.client.hdel(name, *keys)
    
    async def hexists(self, name: str, key: str) -> bool:
        """
        Check if hash field exists.
        
        Args:
            name: Hash name
            key: Field key
            
        Returns:
            True if field exists, False otherwise
        """
        return await self.client.hexists(name, key)
    
    # List Operations
    
    async def lpush(self, name: str, *values: Any) -> int:
        """
        Push values to the head of list.
        
        Args:
            name: List name
            values: Values to push
            
        Returns:
            Length of list after push
        """
        return await self.client.lpush(name, *values)
    
    async def rpush(self, name: str, *values: Any) -> int:
        """
        Push values to the tail of list.
        
        Args:
            name: List name
            values: Values to push
            
        Returns:
            Length of list after push
        """
        return await self.client.rpush(name, *values)
    
    async def lpop(self, name: str) -> Optional[str]:
        """
        Remove and return first element of list.
        
        Args:
            name: List name
            
        Returns:
            First element or None if list is empty
        """
        return await self.client.lpop(name)
    
    async def rpop(self, name: str) -> Optional[str]:
        """
        Remove and return last element of list.
        
        Args:
            name: List name
            
        Returns:
            Last element or None if list is empty
        """
        return await self.client.rpop(name)
    
    async def lrange(self, name: str, start: int, end: int) -> List[str]:
        """
        Get range of elements from list.
        
        Args:
            name: List name
            start: Start index
            end: End index
            
        Returns:
            List of elements
        """
        return await self.client.lrange(name, start, end)
    
    async def llen(self, name: str) -> int:
        """
        Get length of list.
        
        Args:
            name: List name
            
        Returns:
            Length of list
        """
        return await self.client.llen(name)
    
    # Set Operations
    
    async def sadd(self, name: str, *values: Any) -> int:
        """
        Add members to set.
        
        Args:
            name: Set name
            values: Values to add
            
        Returns:
            Number of elements added
        """
        return await self.client.sadd(name, *values)
    
    async def srem(self, name: str, *values: Any) -> int:
        """
        Remove members from set.
        
        Args:
            name: Set name
            values: Values to remove
            
        Returns:
            Number of elements removed
        """
        return await self.client.srem(name, *values)
    
    async def smembers(self, name: str) -> set:
        """
        Get all members of set.
        
        Args:
            name: Set name
            
        Returns:
            Set of members
        """
        return await self.client.smembers(name)
    
    async def sismember(self, name: str, value: Any) -> bool:
        """
        Check if value is member of set.
        
        Args:
            name: Set name
            value: Value to check
            
        Returns:
            True if member exists, False otherwise
        """
        return await self.client.sismember(name, value)
    
    async def scard(self, name: str) -> int:
        """
        Get number of members in set.
        
        Args:
            name: Set name
            
        Returns:
            Number of members
        """
        return await self.client.scard(name)
    
    # JSON Operations (requires decode_responses=True)
    
    async def set_json(self, key: str, value: Any, **kwargs) -> bool:
        """
        Set JSON serializable value.
        
        Args:
            key: Redis key
            value: JSON serializable value
            **kwargs: Additional arguments for set (ex, px, nx, xx)
            
        Returns:
            True if successful
        """
        json_value = json.dumps(value)
        return await self.set(key, json_value, **kwargs)
    
    async def get_json(self, key: str) -> Optional[Any]:
        """
        Get and deserialize JSON value.
        
        Args:
            key: Redis key
            
        Returns:
            Deserialized value or None
        """
        value = await self.get(key)
        if value is None:
            return None
        return json.loads(value)
    
    # Utility Operations
    
    async def ping(self) -> bool:
        """
        Ping Redis server.
        
        Returns:
            True if connection is alive
        """
        return await self.client.ping()
    
    async def flushdb(self) -> bool:
        """
        Delete all keys in current database.
        
        Returns:
            True if successful
        """
        return await self.client.flushdb()
    
    async def keys(self, pattern: str = "*") -> List[str]:
        """
        Get all keys matching pattern.
        
        Args:
            pattern: Key pattern (default: "*")
            
        Returns:
            List of matching keys
        """
        return await self.client.keys(pattern)
    
    async def dbsize(self) -> int:
        """
        Get number of keys in current database.
        
        Returns:
            Number of keys
        """
        return await self.client.dbsize()


# Global Redis connector instance
redis_connector: Optional[RedisConnector] = None


async def get_redis() -> RedisConnector:
    """
    Get global Redis connector instance.
    
    Returns:
        RedisConnector instance
        
    Raises:
        RuntimeError: If Redis connector is not initialized
    """
    global redis_connector
    if redis_connector is None:
        raise RuntimeError("Redis connector not initialized. Call init_redis() first.")
    return redis_connector


async def init_redis(**kwargs) -> RedisConnector:
    """
    Initialize global Redis connector.
    
    Args:
        **kwargs: Arguments to pass to RedisConnector constructor
        
    Returns:
        RedisConnector instance
    """
    global redis_connector
    connector = RedisConnector(**kwargs)
    await connector.connect()
    redis_connector = connector
    return redis_connector


async def close_redis() -> None:
    """
    Close global Redis connector.
    """
    global redis_connector
    if redis_connector:
        await redis_connector.disconnect()
        redis_connector = None

