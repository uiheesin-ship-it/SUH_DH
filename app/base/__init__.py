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

# A full scan is expensive, so the live endpoint caches for a while; the static
# GitHub Pages build calls run_scan() directly and writes data/base.json.
SCREEN_TTL = float(os.environ.get("SUH_DH_BASE_TTL", "1800"))

__all__ = ["run_scan", "get_screen", "load_config"]


def get_screen() -> dict:
    def producer():
        return run_scan()

    return cache.get_or_set("base_screen", SCREEN_TTL, producer,
                            cache_when=lambda d: bool(d and d.get("stocks")))
