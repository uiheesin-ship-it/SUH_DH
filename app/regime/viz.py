"""Plotly figures for the Market Regime Lab.

Kept free of Streamlit imports so the figures can be built (and tested) head-
lessly: the UI layer only decides *where* to draw them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

MATCH_COLOR = "#e45756"
PRICE_COLOR = "#1f4e79"
YIELD_COLOR = "#8c6d1f"
SHADE_COLOR = "rgba(228, 87, 86, 0.16)"
BASE_COLOR = "#9aa0a6"


def build_match_table(matches: pd.DataFrame, fs, close: pd.Series, horizons,
                      keys: list[str] | None = None) -> pd.DataFrame:
    """One row per match: score, the features that drove it, forward returns."""
    from .forward import forward_max_drawdown, forward_returns

    if matches is None or matches.empty:
        return pd.DataFrame()
    keys = keys or list(fs.values.columns)
    fwd = forward_returns(close, horizons)
    mdd = forward_max_drawdown(close, horizons)
    out = pd.DataFrame(index=matches.index)
    out["score"] = matches["score"]
    out["distance"] = matches["distance"]
    out["close"] = close.reindex(matches.index)
    for k in keys:
        if k in fs.values.columns:
            out[k] = fs.values[k].reindex(matches.index)
    if "dd_count" in fs.values.columns and "dd_count" not in out.columns:
        out["dd_count"] = fs.values["dd_count"].reindex(matches.index)
    for h in horizons:
        out[f"fwd_{int(h)}"] = fwd[f"fwd_{int(h)}"].reindex(matches.index)
    out[f"mdd_{int(max(horizons))}"] = mdd[f"mdd_{int(max(horizons))}"].reindex(matches.index)
    return out.sort_values("score", ascending=False)


def _hover_text(table: pd.DataFrame, fs, horizons) -> list[str]:
    lines = []
    for date, row in table.iterrows():
        parts = [f"<b>{pd.Timestamp(date).date()}</b>",
                 f"유사도 {row['score']:.1f} (거리 {row['distance']:.2f})"]
        for k in table.columns:
            spec = fs.specs.get(k)
            if spec is None:
                continue
            parts.append(f"{spec.label}: {spec.format(row[k])}")
        fwd_bits = [f"+{int(h)}d {row[f'fwd_{int(h)}']:+.1f}%"
                    for h in horizons if pd.notna(row.get(f"fwd_{int(h)}"))]
        if fwd_bits:
            parts.append("이후 수익률: " + " | ".join(fwd_bits))
        lines.append("<br>".join(parts))
    return lines


def price_chart(market, fs, table: pd.DataFrame, horizons, *, shade_horizon: int = 20,
                log_scale: bool = True, show_sma: tuple[int, ...] = (50, 200),
                anchor=None, exog_label: str = "US 10Y Treasury yield") -> go.Figure:
    """20-year price panel with the matches shaded, yield panel underneath."""
    px = market.prices
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
                        row_heights=[0.72, 0.28],
                        subplot_titles=(f"{market.ticker} (종가)", exog_label))

    fig.add_trace(go.Scatter(x=px.index, y=px["close"], name=market.ticker,
                             line=dict(color=PRICE_COLOR, width=1.2),
                             hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f}<extra></extra>"),
                  row=1, col=1)
    for w in show_sma:
        col = f"sma{int(w)}"
        if col in getattr(fs, "aux", pd.DataFrame()).columns:
            fig.add_trace(go.Scatter(x=fs.aux.index, y=fs.aux[col], name=f"SMA{w}",
                                     line=dict(width=0.9, dash="dot"), opacity=0.75,
                                     hoverinfo="skip"), row=1, col=1)

    if table is not None and not table.empty:
        idx = pd.DatetimeIndex(px.index)
        span = int(shade_horizon)
        for date in table.index:
            try:
                start_pos = int(idx.get_loc(date))
            except KeyError:
                continue
            end = idx[min(len(idx) - 1, start_pos + span)]
            # match 이후 horizon 구간을 통째로 음영 처리 — "그 다음에 무슨 일이
            # 있었나"를 차트에서 바로 보게 한다.
            fig.add_vrect(x0=date, x1=end, fillcolor=SHADE_COLOR, line_width=0,
                          layer="below", row=1, col=1)
        fig.add_trace(go.Scatter(
            x=table.index, y=table["close"], mode="markers", name="Historical match",
            marker=dict(color=MATCH_COLOR, size=8, symbol="diamond",
                        line=dict(color="white", width=1)),
            text=_hover_text(table, fs, horizons), hovertemplate="%{text}<extra></extra>"),
            row=1, col=1)

    if anchor is not None and anchor in px.index:
        fig.add_trace(go.Scatter(
            x=[anchor], y=[px.loc[anchor, "close"]], mode="markers", name="기준일(현재)",
            marker=dict(color="#111111", size=11, symbol="star"),
            hovertemplate="기준일 %{x|%Y-%m-%d}<br>%{y:,.0f}<extra></extra>"), row=1, col=1)

    if market.exog is not None and not market.exog.empty:
        key = market.exog.columns[0]
        fig.add_trace(go.Scatter(x=market.exog.index, y=market.exog[key], name=exog_label,
                                 line=dict(color=YIELD_COLOR, width=1.1),
                                 hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}%<extra></extra>"),
                      row=2, col=1)

    fig.update_yaxes(type="log" if log_scale else "linear", row=1, col=1,
                     title_text="Index (log)" if log_scale else "Index")
    fig.update_yaxes(title_text="%", row=2, col=1)
    fig.update_layout(height=680, hovermode="closest", margin=dict(l=10, r=10, t=50, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                      template="plotly_white")
    fig.update_xaxes(rangeslider_visible=False)
    return fig


def forward_bar_chart(results: dict, ci_level: float = 0.95) -> go.Figure:
    """Matched vs baseline mean forward return, with bootstrap CIs as error bars."""
    horizons = sorted(results)
    matched = [results[h].matched["mean"] for h in horizons]
    base = [results[h].baseline["mean"] for h in horizons]
    m_err_lo = [results[h].matched["mean"] - results[h].matched["ci_mean"][0] for h in horizons]
    m_err_hi = [results[h].matched["ci_mean"][1] - results[h].matched["mean"] for h in horizons]
    b_err_lo = [results[h].baseline["mean"] - results[h].baseline["ci_mean"][0] for h in horizons]
    b_err_hi = [results[h].baseline["ci_mean"][1] - results[h].baseline["mean"] for h in horizons]
    labels = [f"+{h}d" for h in horizons]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=matched, name="Matched", marker_color=MATCH_COLOR,
                         error_y=dict(type="data", symmetric=False, array=m_err_hi,
                                      arrayminus=m_err_lo, color="#5b1f1f", thickness=1.4)))
    fig.add_trace(go.Bar(x=labels, y=base, name="Baseline (전체 기간)", marker_color=BASE_COLOR,
                         error_y=dict(type="data", symmetric=False, array=b_err_hi,
                                      arrayminus=b_err_lo, color="#4d4d4d", thickness=1.4)))
    fig.add_hline(y=0, line_width=1, line_color="#333")
    fig.update_layout(barmode="group", template="plotly_white", height=380,
                      yaxis_title=f"평균 수익률 (%) · 오차막대 = {int(ci_level * 100)}% bootstrap CI",
                      margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def distribution_chart(matched: pd.Series, baseline: pd.Series, horizon: int) -> go.Figure:
    """Matched vs unconditional forward-return distribution for one horizon."""
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=baseline.dropna(), name="Baseline", histnorm="probability density",
                               marker_color=BASE_COLOR, opacity=0.55, nbinsx=60))
    fig.add_trace(go.Histogram(x=matched.dropna(), name="Matched", histnorm="probability density",
                               marker_color=MATCH_COLOR, opacity=0.75, nbinsx=30))
    for series, color, dash in ((baseline, BASE_COLOR, "dot"), (matched, MATCH_COLOR, "solid")):
        if series.notna().any():
            fig.add_vline(x=float(series.dropna().mean()), line_color=color, line_dash=dash,
                          line_width=2)
    fig.update_layout(barmode="overlay", template="plotly_white", height=340,
                      xaxis_title=f"+{horizon}거래일 수익률 (%)", yaxis_title="density",
                      margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def validation_chart(summary: pd.DataFrame) -> go.Figure:
    """In-sample vs out-of-sample realised performance, fold by fold."""
    if summary is None or summary.empty:
        return go.Figure()
    colors = ["#4c78a8" if k == "In-Sample" else "#e45756" for k in summary["구분"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=summary["Fold"], y=summary["초과(%p)"], marker_color=colors,
                         name="기간 평균 대비 초과수익 (%p)",
                         hovertemplate="%{x}<br>초과 %{y:.2f}%p<extra></extra>"))
    fig.add_hline(y=0, line_width=1, line_color="#333")
    fig.update_layout(template="plotly_white", height=340, yaxis_title="%p",
                      margin=dict(l=10, r=10, t=30, b=10), showlegend=False)
    return fig
