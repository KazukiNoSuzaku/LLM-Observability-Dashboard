"""Async SQLAlchemy engine, session factory, and DB initialisation."""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from llm_observability.core.config import settings
from llm_observability.db.models import Base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
_connect_args: dict = {}
if "sqlite" in settings.database_url:
    # SQLite requires check_same_thread=False when used with threads/asyncio
    _connect_args = {"check_same_thread": False}

engine = create_async_engine(
    settings.database_url,
    echo=False,          # Set True to log all SQL statements
    future=True,
    connect_args=_connect_args,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------


async def init_db() -> None:
    """Create all tables and apply incremental column migrations.

    Safe to call multiple times — CREATE TABLE uses IF NOT EXISTS semantics,
    and the migration step silently skips columns that already exist.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_columns(conn)


async def _migrate_columns(conn) -> None:  # type: ignore[no-untyped-def]
    """Add new columns to existing tables without dropping data.

    Each ALTER TABLE statement is attempted individually; if the column
    already exists SQLite raises an OperationalError which we suppress.
    This lets us evolve the schema incrementally without a migration tool.
    """
    new_columns = [
        # table, column, sql_type
        ("llm_requests", "prompt_template_id",      "INTEGER"),
        ("llm_requests", "prompt_template_name",    "VARCHAR(100)"),
        ("llm_requests", "prompt_template_version", "INTEGER"),
        ("llm_requests", "prompt_variables",        "TEXT"),
    ]
    for table, column, col_type in new_columns:
        try:
            await conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            )
            logger.info("Migration: added column %s.%s", table, column)
        except Exception:
            # Column already exists — this is expected on subsequent startups
            pass


async def get_db() -> AsyncSession:  # type: ignore[return]
    """FastAPI dependency that yields a scoped async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
