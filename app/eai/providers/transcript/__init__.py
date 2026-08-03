"""Transcript provider factory (spec §6.1)."""

from __future__ import annotations

from ... import config
from .base import RawTranscript, TranscriptDataProvider, TranscriptRef  # noqa: F401


def get_transcript_provider(name: str | None = None):
    name = name or config.provider_name("transcript")
    if name == "mock":
        from .mock import MockTranscriptProvider
        return MockTranscriptProvider()
    if name == "directory":
        from .directory import DirectoryTranscriptProvider
        return DirectoryTranscriptProvider()
    if name == "fmp":
        from .fmp import FMPTranscriptProvider
        return FMPTranscriptProvider()
    if name == "alphavantage":
        from .alphavantage import AlphaVantageTranscriptProvider
        return AlphaVantageTranscriptProvider()
    if name == "manual_upload":
        # ManualUpload is invoked per-file via from_upload(); expose the module.
        from . import manual_upload
        return manual_upload
    raise ValueError(f"Unknown transcript provider: {name}")
