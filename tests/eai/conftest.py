"""Async test harness for the eai subsystem — isolated SQLite DB per test."""

from __future__ import annotations

import pytest_asyncio


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setenv("EAI_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path/'test_eai.db'}")
    monkeypatch.setenv("EAI_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("EAI_LLM_PROVIDER", "mock")

    from app.eai import config
    from app.eai import db as dbmod

    config.reset_cache()
    await dbmod.dispose()
    await dbmod.create_all()
    try:
        yield dbmod
    finally:
        await dbmod.dispose()
        config.reset_cache()


@pytest_asyncio.fixture
async def session(db):
    async with db.sessionmaker()() as s:
        yield s
