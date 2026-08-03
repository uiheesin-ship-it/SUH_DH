"""Standalone ASGI app for the Earnings-AI backend + built frontend.

Serves BOTH the login-gated API (/api/eai/*) and the statically-exported Next.js
frontend at "/", so the whole private app is ONE service behind ONE URL — ideal
for a free-tier deploy. The legacy price dashboard (app.main) is NOT imported,
so this runs on requirements-eai.txt alone.

    uvicorn app.eai_asgi:app --host 0.0.0.0 --port ${PORT:-8000}
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .eai.router import include_private, init_eai
from .eai.router import router as eai_router

_ROOT = Path(__file__).resolve().parent.parent
_STATIC_DIR = Path(os.environ.get("EAI_STATIC_DIR") or (_ROOT / "frontend" / "out"))


async def _demo_seed() -> None:
    """Populate the 6-company demo (mock) once, so a fresh deploy isn't empty.

    Only runs when EAI_DEMO_SEED=1 and the DB has no companies yet. Real data
    comes from the harvester; this is just so the first visit shows something.
    """
    if os.environ.get("EAI_DEMO_SEED") != "1":
        return
    from sqlalchemy import select

    from .eai.db import sessionmaker
    from .eai.models import Company
    from .eai.services import jobs

    async with sessionmaker()() as s:
        if (await s.execute(select(Company.id).limit(1))).first():
            return  # already has data
    async with sessionmaker()() as s:
        await jobs.run_batch(s)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_eai()
    try:
        await _demo_seed()
    except Exception:  # never let seeding block startup
        pass
    yield


app = FastAPI(title="Earnings-AI (private research app)", lifespan=lifespan)

_cors = os.environ.get("EAI_CORS_ORIGINS", "*").strip()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _cors == "*" else [o.strip() for o in _cors.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(eai_router)
include_private(app)  # login-gated /api/eai/private/*

# Serve the built frontend LAST so /api/eai/* routes win. html=True makes
# /ideas → ideas/index.html (Next export with trailingSlash).
if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="frontend")
