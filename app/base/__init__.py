"""Base Screener — "healthy base" stock screener for the SUH_DH dashboard.

Public entry points:
  run_scan()   -> run a fresh scan (heavy; hits the network unless SUH_DH_DEMO=1)
  get_screen() -> cached wrapper for the live FastAPI endpoint
"""

from __future__ import annotations

import os

from .. import cache
from .config import load as load_config
from .screen import run_scan
from .screen_kr import run_scan as run_scan_kr

# A full scan is expensive, so the live endpoint caches for a while; the static
# GitHub Pages build calls run_scan() directly and writes data/base.json.
SCREEN_TTL = float(os.environ.get("SUH_DH_BASE_TTL", "1800"))

__all__ = ["run_scan", "get_screen", "run_scan_kr", "get_screen_kr", "load_config"]


def get_screen() -> dict:
    def producer():
        return run_scan()

    return cache.get_or_set("base_screen", SCREEN_TTL, producer,
                            cache_when=lambda d: bool(d and d.get("stocks")))


def get_screen_kr() -> dict:
    def producer():
        return run_scan_kr()

    return cache.get_or_set("base_screen_kr", SCREEN_TTL, producer,
                            cache_when=lambda d: bool(d and d.get("stocks")))
