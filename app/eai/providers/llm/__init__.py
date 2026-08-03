"""LLM provider factory (spec §8)."""

from __future__ import annotations

from ... import config
from .base import Capabilities, LLMProvider, LLMResult, LLMUnavailable  # noqa: F401


def _base_provider(name: str) -> LLMProvider:
    if name == "mock":
        from .mock import MockLLMProvider
        return MockLLMProvider()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    raise ValueError(f"Unknown LLM provider: {name}")


def get_llm_provider(name: str | None = None) -> LLMProvider:
    """Resolve the LLM provider, optionally wrapped in a persistent cache.

    Set EAI_LLM_CACHE_FILE to a JSON path (e.g. data/eai/llm_cache.json) to make
    the daily build reuse prior results and only pay for new calls (spec §9).
    """
    provider = _base_provider(name or config.provider_name("llm"))
    cache_file = config.settings().llm_cache_file
    if cache_file:
        from .cache import CachedLLMProvider
        return CachedLLMProvider(provider, cache_file)
    return provider
