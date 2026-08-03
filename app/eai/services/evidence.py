"""Evidence verification (spec §16).

Auto-pass requires a **normalized exact substring match** against the cited
paragraph. Anything weaker (fuzzy only) is marked ``needs_manual_review`` and
must be *excluded* from confirmed-evidence counts, Numeric/Fundamental
Confirmation, and High-Conviction themes — the caller enforces that by only
trusting ``status == verified``.

Pure functions; no DB. The caller passes a paragraph index built from
``TranscriptParagraph`` rows.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from . import textnorm

# number, optional $, %, currency codes, quarters/periods, units (bn/mn/bps…)
_NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")
_UNIT = re.compile(
    r"\b(?:billion|million|thousand|bn|mn|bps|basis points|percent|%|"
    r"usd|eur|gbp|jpy|q[1-4]|fy\d{2,4}|year over year|yoy|qoq)\b",
    re.I,
)


@dataclass
class VerificationResult:
    status: str                       # verified|needs_manual_review|failed|insufficient_evidence
    method: str                       # exact_substring|fuzzy_candidate|numeric
    paragraph_id: str
    quote_start_offset: int | None = None
    quote_end_offset: int | None = None
    paragraph_hash: str | None = None
    numeric_check: dict | None = None
    fuzzy_candidate_pid: str | None = None
    fuzzy_ratio: float | None = None
    reason: str | None = None


def has_numbers(text: str) -> bool:
    return bool(re.search(r"\d", text or ""))


def extract_numeric_tokens(text: str) -> dict:
    """Pull out numbers and units for separate numeric verification (spec §16)."""
    return {
        "numbers": _NUM.findall(text or ""),
        "units": [u.lower() for u in _UNIT.findall(text or "")],
    }


def verify_one(paragraph_id: str, exact_quote_en: str,
               paragraph_index: dict[str, dict]) -> VerificationResult:
    """Verify a single quote against the paragraph index.

    ``paragraph_index`` maps paragraph_id -> {"normalized": str, "hash": str}.
    """
    if not exact_quote_en or not exact_quote_en.strip():
        return VerificationResult(
            status="insufficient_evidence", method="exact_substring",
            paragraph_id=paragraph_id, reason="empty_quote",
        )

    para = paragraph_index.get(paragraph_id)
    if para is None:
        # Nonexistent paragraph_id must be blocked (spec §15, §16). Offer a fuzzy
        # candidate only as a manual-review hint, never as a pass.
        cand_pid, ratio = _closest_paragraph(exact_quote_en, paragraph_index)
        return VerificationResult(
            status="failed", method="exact_substring", paragraph_id=paragraph_id,
            fuzzy_candidate_pid=cand_pid, fuzzy_ratio=ratio,
            reason="paragraph_id_not_found",
        )

    norm_para = para["normalized"]
    norm_quote = textnorm.normalize(exact_quote_en)
    idx = norm_para.find(norm_quote)
    if idx >= 0:
        result = VerificationResult(
            status="verified", method="exact_substring", paragraph_id=paragraph_id,
            quote_start_offset=idx, quote_end_offset=idx + len(norm_quote),
            paragraph_hash=para.get("hash"),
        )
        if has_numbers(norm_quote):
            # Exact substring guarantees the digits are present; record the
            # numeric tokens and mark the numeric verification explicitly.
            result.numeric_check = {
                "verified": True,
                **extract_numeric_tokens(norm_quote),
            }
        return result

    # Exact failed → fuzzy is a *candidate hint only* (spec §16): manual review.
    ratio = difflib.SequenceMatcher(None, norm_quote, norm_para).ratio()
    return VerificationResult(
        status="needs_manual_review", method="fuzzy_candidate",
        paragraph_id=paragraph_id, fuzzy_ratio=round(ratio, 4),
        reason="exact_substring_failed",
    )


def _closest_paragraph(quote: str, paragraph_index: dict[str, dict]) -> tuple[str | None, float | None]:
    norm_quote = textnorm.normalize(quote)
    best_pid, best_ratio = None, 0.0
    for pid, para in paragraph_index.items():
        r = difflib.SequenceMatcher(None, norm_quote, para["normalized"]).ratio()
        if r > best_ratio:
            best_pid, best_ratio = pid, r
    return best_pid, round(best_ratio, 4) if best_pid else None


@dataclass
class ClaimVerification:
    verified: list[VerificationResult] = field(default_factory=list)
    review: list[VerificationResult] = field(default_factory=list)
    failed: list[VerificationResult] = field(default_factory=list)

    @property
    def verified_count(self) -> int:
        return len(self.verified)

    @property
    def has_verified_evidence(self) -> bool:
        return bool(self.verified)


def verify_claim(evidence_items: list[dict], paragraph_index: dict[str, dict]) -> ClaimVerification:
    """Verify all evidence for one claim; bucket by status.

    ``evidence_items`` is a list of {"paragraph_id", "exact_quote_en"} dicts.
    A claim with no verified evidence should be treated as insufficient by the
    caller (spec §1-8).
    """
    cv = ClaimVerification()
    for ev in evidence_items:
        r = verify_one(ev.get("paragraph_id", ""), ev.get("exact_quote_en", ""), paragraph_index)
        if r.status == "verified":
            cv.verified.append(r)
        elif r.status == "needs_manual_review":
            cv.review.append(r)
        else:
            cv.failed.append(r)
    return cv


def build_index(paragraphs) -> dict[str, dict]:
    """Build a paragraph index from ORM rows or ParsedParagraph objects."""
    index: dict[str, dict] = {}
    for p in paragraphs:
        pid = getattr(p, "paragraph_id")
        norm = getattr(p, "normalized_text_en", None) or textnorm.normalize(
            getattr(p, "exact_text_en", "")
        )
        index[pid] = {"normalized": norm, "hash": getattr(p, "paragraph_hash", "") or
                      textnorm.paragraph_hash(norm)}
    return index
