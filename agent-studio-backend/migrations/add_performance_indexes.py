"""
Add performance indexes to database tables.

This migration adds indexes to frequently queried columns to significantly
improve query performance.

Run with: python migrations/add_performance_indexes.py
"""

from sqlalchemy import create_engine, text
import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def add_indexes():
    """Add performance indexes to database tables."""
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)
    
    # Convert async URL to sync URL if needed
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    
    logger.info(f"Connecting to database...")
    engine = create_engine(database_url)
    
    indexes = [
        # ExecutionEntity indexes
        ("idx_execution_session", "execution_entity", "sessionId"),
        ("idx_execution_workflow", "execution_entity", "workflowId"),
        ("idx_execution_status", "execution_entity", "status"),
        ("idx_execution_started", "execution_entity", "startedAt"),
        
        # ChatSession indexes
        ("idx_session_workflow", "chat_session", "workflowId"),
        ("idx_session_status", "chat_session", "status"),
        ("idx_session_last_message", "chat_session", "lastMessageAt"),
        
        # AgentDeliverable indexes
        ("idx_deliverable_session", "agent_deliverable", "sessionId"),
        ("idx_deliverable_execution", "agent_deliverable", "executionId"),
        ("idx_deliverable_status", "agent_deliverable", "status"),
    ]
    
    with engine.connect() as conn:
        logger.info("Adding performance indexes...")
        
        for index_name, table_name, column_name in indexes:
            try:
                sql = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name}({column_name});"
                conn.execute(text(sql))
                logger.info(f"  ✓ Created index {index_name} on {table_name}({column_name})")
            except Exception as e:
                logger.error(f"  ✗ Failed to create index {index_name}: {e}")
        
        conn.commit()
    
    logger.info("✓ Performance indexes migration completed successfully")


if __name__ == "__main__":
    add_indexes()

