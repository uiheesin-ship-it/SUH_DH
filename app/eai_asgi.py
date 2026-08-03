"""Standalone ASGI app for the Earnings-AI backend (private + public eai APIs).

The legacy price-dashboard ``app.main`` imports pandas/yfinance at module top,
which the eai-only Docker image (requirements-eai.txt) doesn't install. This
entrypoint mounts ONLY the eai routers, so the private 4-tab app runs without
the legacy stack:

    uvicorn app.eai_asgi:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .eai.router import include_private, init_eai
from .eai.router import router as eai_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_eai()
    yield


app = FastAPI(title="Earnings-AI (private research app)", lifespan=lifespan)

# The Next.js frontend proxies same-origin, so CORS is permissive here; the
# private endpoints are protected by the password/token, not by origin.
_cors = os.environ.get("EAI_CORS_ORIGINS", "*").strip()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _cors == "*" else [o.strip() for o in _cors.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(eai_router)
include_private(app)  # login-gated /api/eai/private/*
