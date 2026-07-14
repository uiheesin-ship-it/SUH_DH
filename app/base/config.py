"""Load base-screener config from config.yaml (repo root), with safe defaults.

Every threshold in the base screener is driven from here so a user can tune the
behaviour without touching code. If PyYAML or the file is missing, the built-in
DEFAULTS keep the screener fully functional. Nested keys are deep-merged so a
partial config.yaml only overrides the values it actually sets.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

# Repo root = two levels up from this file (app/base/config.py -> repo/).
ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(os.environ.get("SUH_DH_BASE_CONFIG", ROOT / "config.yaml"))

DEFAULTS: dict[str, Any] = {
    "universe": {
        "source": "finviz",
        "include_adr": True,
        "max_candidates": 300,
        "finviz_price_above_sma50": True,
        "finviz_price_above_sma200": True,
    },
    "min_price": 10,
    "min_market_cap": 500_000_000,
    "min_avg_dollar_volume_20d": 20_000_000,
    "min_history_days": 200,
    "benchmarks": ["SPY", "QQQ", "IWM"],
    "base": {
        "min_length_days": 20,
        "max_length_days": 120,
        "min_depth": 0.05,
        "max_depth": 0.35,
        "pivot_ready_threshold": 0.05,
        "pivot_watch_threshold": 0.10,
        "breakout_extended_threshold": 0.05,
    },
    "trend_template": {
        "min_rs_percentile": 80,
        "min_price_vs_52w_low": 1.30,
        "min_price_vs_52w_high": 0.75,
    },
    "prior_uptrend": {"min_return": 0.25},
    "volatility": {
        "atr_length": 10,
        "atr_contraction_threshold": 0.75,
        "atr_contraction_excellent": 0.60,
        "range_contraction_threshold": 0.75,
        "recent_atr_compression": 0.80,
        "vcp_pass_ratio": 0.75,
        "vcp_excellent_ratio": 0.60,
    },
    "volume": {
        "dry_up_10d_vs_50d": 0.80,
        "dry_up_5d_vs_50d": 0.70,
        "high_volume_down_day_move": -0.03,
        "high_volume_down_day_threshold": 1.5,
        "high_volume_down_days_max": 2,
    },
    "sma50": {"min_ratio": 0.95, "max_ratio": 1.15},
    "rs_line": {"near_high_ratio": 0.98},
    "sector": {"near_high_ratio": 0.95},
    "rs_composite": {"w_3m": 0.4, "w_6m": 0.3, "w_12m": 0.3},
    "scoring": {
        "trend_weight": 25,
        "rs_weight": 20,
        "base_weight": 25,
        "vcp_weight": 15,
        "volume_weight": 10,
        "sector_weight": 5,
        "grade_prime": 85,
        "grade_high": 75,
        "grade_watch": 65,
    },
    "alerts": {
        "ready_min_score": 75,
        "ready_max_distance_to_pivot": 0.05,
        "breakout_min_score": 75,
        "extended_pivot_ratio": 1.05,
        "extended_sma50_ratio": 1.20,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into a copy of ``base``."""
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


_cached: dict | None = None


def load(force: bool = False) -> dict:
    """Return the merged config dict (DEFAULTS overlaid with config.yaml)."""
    global _cached
    if _cached is not None and not force:
        return _cached
    user: dict = {}
    if CONFIG_PATH.exists():
        try:
            import yaml  # optional dependency

            loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                user = loaded
        except Exception:
            # A malformed config must never crash the scan — fall back to defaults.
            user = {}
    _cached = _deep_merge(DEFAULTS, user)
    return _cached


class Config:
    """Convenience wrapper with dotted access and typed getters."""

    def __init__(self, data: dict | None = None):
        self._d = data if data is not None else load()

    def __getitem__(self, key: str) -> Any:
        return self._d[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._d.get(key, default)

    def section(self, name: str) -> dict:
        return self._d.get(name, {}) or {}


def get_config(force: bool = False) -> Config:
    return Config(load(force=force))
