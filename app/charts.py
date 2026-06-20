"""Price history (for charts) and the "why did it pop" reason, via Yahoo.

Charts use yfinance historical OHLCV; the frontend renders candles + volume +
moving averages from this payload. The reason combines recent news headlines
with a check for a just-reported earnings date.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from . import cache, demo_data
from .indicators import attach_moving_averages

CHART_TTL = float(os.environ.get("SUH_DH_CHART_TTL", "600"))
REASON_TTL = float(os.environ.get("SUH_DH_REASON_TTL", "1800"))

VALID_RANGES = {"max", "6mo"}


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def _fetch_chart_live(ticker: str, rng: str) -> dict:
    import yfinance as yf

    period = "max" if rng == "max" else "6mo"
    hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    if hist is None or hist.empty:
        return {"ticker": ticker, "range": rng, "dates": [], "open": [], "high": [],
                "low": [], "close": [], "volume": []}
    hist = hist.dropna(subset=["Close"])
    return {
        "ticker": ticker,
        "range": rng,
        "dates": [d.strftime("%Y-%m-%d") for d in hist.index],
        "open": [round(float(x), 4) for x in hist["Open"]],
        "high": [round(float(x), 4) for x in hist["High"]],
        "low": [round(float(x), 4) for x in hist["Low"]],
        "close": [round(float(x), 4) for x in hist["Close"]],
        "volume": [int(x) for x in hist["Volume"].fillna(0)],
    }


def get_chart(ticker: str, rng: str = "max") -> dict:
    ticker = ticker.upper().strip()
    if rng not in VALID_RANGES:
        rng = "max"
    key = f"chart:{ticker}:{rng}"

    def producer():
        data = demo_data.demo_chart(ticker, rng) if _demo() else _fetch_chart_live(ticker, rng)
        return attach_moving_averages(data)

    return cache.get_or_set(key, CHART_TTL, producer)


# --------------------------------------------------------------------------- #
# Reason (news + earnings)
# --------------------------------------------------------------------------- #
def _news_items(raw_news: list) -> list[dict]:
    """Normalize yfinance news across its old and new (content-wrapped) schemas."""
    items: list[dict] = []
    for n in raw_news or []:
        content = n.get("content", n)  # new schema nests under "content"
        title = content.get("title") or n.get("title")
        if not title:
            continue
        # publisher
        provider = content.get("provider") or {}
        publisher = (
            provider.get("displayName")
            if isinstance(provider, dict)
            else None
        ) or n.get("publisher")
        # link
        link = None
        for key in ("canonicalUrl", "clickThroughUrl"):
            v = content.get(key)
            if isinstance(v, dict) and v.get("url"):
                link = v["url"]
                break
        link = link or n.get("link") or content.get("link")
        # published time
        published = None
        ts = n.get("providerPublishTime")
        if ts:
            published = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        elif content.get("pubDate"):
            published = str(content["pubDate"])[:16].replace("T", " ")
        items.append(
            {"title": title, "publisher": publisher, "link": link, "published": published}
        )
        if len(items) >= 5:
            break
    return items


def _earnings_recent(tk) -> tuple[bool, str | None]:
    """True if the company reported earnings within the last ~5 days."""
    try:
        df = tk.get_earnings_dates(limit=12)
    except Exception:
        return False, None
    if df is None or df.empty:
        return False, None
    now = datetime.now(timezone.utc)
    recent = None
    for idx in df.index:
        try:
            dt = idx.to_pydatetime()
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = (now - dt).total_seconds()
        if 0 <= delta <= 5 * 86400:  # reported in the last 5 days
            if recent is None or dt > recent:
                recent = dt
    if recent:
        return True, recent.strftime("%Y-%m-%d")
    return False, None


def _fetch_reason_live(ticker: str) -> dict:
    import yfinance as yf

    tk = yf.Ticker(ticker)
    try:
        raw = tk.news
    except Exception:
        raw = []
    earnings_recent, earnings_date = _earnings_recent(tk)
    return {
        "ticker": ticker,
        "news": _news_items(raw),
        "earnings_recent": earnings_recent,
        "earnings_date": earnings_date,
    }


def get_reason(ticker: str) -> dict:
    ticker = ticker.upper().strip()

    def producer():
        return demo_data.demo_reason(ticker) if _demo() else _fetch_reason_live(ticker)

    return cache.get_or_set(f"reason:{ticker}", REASON_TTL, producer)
