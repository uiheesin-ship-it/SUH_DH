"""Flat Base Screener — surface US stocks currently sitting in a flat, horizontal,
tight base.

Design principle (per the spec): this screener measures ONLY "how flat is the
current base right now". It never predicts breakouts, never recommends buys, and
deliberately does NOT compute volume / ATR / VCP / Bollinger / moving-average
alignment / Minervini / RS-vs-market / SPY-relative / sector-momentum /
fundamentals / breakout-probability.

Flatness and historical activity are computed SEPARATELY: the Flatness Score is
pure geometry of the base window; a separate Historical Activity Filter keeps
REITs / chronically dead names from topping the list on flatness alone.

Sector and an RS-percentile column are carried for display convenience only and
are NOT part of the Flatness Score.

Public entry points:
  run_scan()   -> run a fresh scan (heavy; hits the network unless SUH_DH_DEMO=1)
  get_screen() -> cached wrapper for the live FastAPI endpoint (/api/flat)
"""

from __future__ import annotations

import os

from .. import cache
from .config import load as load_config
from .screen import run_scan

# A full scan is expensive; the live endpoint caches, the static build calls
# run_scan() directly and writes data/flat.json.
SCREEN_TTL = float(os.environ.get("SUH_DH_FLAT_TTL", "1800"))

__all__ = ["run_scan", "get_screen", "load_config"]


def get_screen() -> dict:
    def producer():
        return run_scan()

    return cache.get_or_set("flat_screen", SCREEN_TTL, producer,
                            cache_when=lambda d: bool(d and d.get("stocks")))
