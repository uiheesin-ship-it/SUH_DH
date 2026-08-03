"""Transcript provider abstraction (spec §6.1).

Priority chain: official transcript API → company IR → webcast/text → user
upload → other permitted sources. The MVP ships the Mock and ManualUpload
adapters (the others are slots for later phases). No unlicensed scraping is
assumed, and full English transcripts are not redistributed (spec §6.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ...services import textnorm


@dataclass
class TranscriptRef:
    ticker: str
    fiscal_year: int
    fiscal_quarter: int
    source: str
    source_identifier: str | None = None


@dataclass
class RawTranscript:
    """Canonical transcript payload the preprocessor consumes.

    ``structured`` is the preferred shape (sections→turns). ``raw_text`` is an
    alternative for plaintext sources. Exactly one should be populated.
    """

    ticker: str
    fiscal_year: int
    fiscal_quarter: int
    call_date: str | None = None
    company: str | None = None
    source: str = "mock"
    source_url: str | None = None
    language: str = "en"
    license_note: str | None = None
    structured: dict | None = None       # {"sections": [...]}
    raw_text: str | None = None
    published_at: str | None = None
    extra: dict = field(default_factory=dict)

    def checksum(self) -> str:
        body = self.raw_text if self.raw_text is not None else str(self.structured)
        return textnorm.sha256(f"{self.ticker}|{self.fiscal_year}|{self.fiscal_quarter}|{body}")


class TranscriptDataProvider(Protocol):
    name: str

    def list_available(self, ticker: str, since=None) -> list[TranscriptRef]: ...

    def fetch(self, ref: TranscriptRef) -> RawTranscript: ...
