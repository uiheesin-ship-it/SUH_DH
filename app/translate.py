"""Best-effort English -> Korean translation for company info and headlines.

Uses deep-translator's free Google endpoint (no API key). Network failures or
rate limits fall back to the original text, so the dashboard never breaks just
because a translation could not be fetched. Results are cached per process.
"""

from __future__ import annotations

import re

_cache: dict[str, str] = {}


def _short_summary(text: str | None, max_sentences: int = 2, max_chars: int = 400) -> str | None:
    """Trim a long business summary down to a brief blurb before translating."""
    if not text:
        return None
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    blurb = " ".join(parts[:max_sentences]).strip()
    return blurb[:max_chars]


def to_korean(text: str | None) -> str | None:
    """Translate to Korean, falling back to the original text on any failure."""
    if not text:
        return text
    if text in _cache:
        return _cache[text]
    result = text
    try:
        from deep_translator import GoogleTranslator

        translated = GoogleTranslator(source="auto", target="ko").translate(text[:1500])
        if translated:
            result = translated
    except Exception:
        result = text  # keep original English rather than failing
    _cache[text] = result
    return result


def summary_korean(text: str | None) -> str | None:
    return to_korean(_short_summary(text))
