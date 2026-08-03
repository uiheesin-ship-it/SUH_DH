"""API-level tests for the eai router (spec §18, §21, §22).

Builds a minimal FastAPI app with just the eai router (so the legacy price
modules' heavy deps aren't required) and drives it with a sync TestClient.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("EAI_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path/'api.db'}")
    monkeypatch.setenv("EAI_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("EAI_LLM_PROVIDER", "mock")
    monkeypatch.setenv("EAI_CONFIG_FILE",
                       os.path.join(os.path.dirname(__file__), "mvp6_config.yaml"))

    from app.eai import config, db
    from app.eai.router import init_eai, router

    config.reset_cache()
    db.reset_sync()

    @asynccontextmanager
    async def lifespan(app):
        await init_eai()
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    with TestClient(app) as c:
        yield c


def test_health_and_ontology(client):
    r = client.get("/api/eai/health")
    assert r.status_code == 200
    assert r.json()["llm_provider"] == "mock"
    onto = client.get("/api/eai/ontology").json()
    assert onto["topics"] and any(t["topic_id"] == "hbm" for t in onto["topics"])


def test_full_flow_via_api(client):
    assert client.post("/api/eai/seed").json()["seeded"]
    run = client.post("/api/eai/jobs/run-batch", params={"wait": True}).json()
    assert run["result"]["status"] in ("completed", "partially_completed")

    companies = client.get("/api/eai/companies").json()["companies"]
    assert len(companies) == 6

    nvda = client.get("/api/eai/companies/NVDA").json()
    assert nvda["calls"]
    assert nvda["calls"][0]["scores"]["is_experimental"] is True

    themes = client.get("/api/eai/themes").json()
    assert themes["themes"]
    assert themes["maturity"]  # Prototype / Insufficient Breadth

    board = client.get("/api/eai/investment-themes").json()
    assert board["investment_themes"]
    assert all(t["conviction"] == "low" for t in board["investment_themes"])

    usage = client.get("/api/eai/usage").json()
    assert usage["total_calls"] > 0

    coverage = client.get("/api/eai/coverage").json()
    assert coverage["total_companies"] == 6


def test_upload_dedup(client):
    client.post("/api/eai/seed")
    doc = {
        "sections": [
            {"section_type": "prepared_remarks", "turns": [
                {"speaker_name": "CEO", "speaker_role": "ceo",
                 "text": "AI demand was strong and data center investment increased."}]},
        ]
    }
    import io
    import json

    def _upload():
        return client.post(
            "/api/eai/upload",
            params={"ticker": "NVDA", "fiscal_year": 2025, "fiscal_quarter": 4},
            files={"file": ("nvda_2025q4.json", io.BytesIO(json.dumps(doc).encode()),
                            "application/json")})

    first = _upload().json()
    assert first["created"] is True
    second = _upload().json()
    assert second["created"] is False  # checksum dedup (spec §6.1)
