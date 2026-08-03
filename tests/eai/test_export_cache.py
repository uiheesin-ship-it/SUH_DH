"""Tests for the static export, LLM cache, and directory transcript provider.

These cover the GitHub Pages deployment path (spec §9, §21, §22): run the
pipeline → export JSON snapshot; reuse cached LLM results so daily runs only
pay for new calls; pick up transcripts dropped into the repo folder.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


async def test_export_snapshot_writes_files(db, tmp_path):
    from app.eai.export import export_snapshot

    out = tmp_path / "eai"
    meta = await export_snapshot(out, run=True)
    assert meta["counts"]["companies"] == 6
    for name in ("index", "themes", "investment_themes", "companies", "coverage", "usage"):
        assert (out / f"{name}.json").exists()
    themes = json.loads((out / "themes.json").read_text())
    assert themes["maturity"]  # Prototype / Insufficient Breadth
    assert (out / "company" / "NVDA.json").exists()


def test_llm_cache_second_call_is_free(tmp_path):
    from app.eai.providers.llm.base import Capabilities, LLMResult
    from app.eai.providers.llm.cache import CachedLLMProvider

    calls = {"n": 0}

    class Inner:
        name = "fake"
        capabilities = Capabilities()

        def complete(self, tier, system, user, *, schema=None, temperature=None, cache_prefix=False):
            calls["n"] += 1
            return LLMResult(data={"x": 1}, model_id="m", provider="fake",
                             input_tokens=100, output_tokens=50, estimated_cost=0.01)

    cache_file = tmp_path / "cache.json"
    p = CachedLLMProvider(Inner(), cache_file)
    r1 = p.complete("fast", "sys", "user", schema={"title": "T"})
    r2 = p.complete("fast", "sys", "user", schema={"title": "T"})
    assert calls["n"] == 1                # inner called once
    assert r1.cache_hit is False and r2.cache_hit is True
    assert r2.estimated_cost == 0.0 and r2.data == {"x": 1}
    assert cache_file.exists()

    # a fresh instance loads the persisted cache (survives across CI runs)
    p2 = CachedLLMProvider(Inner(), cache_file)
    r3 = p2.complete("fast", "sys", "user", schema={"title": "T"})
    assert r3.cache_hit is True and calls["n"] == 1


def test_directory_transcript_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("EAI_TRANSCRIPT_DIR", str(tmp_path))
    from app.eai import config
    config.reset_cache()
    from app.eai.providers.transcript.directory import DirectoryTranscriptProvider

    doc = {"ticker": "AAPL", "fiscal_year": 2026, "fiscal_quarter": 3,
           "call_date": "2026-08-01",
           "sections": [{"section_type": "prepared_remarks", "turns": [
               {"speaker_name": "CEO", "speaker_role": "ceo",
                "text": "AI demand was strong and data center investment increased."}]}]}
    (tmp_path / "AAPL_2026Q3.json").write_text(json.dumps(doc), encoding="utf-8")

    prov = DirectoryTranscriptProvider(tmp_path)
    refs = prov.list_available("AAPL")
    assert len(refs) == 1 and refs[0].fiscal_quarter == 3
    raw = prov.fetch(refs[0])
    assert raw.structured and raw.company is None
    assert raw.checksum()  # deterministic checksum for dedup
    config.reset_cache()
