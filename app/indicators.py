"""Technical indicators computed server-side so the frontend just plots."""

from __future__ import annotations

MA_WINDOWS = (5, 20, 50, 120)


def moving_average(values: list[float], window: int) -> list[float | None]:
    """Simple moving average, left-padded with None until the window fills.

    Returns a list the same length as ``values`` so it lines up with the date
    axis on the chart. Entries before ``window`` samples are None (gaps in the
    line) rather than a partial average, which is the convention traders expect.
    """
    out: list[float | None] = [None] * len(values)
    if window <= 0:
        return out
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            out[i] = round(running / window, 4)
    return out


def attach_moving_averages(chart: dict) -> dict:
    """Add ma5/ma20/ma50/ma120 series (on close) to a chart payload."""
    closes = chart.get("close") or []
    for w in MA_WINDOWS:
        chart[f"ma{w}"] = moving_average(closes, w)
    return chart
