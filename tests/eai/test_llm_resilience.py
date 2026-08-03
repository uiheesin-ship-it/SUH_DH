"""LLM error resilience (spec §8, §23).

A provider API error (invalid key, network) must never crash the batch: it
surfaces as 'unavailable'/'error', and — critically — a failed run must NOT
overwrite the last good static snapshot.
"""

from __future__ import annotations

from app.eai.providers.llm.base import Capabilities
from app.eai.schemas.llm_io import ChunkExtraction
from app.eai.services.llm_runner import run_stage


class _AuthFail:
    name = "x"
    capabilities = Capabilities()

    def complete(self, *a, **k):
        err = type("AuthenticationError", (Exception,), {})
        raise err("Error code: 401 - API key is invalid.")


class _TransientFail:
    name = "x"
    capabilities = Capabilities()

    def __init__(self):
        self.calls = 0

    def complete(self, *a, **k):
        self.calls += 1
        raise RuntimeError("connection reset by peer")


def test_auth_error_surfaces_unavailable_not_crash():
    out = run_stage(_AuthFail(), "deep", "sys", "user", ChunkExtraction, stage="stage4")
    assert out.status == "unavailable"
    assert out.model is None
    assert "401" in (out.error or "")


def test_transient_error_retries_then_error():
    prov = _TransientFail()
    out = run_stage(prov, "fast", "sys", "user", ChunkExtraction, stage="stage1")
    assert out.status == "error"
    assert out.model is None
    assert prov.calls >= 2               # retried before giving up


async def test_export_preserves_snapshot_when_llm_unavailable(db, tmp_path, monkeypatch):
    from app.eai import config
    from app.eai.export import export_snapshot

    out = tmp_path / "eai"
    good = await export_snapshot(out, run=True)          # mock provider → good snapshot
    assert good["written"] is True
    before = (out / "themes.json").read_text()

    # Force an unusable LLM: anthropic provider with no key/model configured.
    monkeypatch.setenv("EAI_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("EAI_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("EAI_FAST_MODEL", raising=False)
    config.reset_cache()

    bad = await export_snapshot(out, run=True)
    assert bad["written"] is False
    assert bad["batch_status"] == "llm_unavailable"
    assert (out / "themes.json").read_text() == before   # NOT overwritten
    config.reset_cache()
