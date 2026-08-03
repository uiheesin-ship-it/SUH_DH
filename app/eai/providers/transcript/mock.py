"""Mock transcript provider — reads bundled fixtures (spec §6.1, §23).

Fixtures live in app/eai/fixtures/transcripts/<TICKER>_<FY>Q<Q>.json and use
the canonical structured shape (sections→turns). Used for the 6-company MVP
and offline tests, with no network access.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import RawTranscript, TranscriptRef

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "transcripts"


class MockTranscriptProvider:
    name = "mock"

    def __init__(self, fixture_dir: Path | None = None) -> None:
        self.dir = fixture_dir or FIXTURE_DIR

    def list_available(self, ticker: str, since=None) -> list[TranscriptRef]:
        refs = []
        for path in sorted(self.dir.glob(f"{ticker.upper()}_*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            refs.append(TranscriptRef(
                ticker=data["ticker"], fiscal_year=int(data["fiscal_year"]),
                fiscal_quarter=int(data["fiscal_quarter"]), source="mock",
                source_identifier=path.name,
            ))
        return refs

    def fetch(self, ref: TranscriptRef) -> RawTranscript:
        path = self.dir / (ref.source_identifier or
                            f"{ref.ticker.upper()}_{ref.fiscal_year}Q{ref.fiscal_quarter}.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        return RawTranscript(
            ticker=data["ticker"], fiscal_year=int(data["fiscal_year"]),
            fiscal_quarter=int(data["fiscal_quarter"]), call_date=data.get("call_date"),
            company=data.get("company"), source="mock",
            language=data.get("language", "en"),
            license_note="mock fixture (synthetic, safe to redistribute)",
            structured={"sections": data["sections"]},
            published_at=data.get("published_at"),
        )
