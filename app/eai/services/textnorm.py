"""Text normalization shared by preprocessing and evidence verification.

The spec (§16) fixes the normalization used for exact-substring evidence
matching to a *limited* set of transforms so that a passing match is
meaningful and reproducible:
  - whitespace collapse
  - newline normalization
  - quote-character normalization (curly → straight)
  - Unicode NFKC normalization

No stemming, lowercasing, or punctuation stripping — those would make the
"exact" match dishonest.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_QUOTES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "«": '"', "»": '"', "′": "'", "″": '"',
    "–": "-", "—": "-",  # en/em dash → hyphen
}

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Apply the spec-limited normalization and return a single-spaced string."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(_QUOTES.get(ch, ch) for ch in text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    return text.strip()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def paragraph_hash(normalized_text: str) -> str:
    """Stable hash of a paragraph's normalized text (spec §7)."""
    return sha256(normalized_text)
