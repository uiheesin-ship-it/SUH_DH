"""Minimal password auth for the private app (single user).

The private 4-tab app must serve full transcripts only to the owner, so every
private endpoint requires a bearer token obtained by POSTing the app password
(EAI_APP_PASSWORD). This is deliberately simple — one password, one user — which
is enough for a personal, single-owner deployment. No password → app runs but
private endpoints are locked (401), so an accidental public deploy never leaks
transcripts.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Header, HTTPException

from . import config


def _password() -> str | None:
    # env EAI_APP_PASSWORD via pydantic-settings alias; fall back to raw env.
    import os
    return os.environ.get("EAI_APP_PASSWORD")


def token_for(password: str) -> str:
    """Deterministic token derived from the password (stable across restarts)."""
    return hmac.new(b"eai-private-app", password.encode("utf-8"), hashlib.sha256).hexdigest()


def expected_token() -> str | None:
    pw = _password()
    return token_for(pw) if pw else None


def login(password: str) -> str:
    pw = _password()
    if not pw:
        raise HTTPException(status_code=503,
                            detail="EAI_APP_PASSWORD not set — private app is disabled.")
    if not hmac.compare_digest(password or "", pw):
        raise HTTPException(status_code=401, detail="Invalid password.")
    return token_for(pw)


def require_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: require a valid bearer token on private endpoints."""
    exp = expected_token()
    if exp is None:
        raise HTTPException(status_code=503,
                            detail="EAI_APP_PASSWORD not set — private app is disabled.")
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not hmac.compare_digest(token, exp):
        raise HTTPException(status_code=401, detail="Login required.")
