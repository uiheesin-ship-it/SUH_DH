"""Async SQLAlchemy engine/session for the eai subsystem.

Portable across SQLite (default, so the MVP runs with no Postgres server) and
PostgreSQL (prod, via EAI_DATABASE_URL=postgresql+asyncpg://…). Column types
are chosen to work on both; JSON columns use the generic ``JSON`` type which
maps to JSONB-compatible storage on Postgres.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    pass


def engine():
    global _engine, _sessionmaker
    if _engine is None:
        url = settings().database_url
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        _engine = create_async_engine(url, echo=False, future=True, connect_args=connect_args)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session, always closed."""
    async with sessionmaker()() as session:
        yield session


async def create_all() -> None:
    """Create tables from the metadata (MVP convenience; prod uses Alembic)."""
    from . import models  # noqa: F401  (register mappers)

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def reset_sync() -> None:
    """Drop the cached engine without awaiting (test-only, e.g. switching DBs)."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None
