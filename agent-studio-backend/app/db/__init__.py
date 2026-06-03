"""Database module for PostgreSQL connections with Azure AD authentication support."""

from db.pgsql import (
    init_db,
    close_db,
    get_db,
    get_write_db,
    get_read_db,
    get_static_read_db,
    get_dynamic_read_db,
    get_admin_db,
    set_user_context,
    Base,
    engine,
    primary_engine,
    AsyncSessionLocal,
    PrimarySessionLocal,
)

__all__ = [
    "init_db",
    "close_db",
    "get_db",
    "get_write_db",
    "get_read_db",
    "get_static_read_db",
    "get_dynamic_read_db",
    "get_admin_db",
    "set_user_context",
    "Base",
    "engine",
    "primary_engine",
    "AsyncSessionLocal",
    "PrimarySessionLocal",
]
