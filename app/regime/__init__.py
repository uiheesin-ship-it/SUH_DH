"""Market Regime Lab — 현재 시장 상태를 정량화하고, 과거의 유사 국면과 그 이후
수익률 분포를 찾아보는 분석 패키지.

Layers (each independently testable, each swappable):

    data/        수집 · 거래일 정렬 · 캐시        (yfinance / stooq / 오프라인 합성)
    features/    feature engineering              (trend, momentum, volatility,
                                                   distribution day, macro)
    similarity   정규화 · 거리 · de-clustering
    matching     strict 조건 매칭
    forward      forward return 통계 · bootstrap
    validation   walk-forward / out-of-sample
    viz          Plotly figure
    ui + streamlit_app   화면

The default market is ^IXIC, but nothing below ``ui`` knows that — any Yahoo
symbol works, and extra exogenous series (VIX, credit spreads, Fed funds) are a
config entry plus, at most, one feature builder.
"""

from .config import Params, load_config  # noqa: F401
