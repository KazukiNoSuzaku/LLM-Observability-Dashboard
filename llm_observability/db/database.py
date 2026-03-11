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
_engine_kwargs: dict = {"echo": False, "future": True}

if "sqlite" in settings.database_url:
    # SQLite requires check_same_thread=False when used with threads/asyncio
    _connect_args = {"check_same_thread": False}
else:
    # PostgreSQL: configure a sensible connection pool for production use.
    # pool_pre_ping verifies connections before checkout to avoid stale errors.
    _engine_kwargs.update(
        {
            "pool_size": 10,
            "max_overflow": 20,
            "pool_pre_ping": True,
            "pool_recycle": 1800,  # recycle connections every 30 min
        }
    )

engine = create_async_engine(
    settings.database_url,
    connect_args=_connect_args,
    **_engine_kwargs,
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


def _is_postgres() -> bool:
    """Return True when the configured DATABASE_URL targets PostgreSQL."""
    return settings.database_url.startswith("postgresql")


async def _migrate_columns(conn) -> None:  # type: ignore[no-untyped-def]
    """Add new columns to existing tables without dropping data.

    On SQLite each ALTER TABLE is attempted individually and OperationalError
    (column already exists) is silently suppressed.
    On PostgreSQL we use ``ADD COLUMN IF NOT EXISTS`` which is a no-op when
    the column is already present.
    """
    new_columns = [
        # table, column, sql_type
        ("llm_requests", "prompt_template_id",      "INTEGER"),
        ("llm_requests", "prompt_template_name",    "VARCHAR(100)"),
        ("llm_requests", "prompt_template_version", "INTEGER"),
        ("llm_requests", "prompt_variables",        "TEXT"),
        ("llm_requests", "provider",                "VARCHAR(50)"),
        # guardrail_logs is a new table (created by create_all),
        # but we guard against partial deployments with these entries:
        ("guardrail_logs", "request_id",     "INTEGER"),
        ("guardrail_logs", "stage",          "VARCHAR(20)"),
        ("guardrail_logs", "violation_type", "VARCHAR(50)"),
        ("guardrail_logs", "severity",       "VARCHAR(20)"),
        ("guardrail_logs", "action_taken",   "VARCHAR(20)"),
        ("guardrail_logs", "latency_ms",     "REAL"),
        ("guardrail_logs", "snippet",        "TEXT"),
        ("guardrail_logs", "metadata_json",  "TEXT"),
    ]
    postgres = _is_postgres()
    for table, column, col_type in new_columns:
        if postgres:
            # PostgreSQL supports IF NOT EXISTS — single idempotent statement
            try:
                await conn.execute(
                    text(
                        f"ALTER TABLE {table} "
                        f"ADD COLUMN IF NOT EXISTS {column} {col_type}"
                    )
                )
                logger.debug("Migration: ensured column %s.%s", table, column)
            except Exception as exc:
                logger.warning("Migration error %s.%s: %s", table, column, exc)
        else:
            # SQLite: attempt and ignore "duplicate column" error
            try:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                )
                logger.info("Migration: added column %s.%s", table, column)
            except Exception:
                # Column already exists — expected on subsequent startups
                pass


async def get_db() -> AsyncSession:  # type: ignore[return]
    """FastAPI dependency that yields a scoped async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
