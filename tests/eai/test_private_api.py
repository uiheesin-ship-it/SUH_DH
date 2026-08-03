"""Private app API: login + transcript / search / bundle-download (auth-gated)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EAI_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path/'priv.db'}")
    monkeypatch.setenv("EAI_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("EAI_LLM_PROVIDER", "mock")
    monkeypatch.setenv("EAI_APP_PASSWORD", "secret123")
    monkeypatch.setenv("EAI_CONFIG_FILE",
                       os.path.join(os.path.dirname(__file__), "mvp6_config.yaml"))

    from app.eai import config, db
    from app.eai.router import include_private, init_eai
    from app.eai.router import router as eai_router
    from app.eai.services import jobs

    config.reset_cache()
    db.reset_sync()

    @asynccontextmanager
    async def lifespan(app):
        await init_eai()
        async with db.sessionmaker()() as s:   # populate transcripts (mock)
            await jobs.run_batch(s)
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(eai_router)
    include_private(app)
    with TestClient(app) as c:
        yield c


def _token(client) -> str:
    r = client.post("/api/eai/login", json={"password": "secret123"})
    assert r.status_code == 200
    return r.json()["token"]


def test_login_wrong_and_right(client):
    assert client.post("/api/eai/login", json={"password": "nope"}).status_code == 401
    assert _token(client)


def test_private_requires_auth(client):
    assert client.get("/api/eai/private/companies").status_code == 401
    h = {"Authorization": f"Bearer {_token(client)}"}
    assert client.get("/api/eai/private/companies", headers=h).status_code == 200


def test_companies_by_sector_and_periods(client):
    h = {"Authorization": f"Bearer {_token(client)}"}
    sectors = client.get("/api/eai/private/companies", headers=h).json()["sectors"]
    assert sectors and any(c["ticker"] == "NVDA" for s in sectors for c in s["companies"])
    nvda = next(c for s in sectors for c in s["companies"] if c["ticker"] == "NVDA")
    assert nvda["has_transcripts"] and nvda["periods"]


def test_full_transcript(client):
    h = {"Authorization": f"Bearer {_token(client)}"}
    r = client.get("/api/eai/private/transcript/NVDA/2026/2", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["paragraphs"]
    assert any("Data center demand" in p["text_en"] for p in data["paragraphs"])
    # english original always present; korean is null until translated
    assert all("text_en" in p for p in data["paragraphs"])


def test_search_finds_paragraph(client):
    h = {"Authorization": f"Bearer {_token(client)}"}
    r = client.get("/api/eai/private/search", params={"q": "HBM supply"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 0
    assert any("HBM" in (res["snippet_en"] or "") for res in body["results"])


def test_bundle_download_one_file(client):
    h = {"Authorization": f"Bearer {_token(client)}"}
    r = client.post("/api/eai/private/download", headers=h,
                    json={"tickers": ["NVDA", "MSFT"], "periods": ["2026Q2", "2026Q1"],
                          "format": "txt"})
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment")
    text = r.content.decode("utf-8")
    assert "NVDA  FY2026 Q2" in text and "MSFT  FY2026 Q1" in text
    assert "Data center demand" in text
