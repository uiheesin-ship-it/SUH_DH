"""Turnaround Screener — US stocks building a healthy base at the BOTTOM, and
sitting at that base's right edge.

The gap it fills between the two existing screeners:

  * app.base  requires an uptrend (Minervini template, RS >= 80, within 25% of
              the 52-week high) and pre-filters Finviz to names above their 50-
              and 200-day. It cannot see anything down here.
  * app.flat  measures pure geometry and will find a flat base anywhere, but
              flatness is mandatory — a VCP, a cup, or an irregular bottom base
              simply does not qualify.

So this screener keeps the base geometry (which never needed an uptrend) and
inverts only the trend gates. It scores four properties every constructive base
shares regardless of shape — contraction, support, dry-up, containment — rather
than matching named patterns, because the base with no name is still a base.

Fundamentals are deliberately NOT scored. By the time an earnings turn is
visible the chart is usually extended; what is actionable beforehand is the
base. The one fundamental input kept is the *date* of the next report, as a
D-day column, so a right-edge base with a print due is easy to find.

Public entry points:
  run_scan()   -> run a fresh scan (heavy; hits the network unless SUH_DH_DEMO=1)
  get_screen() -> cached wrapper for the live FastAPI endpoint (/api/turnaround)
"""

from __future__ import annotations

import os

from .. import cache
from .config import load as load_config
from .screen import run_scan

SCREEN_TTL = float(os.environ.get("SUH_DH_TURNAROUND_TTL", "1800"))

__all__ = ["run_scan", "get_screen", "load_config"]


def get_screen() -> dict:
    def producer():
        return run_scan()

    return cache.get_or_set("turnaround_screen", SCREEN_TTL, producer,
                            cache_when=lambda d: bool(d and d.get("stocks")))
