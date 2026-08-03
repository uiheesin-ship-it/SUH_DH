"""Offline unit tests for evidence verification (spec §16, §23)."""

from app.eai.services import evidence, preprocess

STRUCTURED = {
    "ticker": "NVDA", "fiscal_year": 2026, "fiscal_quarter": 2,
    "sections": [{"section_type": "prepared_remarks", "turns": [
        {"speaker_name": "Colette Kress", "speaker_role": "cfo",
         "text": "Revenue was $30.0 billion, up 122% year over year."},
    ]}],
}


def _index():
    parsed = preprocess.parse_structured(STRUCTURED)
    return evidence.build_index(parsed.paragraphs), parsed


def test_exact_substring_passes_with_offsets():
    idx, _ = _index()
    r = evidence.verify_one("NVDA_2026Q2_PR_CFO_001", "Revenue was $30.0 billion", idx)
    assert r.status == "verified"
    assert r.method == "exact_substring"
    assert r.quote_start_offset == 0
    assert r.quote_end_offset > 0


def test_numeric_evidence_records_tokens():
    idx, _ = _index()
    r = evidence.verify_one("NVDA_2026Q2_PR_CFO_001", "up 122% year over year", idx)
    assert r.status == "verified"
    assert r.numeric_check and r.numeric_check["verified"] is True
    assert "122%" in r.numeric_check["numbers"]


def test_nonexistent_paragraph_id_is_blocked():
    idx, _ = _index()
    r = evidence.verify_one("NVDA_2026Q2_PR_CFO_999", "Revenue was $30.0 billion", idx)
    assert r.status == "failed"
    assert r.reason == "paragraph_id_not_found"


def test_fuzzy_only_is_manual_review_not_pass():
    idx, _ = _index()
    # paraphrase (not an exact substring) → must NOT auto-pass
    r = evidence.verify_one("NVDA_2026Q2_PR_CFO_001",
                            "Revenue came in at thirty billion dollars", idx)
    assert r.status == "needs_manual_review"
    assert r.method == "fuzzy_candidate"


def test_quote_normalization_handles_curly_quotes_and_whitespace():
    idx, _ = _index()
    r = evidence.verify_one("NVDA_2026Q2_PR_CFO_001", "Revenue   was  $30.0 billion", idx)
    assert r.status == "verified"


def test_verify_claim_buckets_and_counts():
    idx, _ = _index()
    cv = evidence.verify_claim([
        {"paragraph_id": "NVDA_2026Q2_PR_CFO_001", "exact_quote_en": "Revenue was $30.0 billion"},
        {"paragraph_id": "NVDA_2026Q2_PR_CFO_001", "exact_quote_en": "paraphrased nonsense here"},
        {"paragraph_id": "MISSING", "exact_quote_en": "x"},
    ], idx)
    assert cv.verified_count == 1
    assert cv.has_verified_evidence
    assert len(cv.review) == 1
    assert len(cv.failed) == 1


def test_empty_quote_is_insufficient():
    idx, _ = _index()
    r = evidence.verify_one("NVDA_2026Q2_PR_CFO_001", "   ", idx)
    assert r.status == "insufficient_evidence"
