"""LLM provider factory (spec §8)."""

from __future__ import annotations

from ... import config
from .base import Capabilities, LLMProvider, LLMResult, LLMUnavailable  # noqa: F401


def get_llm_provider(name: str | None = None) -> LLMProvider:
    name = name or config.provider_name("llm")
    if name == "mock":
        from .mock import MockLLMProvider
        return MockLLMProvider()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    raise ValueError(f"Unknown LLM provider: {name}")
