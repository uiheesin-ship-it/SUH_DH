"""LLM provider abstraction (spec §8).

The finished application calls an LLM at runtime for semantic work; this layer
keeps model IDs out of the code (logical tiers only), gates unsupported
parameters behind capabilities, and returns token/cost accounting for every
call. When no real provider is configured, the system must say "LLM analysis
unavailable" rather than dress up keyword output as analysis (spec §8) — the
Mock provider exists only for offline tests and is always labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Capabilities:
    supports_structured_output: bool = False
    supports_tool_schema: bool = False
    supports_prompt_caching: bool = False
    supports_batch: bool = False
    supports_temperature: bool = True
    supports_thinking: bool = False
    maximum_context_length: int = 128_000


@dataclass
class LLMResult:
    data: dict                       # parsed JSON payload (validated by caller)
    model_id: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    processing_time: float = 0.0
    retry_count: int = 0
    cache_hit: bool = False
    status: str = "ok"               # ok | unavailable | error
    raw_text: str | None = None
    error: str | None = None
    extra: dict = field(default_factory=dict)


class LLMUnavailable(RuntimeError):
    """Raised/surfaced when no usable LLM is configured (spec §8)."""


class LLMProvider(Protocol):
    name: str
    capabilities: Capabilities

    def complete(self, tier: str, system: str, user: str, *,
                 schema: dict[str, Any] | None = None,
                 temperature: float | None = None,
                 cache_prefix: bool = False) -> LLMResult:
        """Return a structured completion for a logical model ``tier``."""
        ...
