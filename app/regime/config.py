"""Tunable parameters for the Market Regime Lab.

Every knob the Streamlit sidebar exposes has a default here, and the defaults
can be overridden without touching code via ``regime_config.yaml`` at the repo
root (same deep-merge pattern as flat_config.yaml / turnaround_config.yaml).

The parameters are grouped into small dataclasses so the analysis functions
take one explicit object instead of a dozen loose keyword arguments. That keeps
the UI layer thin, makes every calculation unit-testable offline, and means a
new data source / feature only has to extend one group.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(os.environ.get("SUH_DH_REGIME_CONFIG", ROOT / "regime_config.yaml"))

DEFAULTS: dict[str, Any] = {
    "market": {
        "ticker": "^IXIC",
        "years": 20,
        "exogenous": [
            {"key": "y10", "label": "US 10Y Treasury yield",
             "symbol": "^TNX", "source": "yahoo", "unit": "percent"},
        ],
    },
    "features": {
        "sma_windows": [20, 50, 100, 200],
        "slope_window": 20,
        "slope_smas": [50, 200],
        "return_windows": [5, 20, 60, 120],
        "high_window": 252,
        "vol_window": 20,
        "atr_window": 14,
        "yield_change_windows": [20, 120],
        "yield_pctile_window": 252,
    },
    "distribution_day": {
        "lookback": 25,
        "drop_pct": 0.2,
        "volume_bump_pct": 0.0,
        "clv_max": 0.5,
        "days_since_cap": 120,
    },
    "similarity": {
        "top_n": 25,
        "min_gap": 20,
        "episode_pick": "best",
        "exclude_recent": 120,
        "require_full_horizon": False,
        "normalization": "robust",
        "min_history": 250,
        "max_distance": None,
        "weights": {
            "px_vs_sma50": 1.0,
            "px_vs_sma200": 1.0,
            "sma_stack": 1.0,
            "sma50_slope": 0.5,
            "sma200_slope": 0.5,
            "ret_20": 1.0,
            "ret_60": 0.5,
            "dd_52w": 1.5,
            "vol_realized": 1.0,
            "dd_count": 1.5,
            "y10_chg_120d": 0.5,
        },
    },
    "forward": {
        "horizons": [5, 20, 60, 120],
        "bootstrap_samples": 2000,
        "ci_level": 0.95,
        "min_sample_warn": 10,
        "seed": 20240101,
    },
    "validation": {
        "mode": "fixed",
        "train_end": "2015-12-31",
        "validation_end": "2020-12-31",
        "step": 5,
        "expanding_start": "2016-01-01",
        "horizon": 20,
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def deep_merge(base: dict, over: dict) -> dict:
    """Public alias of the config merger — API/UI 레이어가 사용자가 보낸 파라미터를
    기본 설정 위에 얹을 때 씁니다(계산 로직과 무관한 설정 병합)."""
    return _deep_merge(base, over)


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """DEFAULTS deep-merged with regime_config.yaml. A missing or broken file
    never breaks the app — we fall back to the built-in defaults."""
    p = Path(path or CONFIG_PATH)
    try:
        import yaml  # optional; defaults work without it

        with p.open("r", encoding="utf-8") as fh:
            user = yaml.safe_load(fh) or {}
        if not isinstance(user, dict):
            user = {}
    except Exception:
        user = {}
    return _deep_merge(DEFAULTS, user)


@dataclass(frozen=True)
class FeatureParams:
    """Windows for the trend / momentum / volatility block."""

    sma_windows: tuple[int, ...] = (20, 50, 100, 200)
    slope_window: int = 20
    slope_smas: tuple[int, ...] = (50, 200)
    return_windows: tuple[int, ...] = (5, 20, 60, 120)
    high_window: int = 252
    vol_window: int = 20
    atr_window: int = 14
    yield_change_windows: tuple[int, ...] = (20, 120)
    yield_pctile_window: int = 252

    @classmethod
    def from_config(cls, cfg: dict) -> "FeatureParams":
        f = (cfg or {}).get("features", {})
        return cls(
            sma_windows=tuple(int(x) for x in f.get("sma_windows", (20, 50, 100, 200))),
            slope_window=int(f.get("slope_window", 20)),
            slope_smas=tuple(int(x) for x in f.get("slope_smas", (50, 200))),
            return_windows=tuple(int(x) for x in f.get("return_windows", (5, 20, 60, 120))),
            high_window=int(f.get("high_window", 252)),
            vol_window=int(f.get("vol_window", 20)),
            atr_window=int(f.get("atr_window", 14)),
            yield_change_windows=tuple(int(x) for x in f.get("yield_change_windows", (20, 120))),
            yield_pctile_window=int(f.get("yield_pctile_window", 252)),
        )


@dataclass(frozen=True)
class DistributionParams:
    """Distribution-day (기관 매도일) detection thresholds.

    A day counts when *all three* hold: return <= -drop_pct%, volume >=
    previous volume * (1 + volume_bump_pct/100), and close location value
    (Close-Low)/(High-Low) <= clv_max.
    """

    lookback: int = 25
    drop_pct: float = 0.2
    volume_bump_pct: float = 0.0
    clv_max: float = 0.5
    days_since_cap: int = 120

    @classmethod
    def from_config(cls, cfg: dict) -> "DistributionParams":
        d = (cfg or {}).get("distribution_day", {})
        return cls(
            lookback=int(d.get("lookback", 25)),
            drop_pct=float(d.get("drop_pct", 0.2)),
            volume_bump_pct=float(d.get("volume_bump_pct", 0.0)),
            clv_max=float(d.get("clv_max", 0.5)),
            days_since_cap=int(d.get("days_since_cap", 120)),
        )


@dataclass(frozen=True)
class SimilarityParams:
    """How the current feature vector is compared with history."""

    weights: dict[str, float] = field(default_factory=dict)
    top_n: int = 25
    min_gap: int = 20
    episode_pick: str = "best"          # best | first
    exclude_recent: int = 120
    require_full_horizon: bool = False
    normalization: str = "robust"       # robust (median/MAD) | zscore (mean/std)
    min_history: int = 250
    max_distance: float | None = None

    @classmethod
    def from_config(cls, cfg: dict) -> "SimilarityParams":
        s = (cfg or {}).get("similarity", {})
        md = s.get("max_distance", None)
        return cls(
            weights={str(k): float(v) for k, v in (s.get("weights") or {}).items()},
            top_n=int(s.get("top_n", 25)),
            min_gap=int(s.get("min_gap", 20)),
            episode_pick=str(s.get("episode_pick", "best")),
            exclude_recent=int(s.get("exclude_recent", 120)),
            require_full_horizon=bool(s.get("require_full_horizon", False)),
            normalization=str(s.get("normalization", "robust")),
            min_history=int(s.get("min_history", 250)),
            max_distance=None if md in (None, "") else float(md),
        )

    def with_weights(self, weights: dict[str, float]) -> "SimilarityParams":
        return replace(self, weights=dict(weights))


@dataclass(frozen=True)
class ForwardParams:
    """Forward-return horizons, sample-independence handling and bootstrap."""

    horizons: tuple[int, ...] = (5, 20, 60, 120)
    bootstrap_samples: int = 2000
    ci_level: float = 0.95
    min_sample_warn: int = 10
    seed: int = 20240101
    # all     : 모든 match 사용 + 겹침을 cluster bootstrap 으로 반영 (기본)
    # horizon : horizon 별로 최소 h거래일 간격을 다시 강제해 완전 비중첩 표본 사용
    independence: str = "all"
    # cluster : 에피소드 단위 재표본 (겹침 반영) / iid : 단순 재표본(비교용)
    ci_method: str = "cluster"

    @classmethod
    def from_config(cls, cfg: dict) -> "ForwardParams":
        f = (cfg or {}).get("forward", {})
        return cls(
            horizons=tuple(int(x) for x in f.get("horizons", (5, 20, 60, 120))),
            bootstrap_samples=int(f.get("bootstrap_samples", 2000)),
            ci_level=float(f.get("ci_level", 0.95)),
            min_sample_warn=int(f.get("min_sample_warn", 10)),
            seed=int(f.get("seed", 20240101)),
            independence=str(f.get("independence", "all")),
            ci_method=str(f.get("ci_method", "cluster")),
        )


@dataclass(frozen=True)
class ValidationParams:
    """Out-of-sample / walk-forward validation layout."""

    mode: str = "fixed"                 # fixed | expanding
    train_end: str = "2015-12-31"
    validation_end: str = "2020-12-31"
    step: int = 5
    expanding_start: str = "2016-01-01"
    horizon: int = 20

    @classmethod
    def from_config(cls, cfg: dict) -> "ValidationParams":
        v = (cfg or {}).get("validation", {})
        return cls(
            mode=str(v.get("mode", "fixed")),
            train_end=str(v.get("train_end", "2015-12-31")),
            validation_end=str(v.get("validation_end", "2020-12-31")),
            step=int(v.get("step", 5)),
            expanding_start=str(v.get("expanding_start", "2016-01-01")),
            horizon=int(v.get("horizon", 20)),
        )


@dataclass(frozen=True)
class Params:
    """One bag with every parameter group, as handed around by the app."""

    ticker: str = "^IXIC"
    years: int = 20
    features: FeatureParams = field(default_factory=FeatureParams)
    distribution: DistributionParams = field(default_factory=DistributionParams)
    similarity: SimilarityParams = field(default_factory=SimilarityParams)
    forward: ForwardParams = field(default_factory=ForwardParams)
    validation: ValidationParams = field(default_factory=ValidationParams)
    exogenous: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_config(cls, cfg: dict | None = None) -> "Params":
        cfg = cfg or load_config()
        m = cfg.get("market", {})
        return cls(
            ticker=str(m.get("ticker", "^IXIC")),
            years=int(m.get("years", 20)),
            features=FeatureParams.from_config(cfg),
            distribution=DistributionParams.from_config(cfg),
            similarity=SimilarityParams.from_config(cfg),
            forward=ForwardParams.from_config(cfg),
            validation=ValidationParams.from_config(cfg),
            exogenous=tuple(dict(x) for x in (m.get("exogenous") or [])),
        )
