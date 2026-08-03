"""Verify the real AnthropicProvider request/response path with a fake SDK.

We can't make a paid API call in CI, so we inject a fake ``anthropic`` module
and assert the provider (a) builds a tool-schema structured-output request with
the configured model id, (b) applies prompt-cache control on the system block,
(c) parses the tool_use result + token usage, and (d) validates through
run_stage. This gives confidence the path works once EAI_ANTHROPIC_API_KEY and
the EAI_*_MODEL variables are set — no code change needed to "go live".
"""

from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def fake_anthropic(monkeypatch):
    captured = {}

    class _Block:
        type = "tool_use"
        input = {"mentions": []}  # valid ChunkExtraction payload

    class _Usage:
        input_tokens = 123
        output_tokens = 45

    class _Resp:
        content = [_Block()]
        usage = _Usage()

    class _Messages:
        def create(self, **kwargs):
            captured["kwargs"] = kwargs
            return _Resp()

    class _Client:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.messages = _Messages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", mod)

    monkeypatch.setenv("EAI_ANTHROPIC_API_KEY", "sk-test-123")
    monkeypatch.setenv("EAI_FAST_MODEL", "some-fast-model-id")
    monkeypatch.delenv("EAI_LLM_CACHE_FILE", raising=False)
    from app.eai import config
    config.reset_cache()
    yield captured
    config.reset_cache()


def test_anthropic_structured_request_and_parse(fake_anthropic):
    from app.eai.providers.llm.anthropic_provider import AnthropicProvider
    from app.eai.schemas.llm_io import ChunkExtraction
    from app.eai.services.llm_runner import run_stage

    provider = AnthropicProvider()
    outcome = run_stage(provider, "fast", "SYSTEM PREFIX", "USER BODY",
                        ChunkExtraction, stage="stage1")

    assert outcome.status == "ok"
    assert isinstance(outcome.model, ChunkExtraction)

    kw = fake_anthropic["kwargs"]
    assert kw["model"] == "some-fast-model-id"          # tier→configured id (not hardcoded)
    assert kw["tools"][0]["name"] == "emit"             # tool-schema structured output
    assert kw["tool_choice"]["name"] == "emit"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}  # prompt caching
    assert fake_anthropic["api_key"] == "sk-test-123"   # key from env, not code

    usage = outcome.usage[-1]
    assert usage["input_tokens"] == 123 and usage["output_tokens"] == 45
    assert usage["estimated_cost"] > 0                  # real cost accounting


def test_llm_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("EAI_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("EAI_FAST_MODEL", "x")
    from app.eai import config
    from app.eai.providers.llm.anthropic_provider import AnthropicProvider
    from app.eai.providers.llm.base import LLMUnavailable
    config.reset_cache()
    with pytest.raises(LLMUnavailable):
        AnthropicProvider().complete("fast", "s", "u")
    config.reset_cache()


def test_run_stage_surfaces_unavailable(monkeypatch):
    """No usable LLM must surface as 'unavailable', never faked (spec §8)."""
    monkeypatch.delenv("EAI_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("EAI_FAST_MODEL", "x")
    from app.eai import config
    from app.eai.providers.llm.anthropic_provider import AnthropicProvider
    from app.eai.schemas.llm_io import ChunkExtraction
    from app.eai.services.llm_runner import run_stage
    config.reset_cache()
    outcome = run_stage(AnthropicProvider(), "fast", "s", "u", ChunkExtraction, stage="stage1")
    assert outcome.status == "unavailable"
    assert outcome.model is None
    config.reset_cache()
