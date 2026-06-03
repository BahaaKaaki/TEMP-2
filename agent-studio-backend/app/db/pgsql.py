# app/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool
from sqlalchemy import text, event
from sqlalchemy.engine import Engine
import os
from dotenv import load_dotenv
import asyncpg
import asyncio
import logging
import secrets
from typing import List, Optional

rls_logger = logging.getLogger("db.rls")

load_dotenv()

from config.keyvault import cfg

# Import settings for pool configuration
try:
    from config.settings import settings
    POOL_SIZE = settings.DB_POOL_MAX_SIZE
    POOL_MIN_SIZE = settings.DB_POOL_MIN_SIZE
    DB_TIMEOUT = settings.DB_TIMEOUT
except ImportError:
    POOL_SIZE = 15
    POOL_MIN_SIZE = 1
    DB_TIMEOUT = 30

# Database configuration from central config
app_user = cfg.POSTGRES_USER
app_password = cfg.POSTGRES_PASSWORD
admin_user = cfg.ADMIN_POSTGRES_USER
admin_password = cfg.ADMIN_POSTGRES_PASSWORD
db_name = cfg.POSTGRES_DB

use_entra_auth = cfg.USE_ENTRA_AUTH
use_ssl = cfg.POSTGRES_SSL

primary_host = cfg.DATABASE_PRIMARY_HOST or cfg.DATABASE_HOST
replica1_host = None
replica2_host = None

# Store credentials for both user types
_app_credentials = {"user": app_user, "password": app_password}
_admin_credentials = {"user": admin_user, "password": admin_password}

# Import Azure AD token management from separate module
if use_entra_auth:
    from db.azure_auth import AzureTokenManager
    _token_manager = AzureTokenManager()
    logging.info("🔐 Azure AD token manager initialized")
else:
    _token_manager = None

def _build_database_url(user: str, password: str, host: str, db: str) -> str:
    """Build database URL. For Azure AD, password will be added dynamically in connect_args."""
    import urllib.parse
    
    # URL-encode the username (important for Azure AD users with special characters)
    encoded_user = urllib.parse.quote(user, safe='')
    
    # For Azure AD, don't include password in URL - it will be added in connect_args
    # SSL is configured via ssl kwarg in connect_args, not URL parameter
    if use_entra_auth:
        return f"postgresql+asyncpg://{encoded_user}@{host}:5432/{db}"
    
    # For password auth, include password in URL
    encoded_password = urllib.parse.quote(password, safe='') if password else ''
    if encoded_password:
        return f"postgresql+asyncpg://{encoded_user}:{encoded_password}@{host}:5432/{db}"
    else:
        return f"postgresql+asyncpg://{encoded_user}@{host}:5432/{db}"

# Construct database URLs for app user
PRIMARY_DATABASE_URL = _build_database_url(app_user, app_password, primary_host, db_name)
REPLICA1_DATABASE_URL = None
REPLICA2_DATABASE_URL = None

# Construct admin database URL (for migrations and admin operations)
ADMIN_DATABASE_URL = _build_database_url(admin_user, admin_password, primary_host, db_name) if admin_user else None

# For backward compatibility
DATABASE_URL = PRIMARY_DATABASE_URL


# Connection pool configuration - uses settings from config
pool_settings = {
    "command_timeout": DB_TIMEOUT,
    "min_size": POOL_MIN_SIZE,
    "max_size": POOL_SIZE,
    "max_queries": 1000,
    "max_inactive_connection_lifetime": 300.0,
    "statement_cache_size": 100,
}

# Replica pool settings
replica_pool_settings = {
    "command_timeout": max(8, DB_TIMEOUT - 2),
    "min_size": max(2, POOL_MIN_SIZE),
    "max_size": POOL_SIZE + 5,
    "max_queries": 1500,
    "max_inactive_connection_lifetime": 300.0,
    "statement_cache_size": 150,
}

def _get_connect_args(pool_config: dict, credentials: dict = None) -> dict:
    """Build connection arguments with Entra ID support."""
    connect_args = {
        "command_timeout": pool_config["command_timeout"],
        "statement_cache_size": pool_config["statement_cache_size"],
        "prepared_statement_cache_size": pool_config["statement_cache_size"]
    }
    
    if use_ssl:
        import ssl
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_REQUIRED
        connect_args["ssl"] = ssl_ctx
    
    if use_entra_auth and _token_manager:
        # Get fresh token for Entra ID authentication
        token = _token_manager.get_token()
        if token:
            connect_args["password"] = token
            logging.info("🔐 Using Entra ID authentication")
        else:
            logging.warning("⚠️  Entra ID token unavailable, falling back to password authentication")
            if credentials and credentials.get("password"):
                connect_args["password"] = credentials["password"]
    else:
        # Standard password authentication
        if credentials and credentials.get("password"):
            connect_args["password"] = credentials["password"]
    
    return connect_args

def create_engine_with_settings(database_url: str, is_replica: bool = False, credentials: dict = None):
    """Create SQLAlchemy async engine with connection pooling and Entra ID support."""
    if database_url is None:
        return None
    
    pool_config = replica_pool_settings if is_replica else pool_settings
    connect_args = _get_connect_args(pool_config, credentials)
    
    # Use AsyncAdaptedQueuePool for async engines (default for async)
    engine = create_async_engine(
        database_url,
        echo=False,
        pool_size=pool_config["max_size"],
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=3600,  # Recycle connections after 1 hour
        pool_pre_ping=True,
        connect_args=connect_args
    )
    
    # Use do_connect event to inject fresh token BEFORE each new connection is established
    if use_entra_auth:
        @event.listens_for(engine.sync_engine, "do_connect")
        def provide_token(dialect, conn_rec, cargs, cparams):
            """Inject fresh Azure AD token before each new DB connection."""
            if _token_manager:
                fresh_token = _token_manager.get_token()
                if fresh_token:
                    cparams["password"] = fresh_token
                    logging.debug("🔄 Injected fresh Azure AD token for new connection")
                else:
                    logging.warning("⚠️ Token manager returned None in do_connect")
    
    return engine

# Create engines
primary_engine = create_engine_with_settings(PRIMARY_DATABASE_URL, is_replica=False, credentials=_app_credentials)
replica1_engine = create_engine_with_settings(REPLICA1_DATABASE_URL, is_replica=True, credentials=_app_credentials) if REPLICA1_DATABASE_URL else None
replica2_engine = create_engine_with_settings(REPLICA2_DATABASE_URL, is_replica=True, credentials=_app_credentials) if REPLICA2_DATABASE_URL else None

# Admin engine (for migrations and admin operations)
admin_engine = create_engine_with_settings(ADMIN_DATABASE_URL, is_replica=False, credentials=_admin_credentials) if ADMIN_DATABASE_URL else None

# Replica engines list for load balancing (filter out None values)
replica_engines = [engine for engine in [replica1_engine, replica2_engine] if engine is not None]

# Legacy engine for backward compatibility
engine = primary_engine

# Session makers
PrimarySessionLocal = async_sessionmaker(
    primary_engine,
    expire_on_commit=False,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False
)

# Create replica session makers only if replica engines exist
Replica1SessionLocal = async_sessionmaker(
    replica1_engine,
    expire_on_commit=False,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False
) if replica1_engine else None

Replica2SessionLocal = async_sessionmaker(
    replica2_engine,
    expire_on_commit=False,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False
) if replica2_engine else None

# Replica session makers list (filter out None values)
replica_session_makers = [maker for maker in [Replica1SessionLocal, Replica2SessionLocal] if maker is not None]

# If no replicas available, use primary for read operations
if not replica_session_makers:
    replica_session_makers = [PrimarySessionLocal]

# Legacy session maker for backward compatibility
AsyncSessionLocal = PrimarySessionLocal

Base = declarative_base()

# Global connection pools
_primary_pool = None
_replica_pools = []

class DatabaseRouter:
    """Intelligent database routing for read/write splitting"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    def get_replica_session_maker(self) -> async_sessionmaker:
        """Get a random replica session maker for load balancing"""
        return secrets.choice(replica_session_makers)
    
    def get_primary_session_maker(self) -> async_sessionmaker:
        """Get the primary session maker for write operations"""
        return PrimarySessionLocal

async def init_db():
    """Initialize database connections for all instances"""
    global _primary_pool, _replica_pools
    
    try:
        # Start background token refresh if using Entra ID
        if use_entra_auth and _token_manager:
            await _token_manager.start_background_refresh()
            logging.info("🔄 Background token refresh started")
        
        # Initialize primary database
        async with primary_engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        
        logging.info(f"🔌 Database authentication mode: {'Entra ID (DefaultAzureCredential)' if use_entra_auth else 'Password'}")
            
        # Initialize primary asyncpg pool
        if _primary_pool is None:
            # Build connection kwargs for asyncpg pool
            pool_kwargs = {
                **pool_settings, 
                "timeout": 3
            }
            
            # Add SSL if required (Azure PostgreSQL requires SSL)
            ssl_ctx = None
            if use_ssl:
                import ssl
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_REQUIRED
            
            if use_entra_auth:
                # Verify token manager works by getting initial token
                token = await _token_manager.get_token_async() if _token_manager else None
                if token:
                    def _asyncpg_password_provider():
                        """Callable invoked by asyncpg for each new connection — always returns a fresh token."""
                        fresh = _token_manager.get_token()
                        return fresh

                    _primary_pool = await asyncpg.create_pool(
                        host=primary_host,
                        port=5432,
                        user=app_user,
                        password=_asyncpg_password_provider,
                        database=db_name,
                        ssl=ssl_ctx,
                        **pool_kwargs,
                        setup=lambda conn: conn.execute("SELECT 1")
                    )
                    logging.info("✅ Primary pool created with Azure AD token (callable password)")
                else:
                    logging.error("Failed to get Entra ID token for asyncpg pool")
                    # Fallback to password if available
                    if app_password:
                        _primary_pool = await asyncpg.create_pool(
                            host=primary_host,
                            port=5432,
                            user=app_user,
                            password=app_password,
                            database=db_name,
                            ssl=ssl_ctx,
                            **pool_kwargs,
                            setup=lambda conn: conn.execute("SELECT 1")
                        )
                        logging.warning("⚠️  Fell back to password authentication for asyncpg pool")
            else:
                # Standard password authentication
                _primary_pool = await asyncpg.create_pool(
                    host=primary_host,
                    port=5432,
                    user=app_user,
                    password=app_password,
                    database=db_name,
                    ssl=ssl_ctx,
                    **pool_kwargs,
                    setup=lambda conn: conn.execute("SELECT 1")
                )
            
            # Pre-warm primary connections
            for _ in range(pool_settings["min_size"]):
                async with _primary_pool.acquire() as conn:
                    await conn.execute("SELECT 1")
        
        # Initialize replica databases (only if they exist)
        replica_urls = [url for url in [REPLICA1_DATABASE_URL, REPLICA2_DATABASE_URL] if url is not None]
        
        for i, (engine, url) in enumerate(zip(replica_engines, replica_urls)):
            if engine is None or url is None:
                continue
                
            # Test SQLAlchemy connection
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            
            # Initialize asyncpg pool if not exists
            if len(_replica_pools) <= i:
                replica_pool_kwargs = {
                    **replica_pool_settings,
                    "timeout": 3
                }
                
                # Add SSL if required (Azure PostgreSQL requires SSL)
                ssl_ctx = None
                if use_ssl:
                    import ssl
                    ssl_ctx = ssl.create_default_context()
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_REQUIRED
                
                # Extract host from replica URL
                replica_host = url.split("@")[1].split(":")[0] if "@" in url else replica_urls[i].split("@")[1].split(":")[0]
                pool = await asyncpg.create_pool(
                    host=replica_host,
                    port=5432,
                    user=app_user,
                    password=app_password,
                    database=db_name,
                    ssl=ssl_ctx,
                    **replica_pool_kwargs,
                    setup=lambda conn: conn.execute("SELECT 1")
                )
                _replica_pools.append(pool)
                
                # Pre-warm replica connections
                for _ in range(replica_pool_settings["min_size"]):
                    async with pool.acquire() as conn:
                        await conn.execute("SELECT 1")
                        
        logging.info(f"Database cluster initialized: 1 primary + {len(replica_engines)} replicas")
        
        # Create tables on primary database if they don't exist
        await create_tables_if_not_exist()
                    
    except asyncio.TimeoutError:
        print("Timeout while initializing database connections")
        raise
    except Exception as e:
        logging.error(f"Error initializing database cluster: {e}")
        raise

async def create_tables_if_not_exist():
    """Create all database tables on the primary database if they don't exist"""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    try:
        logging.info("Checking and creating database tables...")

        # Serialize create_all across uvicorn workers (avoids pg_type race on new tables).
        async with primary_engine.begin() as conn:
            await conn.execute(text("SELECT pg_advisory_xact_lock(742001)"))
            from db.models import Base

            await conn.run_sync(Base.metadata.create_all)

        logging.info("✅ Database tables created/verified successfully on primary database")

    except IntegrityError as e:
        err = str(e).lower()
        if "pg_type_typname_nsp_index" in err or "already exists" in err:
            logging.warning(
                "Database tables already created by another worker (concurrent startup): %s",
                e,
            )
            return
        logging.error(f"❌ Error creating database tables: {e}")
        raise
    except Exception as e:
        logging.error(f"❌ Error creating database tables: {e}")
        raise


async def close_db():
    """
    Close all database connections gracefully.
    
    Called during shutdown to ensure:
    - All connection pools are closed
    - No hanging database connections
    - Clean termination of async operations
    """
    global _primary_pool, _replica_pools
    
    logging.info("Closing database connections...")
    
    try:
        # Stop background token refresh
        if use_entra_auth and _token_manager:
            await _token_manager.stop_background_refresh()
            logging.info("✅ Background token refresh stopped")
        
        # Close primary pool
        if _primary_pool is not None:
            await _primary_pool.close()
            _primary_pool = None
            logging.info("✅ Primary database pool closed")
        
        # Close replica pools
        for i, pool in enumerate(_replica_pools):
            if pool is not None:
                await pool.close()
                logging.info("Replica %d database pool closed", i + 1)
        _replica_pools = []
        
        # Dispose SQLAlchemy engines
        await primary_engine.dispose()
        for engine in replica_engines:
            if engine:
                await engine.dispose()
        
        logging.info("✅ All database connections closed")
        
    except Exception as e:
        logging.warning(f"⚠️  Error closing database connections: {e}")

def get_instance_info():
    """Get instance information for multi-instance deployment tracking"""
    import socket
    import os
    return {
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "instance_id": cfg.INSTANCE_ID or f"{socket.gethostname()}-{os.getpid()}"
    }


async def set_user_context(
    session: AsyncSession,
    user_id: Optional[str],
    group_ids: Optional[List[str]] = None,
):
    """
    Set the current user ID (and AD group IDs) in PostgreSQL session for RLS.

    Sets two session-level GUCs that RLS policies read:
      * app.current_user_id     -- the user's UUID
      * app.current_user_groups -- a comma-separated list of the user's AD
                                   group GUIDs (used by group-based shares)

    Args:
        session:    SQLAlchemy async session
        user_id:    UUID of the current user, or None to disable RLS filtering
        group_ids:  Optional list of AD group GUIDs the user belongs to.
                    Each entry must be a valid UUID/GUID (validated below).
    """
    if user_id:
        # Validate UUID format to prevent SQL injection
        import uuid
        try:
            uuid.UUID(user_id)  # Validates UUID format
        except ValueError:
            raise ValueError(f"Invalid user_id format: {user_id}")

        # Validate every group id, drop anything that doesn't look like a GUID
        # so a malformed claim from the IdP can't break the SET.
        validated_groups: List[str] = []
        if group_ids:
            for gid in group_ids:
                try:
                    uuid.UUID(str(gid))
                    validated_groups.append(str(gid))
                except (ValueError, TypeError):
                    rls_logger.warning(
                        "🔒 RLS: Dropping malformed group id %r from context", gid
                    )

        groups_csv = ",".join(validated_groups)

        # Use raw connection to execute SET without parameter binding.
        # Use SET (not SET LOCAL) so it persists for the entire connection session.
        conn = await session.connection()
        await conn.execute(text(f"SET app.current_user_id = '{user_id}'"))
        # Always set the groups GUC (even to ''), so the policy can read it
        # without falling back to the default of an unconfigured server.
        await conn.execute(text(f"SET app.current_user_groups = '{groups_csv}'"))

        if rls_logger.isEnabledFor(logging.DEBUG):
            verify = await conn.execute(text(
                "SELECT current_setting('app.current_user_id', true), "
                "current_setting('app.current_user_groups', true)"
            ))
            uid_v, grp_v = verify.first() or (None, None)
            rls_logger.debug(
                "🔒 RLS: user=%s groups=[%d] verified=(%s, %s)",
                user_id, len(validated_groups), uid_v, grp_v,
            )
    else:
        # Clear the user context (useful for system operations)
        conn = await session.connection()
        await conn.execute(text("SET app.current_user_id = ''"))
        await conn.execute(text("SET app.current_user_groups = ''"))
        rls_logger.debug("🔓 RLS: Cleared user context")


async def get_write_db():
    """Dependency for getting primary database session (write operations)"""
    from core.request_context import get_current_user_id
    
    session = PrimarySessionLocal()
    try:
        # Ensure connection is established with retry logic
        retries = 3
        for attempt in range(retries):
            try:
                await session.execute(text("SELECT 1"))
                break
            except Exception as e:
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(1)  # Wait before retrying
        
        # Automatically set user context from request context if authenticated
        user_id = get_current_user_id()
        if user_id:
            await set_user_context(session, user_id)
        
        yield session
    finally:
        # CRITICAL: Reset user context before returning connection to pool
        try:
            conn = await session.connection()
            await conn.execute(text("RESET app.current_user_id"))
        except:
            pass  # Ignore errors during cleanup
        await session.close()


async def get_static_read_db():
    """
    Dependency for reading STATIC/SEMI-STATIC data from replicas.
    Perfect for: recipes, barcodes, workout programs, food database, etc.
    This data changes infrequently, so replica lag is not a concern.
    """
    from core.request_context import get_current_user_id
    
    router = DatabaseRouter()
    session_maker = router.get_replica_session_maker()
    session = session_maker()
    
    try:
        # Ensure connection is established with retry logic
        retries = 3
        for attempt in range(retries):
            try:
                await session.execute(text("SELECT 1"))
                break
            except Exception as e:
                if attempt == retries - 1:
                    # Fallback to primary if all replicas fail
                    await session.close()
                    logging.warning("All replicas failed, falling back to primary for static read operation")
                    session = PrimarySessionLocal()
                    await session.execute(text("SELECT 1"))
                    break
                await asyncio.sleep(1)  # Wait before retrying
        
        # Automatically set user context from request context if authenticated
        user_id = get_current_user_id()
        if user_id:
            await set_user_context(session, user_id)
        
        yield session
    finally:
        # CRITICAL: Reset user context before returning connection to pool
        try:
            conn = await session.connection()
            await conn.execute(text("RESET app.current_user_id"))
        except:
            pass  # Ignore errors during cleanup
        await session.close()

async def get_dynamic_read_db():
    """
    Dependency for reading FREQUENTLY UPDATED data.
    Routes to PRIMARY to avoid read-after-write consistency issues.
    Perfect for: user profiles, recent meals, live activity data, etc.
    """
    from core.request_context import get_current_user_id
    
    session = PrimarySessionLocal()
    try:
        # Ensure connection is established with retry logic
        retries = 3
        for attempt in range(retries):
            try:
                await session.execute(text("SELECT 1"))
                break
            except Exception as e:
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(1)  # Wait before retrying
        
        # Automatically set user context from request context if authenticated
        user_id = get_current_user_id()
        if user_id:
            await set_user_context(session, user_id)
        
        yield session
    finally:
        # CRITICAL: Reset user context before returning connection to pool
        try:
            conn = await session.connection()
            await conn.execute(text("RESET app.current_user_id"))
        except:
            pass  # Ignore errors during cleanup
        await session.close()

async def get_read_db():
    """
    Legacy dependency - defaults to static read (replica) for backward compatibility.
    Consider using get_static_read_db() or get_dynamic_read_db() explicitly.
    """
    async for session in get_static_read_db():
        yield session

async def get_db():
    """Legacy dependency for backward compatibility - routes to primary"""
    async for session in get_write_db():
        yield session

async def get_admin_db():
    """
    Dependency for admin operations that need elevated access.
    
    Strategy:
    - If ADMIN_POSTGRES_USER is configured, uses the dedicated admin engine
      (separate DB credentials with elevated privileges).
    - Otherwise, falls back to PrimarySessionLocal.
    
    In both cases, sets app.current_user_id from request context so that
    RLS policies with admin clauses evaluate correctly. This is required
    because Azure PostgreSQL admin users do NOT have BYPASSRLS privileges,
    so FORCE ROW LEVEL SECURITY applies even to the admin DB user.
    
    IMPORTANT: Only use this dependency with admin-authenticated endpoints!
    """
    from core.request_context import get_current_user_id
    
    if admin_engine is not None:
        AdminSessionLocal = async_sessionmaker(
            admin_engine,
            expire_on_commit=False,
            class_=AsyncSession,
            autocommit=False,
            autoflush=False
        )
        session = AdminSessionLocal()
        try:
            await session.execute(text("SELECT 1"))
            
            user_id = get_current_user_id()
            if user_id:
                await set_user_context(session, user_id)
            
            yield session
        finally:
            try:
                conn = await session.connection()
                await conn.execute(text("RESET app.current_user_id"))
            except:
                pass
            await session.close()
    else:
        session = PrimarySessionLocal()
        try:
            retries = 3
            for attempt in range(retries):
                try:
                    await session.execute(text("SELECT 1"))
                    break
                except Exception as e:
                    if attempt == retries - 1:
                        raise
                    await asyncio.sleep(1)
            
            user_id = get_current_user_id()
            if user_id:
                await set_user_context(session, user_id)
            
            yield session
        finally:
            try:
                conn = await session.connection()
                await conn.execute(text("RESET app.current_user_id"))
            except:
                pass
            await session.close()

def get_db_url():
    return DATABASE_URL

def get_primary_db_url():
    return PRIMARY_DATABASE_URL

def get_replica_db_urls():
    return [REPLICA1_DATABASE_URL, REPLICA2_DATABASE_URL]

def get_admin_db_url():
    return ADMIN_DATABASE_URL
