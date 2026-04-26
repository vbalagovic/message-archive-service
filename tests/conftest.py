"""Shared test fixtures.

Strategy: spin up a single Postgres container for the whole session, run
migrations once, then truncate the table between tests for isolation. This
is much faster than tearing down the DB per test and exercises real SQL.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker
from app.domain.models import Base, MessageRole

VALID_API_KEY = "test-key"


@pytest.fixture(scope="session", autouse=True)
def _postgres_container() -> Iterator[PostgresContainer]:
    """Start one Postgres for the whole session."""
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        # testcontainers gives us postgresql+asyncpg://user:pass@host:port/db
        os.environ["DATABASE_URL"] = url
        os.environ["API_KEYS"] = VALID_API_KEY
        os.environ["RATE_LIMIT_PER_MINUTE"] = "10000"  # don't trip rate limit in tests
        os.environ["LOG_LEVEL"] = "WARNING"
        get_settings.cache_clear()
        yield pg
    get_settings.cache_clear()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_schema(_postgres_container: PostgresContainer) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    yield
    await dispose_engine()


@pytest_asyncio.fixture(autouse=True)
async def _truncate_messages() -> AsyncIterator[None]:
    """Clean slate between every test."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(text("TRUNCATE TABLE messages"))
        await session.commit()
    yield


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        yield s


def _build_app():  # type: ignore[no-untyped-def]
    # Imported lazily because app.main reads settings at import time, and
    # those settings are populated by the autouse _postgres_container fixture.
    from app.main import create_app  # noqa: PLC0415

    return create_app()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": VALID_API_KEY},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def anon_client() -> AsyncIterator[AsyncClient]:
    """Client with no auth headers — for testing 401s."""
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ----------------------------------------------------------------------------
# Factories
# ----------------------------------------------------------------------------
def make_message_payload(
    *,
    message_id: UUID | None = None,
    chat_id: UUID | None = None,
    content: str = "hello world",
    rating: bool | None = None,
    sent_at: datetime | None = None,
    role: MessageRole = MessageRole.USER,
) -> dict[str, object]:
    return {
        "message_id": str(message_id or uuid4()),
        "chat_id": str(chat_id or uuid4()),
        "content": content,
        "rating": rating,
        "sent_at": (sent_at or datetime.now(UTC)).isoformat(),
        "role": role.value,
    }


def utc_at(seconds_offset: int) -> datetime:
    """Stable, comparable UTC timestamps for ordering tests."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return base + timedelta(seconds=seconds_offset)
