"""Anthropic LLM provider (spec §8).

Lazy-imports the ``anthropic`` SDK so the package is optional in environments
that only run the mock provider/tests. Model IDs come from config tiers
(never hardcoded); the API key comes from the environment. Uses tool-schema
structured output when a schema is supplied, and prompt caching only when
enabled — unsupported params are never forced (capability-gated).
"""

from __future__ import annotations

import json
import time

from ... import config
from .base import Capabilities, LLMResult, LLMUnavailable

# Rough public per-MTok pricing knobs (USD); override via config if needed.
_DEFAULT_COST = {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000}


class AnthropicProvider:
    name = "anthropic"
    capabilities = Capabilities(
        supports_structured_output=True, supports_tool_schema=True,
        supports_prompt_caching=True, supports_batch=True,
        supports_temperature=True, supports_thinking=True, maximum_context_length=200_000,
    )

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        key = config.settings().anthropic_api_key
        if not key:
            raise LLMUnavailable("EAI_ANTHROPIC_API_KEY not set")
        try:
            import anthropic  # lazy
        except ImportError as e:  # pragma: no cover - depends on optional dep
            raise LLMUnavailable("anthropic SDK not installed") from e
        self._client = anthropic.Anthropic(api_key=key)
        return self._client

    def complete(self, tier, system, user, *, schema=None, temperature=None,
                 cache_prefix=False) -> LLMResult:
        model = config.model_for_tier(tier)
        if not model:
            raise LLMUnavailable(f"No model configured for tier '{tier}'")
        client = self._get_client()

        t0 = time.time()
        kwargs: dict = {"model": model, "max_tokens": 4096,
                        "system": _system_blocks(system, cache_prefix and
                                                  self.capabilities.supports_prompt_caching)}
        if temperature is not None and self.capabilities.supports_temperature:
            kwargs["temperature"] = temperature

        if schema is not None and self.capabilities.supports_tool_schema:
            tool = {"name": "emit", "description": "Return the structured result.",
                    "input_schema": schema}
            kwargs["tools"] = [tool]
            kwargs["tool_choice"] = {"type": "tool", "name": "emit"}

        kwargs["messages"] = [{"role": "user", "content": user}]
        resp = client.messages.create(**kwargs)

        data, raw_text = _parse_response(resp)
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0
        return LLMResult(
            data=data, model_id=model, provider="anthropic",
            input_tokens=in_tok, output_tokens=out_tok,
            estimated_cost=in_tok * _DEFAULT_COST["input"] + out_tok * _DEFAULT_COST["output"],
            processing_time=time.time() - t0, status="ok", raw_text=raw_text,
        )


def _system_blocks(system: str, cache: bool):
    block = {"type": "text", "text": system}
    if cache:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


def _parse_response(resp) -> tuple[dict, str | None]:
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input), None
    # fall back to text → try to parse JSON
    text = ""
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text += block.text
    try:
        return json.loads(text), text
    except Exception:
        return {}, text
