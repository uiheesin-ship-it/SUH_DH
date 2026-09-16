"""Feature engineering layer.

``build_features(market, params)`` runs every registered builder and returns
one :class:`FeatureSet` — the single input the similarity, strict-match and
validation layers work from.
"""

from __future__ import annotations

import pandas as pd

from .base import FeatureSet, FeatureSpec, builders, register  # noqa: F401
from . import distribution, macro, momentum, trend, volatility

for _b in (trend.build, momentum.build, volatility.build, distribution.build, macro.build):
    register(_b)


def build_features(market, params) -> FeatureSet:
    frames: list[pd.DataFrame] = []
    auxes: list[pd.DataFrame] = []
    specs: dict[str, FeatureSpec] = {}
    for builder in builders():
        values, spec_list, aux = builder(market, params)
        if values is not None and not values.empty:
            frames.append(values)
        for spec in spec_list:
            specs[spec.key] = spec
        if aux is not None and not aux.empty:
            auxes.append(aux)
    idx = market.prices.index
    values = pd.concat(frames, axis=1) if frames else pd.DataFrame(index=idx)
    aux = pd.concat(auxes, axis=1) if auxes else pd.DataFrame(index=idx)
    values = values.loc[:, ~values.columns.duplicated()]
    aux = aux.loc[:, ~aux.columns.duplicated()]
    return FeatureSet(values=values.reindex(idx), specs=specs, aux=aux.reindex(idx))


def default_weights(fs: FeatureSet) -> dict[str, float]:
    return {k: fs.specs[k].default_weight for k in fs.values.columns if k in fs.specs}
