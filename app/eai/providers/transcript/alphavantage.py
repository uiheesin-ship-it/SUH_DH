"""Alpha Vantage transcript API provider (spec §6.1, priority 1).

Alpha Vantage's EARNINGS_CALL_TRANSCRIPT returns a *structured* transcript
(speaker + title + content per turn), which maps cleanly to our canonical
sections→turns shape. The free tier allows ~25 requests/day (≈5/min) — enough
to test coverage on the 6-company MVP before committing to a paid plan
(recommended path: mock/upload → Alpha Vantage free → paid only if it pays off).

Requires EAI_ALPHAVANTAGE_API_KEY. Licensed API (not scraping); full text is
not redistributed — only derived analysis + verified short quotes are stored.
"""

from __future__ import annotations

import re

from ... import config
from ...services.preprocess import role_from_title
from .base import RawTranscript, TranscriptRef

_QA_MARK = re.compile(
    r"(question[\s-]and[\s-]answer|q\s*&\s*a|questions?\s+and\s+answers?)", re.I)


class AlphaVantageTranscriptProvider:
    name = "alphavantage"

    def __init__(self, api_key: str | None = None, base: str | None = None) -> None:
        s = config.settings()
        self.api_key = api_key or s.alphavantage_api_key
        self.base = (base or s.alphavantage_base).rstrip("/")
        self.max_quarters = s.transcript_max_quarters

    # --- HTTP (isolated so tests can monkeypatch without a network) ---------
    def _get(self, params: dict) -> dict:
        import httpx  # lazy

        params = {**params, "apikey": self.api_key}
        with httpx.Client(timeout=30.0) as client:
            r = client.get(f"{self.base}/query", params=params)
            r.raise_for_status()
            return r.json()

    # --- provider interface -------------------------------------------------
    def list_available(self, ticker: str, since=None) -> list[TranscriptRef]:
        """Recent reported quarters (from EARNINGS), newest first, capped.

        Alpha Vantage has no transcript-list endpoint; the docs say to verify
        available periods via EARNINGS, which we do so we only spend transcript
        requests on quarters that exist.
        """
        if not self.api_key:
            return []
        data = self._get({"function": "EARNINGS", "symbol": ticker.upper()})
        if _rate_limited(data):
            return []
        refs: list[TranscriptRef] = []
        for row in data.get("quarterlyEarnings", []) or []:
            fde = row.get("fiscalDateEnding") or ""
            try:
                year, month = int(fde[:4]), int(fde[5:7])
            except (ValueError, IndexError):
                continue
            quarter = (month - 1) // 3 + 1  # calendar quarter label AV expects
            refs.append(TranscriptRef(
                ticker=ticker.upper(), fiscal_year=year, fiscal_quarter=quarter,
                source="alphavantage", source_identifier=f"{year}Q{quarter}"))
        refs.sort(key=lambda r: (r.fiscal_year, r.fiscal_quarter), reverse=True)
        return refs[: self.max_quarters]

    def fetch(self, ref: TranscriptRef) -> RawTranscript:
        qlabel = f"{ref.fiscal_year}Q{ref.fiscal_quarter}"
        data = self._get({"function": "EARNINGS_CALL_TRANSCRIPT",
                          "symbol": ref.ticker, "quarter": qlabel})
        if _rate_limited(data):
            raise RuntimeError("Alpha Vantage rate limit / info message")
        turns = data.get("transcript") or []
        if not turns:
            raise ValueError(f"no transcript for {ref.ticker} {qlabel}")

        sections = _to_sections(turns)
        return RawTranscript(
            ticker=ref.ticker, fiscal_year=ref.fiscal_year, fiscal_quarter=ref.fiscal_quarter,
            source="alphavantage",
            source_url=f"{self.base}/query?function=EARNINGS_CALL_TRANSCRIPT&symbol={ref.ticker}",
            license_note="licensed transcript API (not redistributed)",
            structured={"sections": sections})


def _rate_limited(data: dict) -> bool:
    # AV returns {"Information": ...} or {"Note": ...} when throttled/limited.
    return isinstance(data, dict) and ("Information" in data or "Note" in data)


def _to_sections(turns: list[dict]) -> list[dict]:
    """Split AV turns into Prepared Remarks vs Q&A and assign speaker roles.

    AV turns carry speaker+title+content but no section marker, so we flip to
    Q&A at the first analyst speaker or the operator's "question-and-answer"
    transition, then let parse_structured link questions↔answers.
    """
    pre: list[dict] = []
    qa: list[dict] = []
    in_qa = False
    for t in turns:
        speaker = (t.get("speaker") or "").strip()
        title = (t.get("title") or "").strip()
        content = t.get("content") or ""
        section = "qa" if in_qa else "prepared_remarks"
        role = ("operator" if speaker.lower() == "operator"
                else role_from_title(title, section))
        if not in_qa and (role == "analyst" or _QA_MARK.search(content)):
            in_qa = True
            if role != "operator" and speaker.lower() != "operator":
                role = role_from_title(title, "qa")
        (qa if in_qa else pre).append(
            {"speaker_name": speaker, "speaker_role": role, "text": content})
    return [{"section_type": "prepared_remarks", "turns": pre},
            {"section_type": "qa", "turns": qa}]
