"""Load turnaround-screener config from turnaround_config.yaml (repo root), with
safe defaults. Mirrors app/flat/config.py: a partial YAML is deep-merged over the
built-in DEFAULTS so every threshold is tunable without touching code, and a
missing/broken file never breaks a scan.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(os.environ.get("SUH_DH_TURNAROUND_CONFIG",
                                 ROOT / "turnaround_config.yaml"))

# Candidate base lengths swept per ticker. Finer near the short end because a
# bottom base that just finished tightening is usually 25-60 days long.
PERIODS = [20, 25, 30, 40, 50, 60, 80, 100, 120]

DEFAULTS: dict[str, Any] = {
    # --- universe -------------------------------------------------------
    # Deliberately NO moving-average filter: this screener lives BELOW the
    # 200-day, which is exactly where the base screener's finviz pre-filter
    # (price_above_sma50/sma200) refuses to look. ETFs and REITs are excluded
    # outright — a turnaround is a single-company story, not a basket.
    "universe": {
        "source": "finviz",
        "include_adr": True,
        "max_candidates": 3000,
    },
    "min_price": 1.0,
    "min_market_cap": 300_000_000,
    "min_avg_dollar_volume_20d": 6_000_000,
    # Need base(<=120) + a year of pre-base context for the trough search.
    "min_history_days": 300,
    # Dead / deal-pinned names (merger-arb pinned to a deal price) score well on
    # every tightness metric but are untradeable. Same gate as base/flat.
    "min_base_daily_vol": 0.005,

    # --- bottom gate: "it actually fell" --------------------------------
    "bottom": {
        # Peak window for the drawdown test. Intentionally longer than a year:
        # a base that has been building for 12+ months pushes the pre-decline
        # peak out of a 252-day window, and the drawdown would be measured
        # against a high made inside the base itself.
        "high_lookback": 756,
        # Price must sit at least this far below that peak. This is the base
        # screener's min_price_vs_52w_high (0.75) turned upside down.
        "min_off_52w_high": 0.30,
        # ... but not already doubled off the low — that turnaround is over.
        "max_off_52w_low": 1.00,
        # Falling-knife guard: the low of the last N sessions must not undercut
        # the low of everything before it. Phrased as "new low", not "at the
        # 52-week low" — a flat base resting on its lows re-touches the 52-week
        # low constantly and would be excluded forever.
        "no_new_low_days": 20,
        "new_low_tolerance": 0.01,
    },

    # --- trough anchor ---------------------------------------------------
    "trough": {
        "lookback": 252,
        # Use the FIRST bar within this tolerance of the running low, not the
        # exact argmin: on a double bottom ($10.00 then $9.98) argmin picks the
        # right-hand low, which is not when the bottom was actually formed.
        "tolerance": 0.03,
    },

    # --- base window detection ------------------------------------------
    "base": {
        "min_length_days": 20,
        "max_length_days": 120,
        "min_depth": 0.05,
        # Looser than the base screener's 0.35: a bottom base is deeper by
        # nature. The decline-swallow guards below are what keep this honest.
        "max_depth": 0.40,
        # The trough must land within the first 70% of the base window; a low
        # in the last 30% means the stock is still making lows, not basing.
        "low_early_frac": 0.70,
        # Where the last close sits inside the window's own high-low range.
        # This is what rejects a window that swallowed a gentle decline: such a
        # window's right side is a low shelf near its floor (recovery ~0.4),
        # while a real right edge — flat base or the right side of a cup — sits
        # in the upper half (0.8+). A front-third slope test cannot do this job:
        # the descending left side of a legitimate cup fails it too.
        "min_recovery": 0.45,
        # A base goes sideways; a slice of a vertical advance does not. Without
        # this, a short window drawn inside a run looks like a textbook right
        # edge (low at the left, price at the high, modest depth).
        "max_drift": 0.20,
    },

    # --- base quality (40 pts) — computed from the trough forward --------
    "quality": {
        "contraction_weight": 12,
        "support_weight": 10,
        "dryup_weight": 10,
        "containment_weight": 8,
        # contraction: late-third range / early-third range (post-trough)
        "contraction_full": 0.60,   # <=0.60 -> full marks
        "contraction_zero": 1.00,   # >=1.00 -> zero
        # dry-up: recent 10-day volume / 50-day average
        "dryup_full": 0.65,
        "dryup_zero": 1.10,
        # containment: fraction of closes within +/-7.5% of the base median
        "containment_floor": 0.60,
        "containment_span": 0.30,
    },

    # --- right edge (30 pts) ---------------------------------------------
    "edge": {
        # Effective pivot = whichever is nearer: the base high, or the recent
        # ledge/handle high. A deep bottom base's own high can be 30% away, so
        # the ledge is what actually gets challenged first.
        "ledge_lookback": 15,
        "ready_threshold": 0.05,    # within 5% of pivot -> "ready"
        "watch_threshold": 0.12,    # within 12% -> "watch"
        # Position of the last close inside the base band (0 = low, 1 = high).
        "min_position": 0.50,
        "position_full": 0.85,
        # Recent tightening: last 10 days' average range vs the base average.
        "tighten_full": 0.60,
        "tighten_zero": 1.10,
        # Extension: past this far above the pivot the move is gone.
        "max_extension": 0.15,      # hard exclude, relative to the base high
        # Second, window-independent extension test. Price this far above its
        # 50-day has already moved, whatever window you draw around it. Sits
        # between the base screener's inbase.sma50_stretch (1.12) and its
        # alerts.extended_sma50_ratio (1.20) — loose enough to keep a stock that
        # just gapped out of a tight base, tight enough to drop a sustained run.
        "max_sma50_stretch": 1.18,
        "extension_zero": 0.08,     # readiness score hits 0 here
        "weights": {
            "distance": 0.40,   # how close to the effective pivot
            "position": 0.30,   # where in the base band the price sits
            "tighten": 0.30,    # is the right edge tightening
        },
    },

    # --- bottom setup (20 pts): is the decline actually over -------------
    "setup": {
        "slope_lookback_fast": 20,   # SMA50 slope window
        "slope_lookback_slow": 40,   # SMA200 slope window
        # SMA200 slope: still negative is fine, but it must have flattened.
        "slope200_zero": -0.10,      # -10% over 40d -> no credit
        "slope200_full": 0.00,       # flat or rising -> full credit
        "slope50_zero": -0.08,
        "slope50_full": 0.02,
        "weights": {
            "decel": 0.35,       # 200d slope flattening / turning up
            "ma_recover": 0.35,  # price vs SMA50 / SMA200
            "rs_repair": 0.30,   # RS line no longer making lows
        },
        # RS line repair is measured over the base window vs its own low.
        "rs_repair_full": 0.08,
    },

    # --- first-turn triggers (10 pts) ------------------------------------
    "triggers": {
        "fresh_days": 5,             # a trigger counts as "fresh" this long
        "power_bar_vol_mult": 2.5,   # volume >= 50d avg * this
        "power_bar_min_ret": 0.05,   # and close up >= 5%
        "power_bar_close_loc": 0.70, # and closed in the top 30% of its range
        "earnings_gap_min": 0.05,    # gap/day move >= 5% on an earnings day
        "earnings_gap_vol_mult": 3.0,
        "earnings_window_days": 2,   # D+0 / D+1 counts as the earnings reaction
        "pocket_pivot_lookback": 10,
        "reclaim_below_days": 60,    # must have been under the 200d this long
        "score": 10,
    },

    # --- score weights (sum = 100) ---------------------------------------
    "score": {
        "edge_weight": 30,
        "quality_weight": 40,
        "setup_weight": 20,
        "trigger_weight": 10,
    },
    "grades": {"prime": 80, "high": 68, "watch": 55},

    # --- earnings D-day column -------------------------------------------
    # The killer filter: a bottom base at its right edge with earnings due.
    # Off by default because it costs one extra network call per surviving name.
    "earnings": {
        "enabled": True,
        "max_lookup": 120,      # only for the top N records, by score
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


_cached: dict | None = None


def load(force: bool = False) -> dict:
    global _cached
    if _cached is not None and not force:
        return _cached
    user: dict = {}
    if CONFIG_PATH.exists():
        try:
            import yaml

            loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                user = loaded
        except Exception:
            user = {}
    _cached = _deep_merge(DEFAULTS, user)
    return _cached
