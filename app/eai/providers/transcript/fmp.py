"""Licensed transcript API provider (spec §6.1, priority 1).

Fetches earnings-call transcripts over HTTP from a licensed API (default shape:
Financial Modeling Prep). This is the "automatically pull from the internet"
path — the daily workflow calls this, so new calls are ingested + analyzed with
no manual file drop. Requires EAI_TRANSCRIPT_API_KEY; the base URL is
configurable so any FMP-compatible endpoint works.

We deliberately use a *licensed* API, not scraping: the spec forbids assuming
unlicensed scraping, and full English transcripts are not redistributed — only
derived analysis + short verified quotes are stored/shown.

The API returns transcript text as one string; preprocessing's plaintext parser
turns it into paragraphs/speakers. Network errors on one ticker/quarter are
raised to the caller (jobs.ingest_company isolates them per-item so the batch
continues, spec §23).
"""

from __future__ import annotations

from ... import config
from .base import RawTranscript, TranscriptRef


class FMPTranscriptProvider:
    name = "fmp"

    def __init__(self, api_key: str | None = None, base: str | None = None) -> None:
        s = config.settings()
        self.api_key = api_key or s.transcript_api_key
        self.base = (base or s.transcript_api_base).rstrip("/")
        self.max_quarters = s.transcript_max_quarters

    # --- HTTP (isolated so tests can monkeypatch without a network) ---------
    def _get(self, url: str, params: dict):
        import httpx  # lazy

        params = {**params, "apikey": self.api_key}
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r.json()

    # --- provider interface -------------------------------------------------
    def list_available(self, ticker: str, since=None) -> list[TranscriptRef]:
        """List recent (quarter, year) transcripts, newest first, capped."""
        if not self.api_key:
            return []
        data = self._get(f"{self.base}/api/v4/earning_call_transcript",
                         {"symbol": ticker.upper()})
        refs: list[TranscriptRef] = []
        for row in data or []:
            # FMP v4 returns [quarter, year, date] triples.
            try:
                quarter, year = int(row[0]), int(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            refs.append(TranscriptRef(
                ticker=ticker.upper(), fiscal_year=year, fiscal_quarter=quarter,
                source="fmp", source_identifier=f"{year}Q{quarter}"))
        refs.sort(key=lambda r: (r.fiscal_year, r.fiscal_quarter), reverse=True)
        return refs[: self.max_quarters]

    def fetch(self, ref: TranscriptRef) -> RawTranscript:
        data = self._get(f"{self.base}/api/v3/earning_call_transcript/{ref.ticker}",
                         {"year": ref.fiscal_year, "quarter": ref.fiscal_quarter})
        if not data:
            raise ValueError(f"no transcript for {ref.ticker} {ref.fiscal_year}Q{ref.fiscal_quarter}")
        rec = data[0] if isinstance(data, list) else data
        content = rec.get("content") or ""
        if not content.strip():
            raise ValueError(f"empty transcript content for {ref.ticker}")
        date = (rec.get("date") or "").split(" ")[0] or None
        return RawTranscript(
            ticker=ref.ticker, fiscal_year=int(rec.get("year", ref.fiscal_year)),
            fiscal_quarter=int(rec.get("quarter", ref.fiscal_quarter)),
            call_date=date, published_at=date, source="fmp",
            source_url=f"{self.base}/api/v3/earning_call_transcript/{ref.ticker}",
            license_note="licensed transcript API (not redistributed)",
            raw_text=content)
