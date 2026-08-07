"""Load flat-screener config from flat_config.yaml (repo root), with safe
defaults. Mirrors app/base/config.py: a partial YAML is deep-merged over the
built-in DEFAULTS so every threshold is tunable without touching code, and a
missing/broken file never breaks a scan.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(os.environ.get("SUH_DH_FLAT_CONFIG", ROOT / "flat_config.yaml"))

# All base-period lengths evaluated independently (spec §3).
PERIODS = [20, 30, 40, 50, 60, 80, 100, 120]

DEFAULTS: dict[str, Any] = {
    # --- universe (spec §2) ---
    "universe": {
        "source": "finviz",
        "include_reit": False,     # REIT excluded by default
        "include_adr": True,
        "max_candidates": 3000,    # raised: no share-vol filter -> bigger universe
    },
    # Quality floor is market cap, not price. min_price is only a sub-$1
    # penny-stock data-noise guard; min_market_cap does the real filtering.
    "min_price": 1.0,
    "min_market_cap": 300_000_000,   # small-cap and up
    "min_avg_dollar_volume_20d": 10_000_000,
    # Need base(≤120) + prior activity(≤252) for a clean, look-ahead-free split.
    "min_history_days": 180,
    # --- base status band (spec §6) ---
    "status": {
        "lower_mult": 0.97,        # active if close >= Q10 * 0.97
        "upper_mult": 1.03,        # active if close <= Q90 * 1.03
        "exclude_recent_days": 0,  # >0 drops the last N days from the status Q10/Q90
    },
    # --- per-period flatness thresholds (spec §5). Buckets keyed by the max day
    #     count of the bucket; a period uses the first bucket whose max >= n. ---
    "thresholds": {
        "short": {   # 20-40 trading days
            "max_len": 40,
            "close_band": 0.12, "base_drift": 0.06,
            "containment": 0.80, "center_shift": 0.06, "outlier_ratio": 0.05,
        },
        "mid": {     # 41-80 trading days
            "max_len": 80,
            "close_band": 0.18, "base_drift": 0.08,
            "containment": 0.80, "center_shift": 0.07, "outlier_ratio": 0.05,
        },
        "long": {    # 81-120 trading days
            "max_len": 120,
            "close_band": 0.22, "base_drift": 0.10,
            "containment": 0.80, "center_shift": 0.08, "outlier_ratio": 0.05,
        },
    },
    # --- prior-trend tag (spec §7) ---
    "prior_trend": {
        "lookbacks": [60, 120],
        "continuation_min": 0.20,   # representative_prior_return >= +20% => Continuation
        "turnaround_max": -0.20,    # <= -20% => Turnaround
    },
    # --- extra acceptance criteria by category (spec §8) ---
    "acceptance": {
        "continuation": {"min_len": 20, "min_score": 70},
        "turnaround_neutral": {
            "min_len": 40, "min_score": 80, "min_containment": 0.85,
            "max_drift": 0.05, "max_center_shift": 0.05,
            "require_historical_activity": True,
        },
    },
    # --- historical activity filter (spec §9) — pre-base data only ---
    "historical_activity": {
        "prior_short_window": 120,
        "prior_long_window": 252,
        "min_prior_120_close_band": 0.20,
        "min_max_abs_move": 0.15,
        "min_base_distinctness": 1.5,
        "max_abs_lookbacks": [20, 60],
    },
    # --- chronically low volatility exclusion (spec §10) ---
    "chronic_low_vol": {
        "max_prior_252_close_band": 0.20,
        "max_abs_20d": 0.12,
        "max_abs_60d": 0.12,
        "max_base_distinctness": 1.3,
    },
    # --- flatness score weights (spec §11) — must sum to 100 ---
    "score": {
        "range_weight": 35,
        "slope_weight": 25,
        "containment_weight": 20,
        "center_weight": 10,
        "outlier_weight": 10,
        "containment_floor": 0.60,   # containment score ramps 0.60 -> 0.90
        "containment_span": 0.30,
        "outlier_scale": 0.05,       # outlier score hits 0 at 5% outlier days
    },
    # --- flatness grade cuts (spec §12) ---
    "grades": {"very_flat": 85, "flat": 75, "moderate": 65},
    # how many runner-up base periods to keep per ticker (spec §17)
    "top_candidates": 3,
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


def thresholds_for(n: int, cfg: dict) -> dict:
    """Return the flatness thresholds for a base of ``n`` trading days."""
    th = cfg["thresholds"]
    for key in ("short", "mid", "long"):
        bucket = th[key]
        if n <= int(bucket["max_len"]):
            return bucket
    return th["long"]
