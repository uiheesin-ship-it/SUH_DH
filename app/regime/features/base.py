"""Feature descriptors and the registry that ties builders together.

A *feature* is one number describing the market as of the close of day *t*,
computed from data up to and including *t* only. Each builder returns

    (values, specs, aux)

where ``values`` holds the feature columns, ``specs`` describes them for the UI
(label, group, display format, default weight) and ``aux`` carries helper
series the charts want (SMA lines, distribution-day flags) that are not
features themselves.

Adding a feature family — VIX term structure, market breadth, credit spreads —
means writing one builder module and calling :func:`register`. Nothing in the
similarity, forward-return or validation layers has to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

import pandas as pd

GROUPS = ("Trend", "Momentum", "Volatility", "Distribution", "Macro")


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    label: str
    group: str
    fmt: str = "num"            # pct | bp | num | days | count | score
    default_weight: float = 0.0
    description: str = ""

    def format(self, value) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "–"
        if self.fmt == "pct":
            return f"{value:+.2f}%"
        if self.fmt == "pct_abs":   # 변동성처럼 부호가 의미 없는 값
            return f"{value:.2f}%"
        if self.fmt == "bp":
            return f"{value:+.0f}bp"
        if self.fmt in ("count", "days"):
            return f"{value:.0f}"
        if self.fmt == "score":
            return f"{value:+.2f}"
        return f"{value:,.2f}"


@dataclass
class FeatureSet:
    """Feature matrix + descriptors + charting helpers, all on one calendar."""

    values: pd.DataFrame
    specs: dict[str, FeatureSpec] = field(default_factory=dict)
    aux: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def keys(self) -> list[str]:
        return list(self.values.columns)

    def by_group(self) -> dict[str, list[FeatureSpec]]:
        out: dict[str, list[FeatureSpec]] = {}
        for key in self.values.columns:
            spec = self.specs.get(key)
            if spec is None:
                continue
            out.setdefault(spec.group, []).append(spec)
        return out

    def valid_mask(self, keys: list[str] | None = None) -> pd.Series:
        """Days whose features are fully computed.

        Columns that are empty end to end (e.g. a macro series the provider
        could not deliver today) are ignored rather than invalidating every
        row — a missing 10Y feed must not blank out the whole analysis.
        """
        cols = [k for k in (keys or list(self.values.columns))
                if k in self.values.columns and self.values[k].notna().any()]
        if not cols:
            return pd.Series(False, index=self.values.index)
        return self.values[cols].notna().all(axis=1)

    def row(self, date) -> pd.Series:
        return self.values.loc[pd.Timestamp(date)]

    def describe_row(self, date) -> dict[str, str]:
        row = self.row(date)
        return {self.specs[k].label: self.specs[k].format(row[k])
                for k in self.values.columns if k in self.specs}


Builder = Callable[..., tuple[pd.DataFrame, Iterable[FeatureSpec], pd.DataFrame]]
_BUILDERS: list[Builder] = []


def register(builder: Builder) -> Builder:
    """Register a feature builder (decorator-friendly)."""
    if builder not in _BUILDERS:
        _BUILDERS.append(builder)
    return builder


def builders() -> list[Builder]:
    return list(_BUILDERS)
