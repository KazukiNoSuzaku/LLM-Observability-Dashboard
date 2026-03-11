"""Shared pytest fixtures for the LLM Observability test suite."""

import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Test environment — set before any app imports ────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("GUARDRAILS_ENABLED", "false")
os.environ.setdefault("PHOENIX_ENABLED", "false")
os.environ.setdefault("JUDGE_ENABLED", "false")

from llm_observability.db.database import get_db
from llm_observability.db.models import Base
from llm_observability.main import app


# ── One event loop per test session ──────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Fresh in-memory DB per test function ─────────────────────────────────────
# A new engine + schema per test means committed rows never bleed across tests.

@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Yield an async DB session backed by a fresh in-memory database."""
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


# ── FastAPI test client wired to the per-test DB ─────────────────────────────

@pytest_asyncio.fixture
async def client(db_session):
    """AsyncClient with the test DB injected via dependency override."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
