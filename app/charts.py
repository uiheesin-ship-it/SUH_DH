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

# Charts are viewed "live", so keep this short — just enough to absorb rapid
# re-clicks and range toggles without re-hitting Yahoo on every interaction.
CHART_TTL = float(os.environ.get("SUH_DH_CHART_TTL", "30"))
REASON_TTL = float(os.environ.get("SUH_DH_REASON_TTL", "1800"))

VALID_RANGES = {"max", "6mo"}


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def _empty_chart(ticker: str, rng: str) -> dict:
    return {"ticker": ticker, "range": rng, "dates": [], "open": [], "high": [],
            "low": [], "close": [], "volume": []}


def _fetch_chart_yahoo(ticker: str, rng: str) -> dict:
    import time as _time

    import yfinance as yf

    period = "max" if rng == "max" else "6mo"
    # Yahoo intermittently throttles/blocks (esp. from cloud IPs). Retry a few
    # times with a short backoff before giving up to the fallback source.
    hist = None
    for attempt in range(3):
        try:
            hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
        except Exception:
            hist = None
        if hist is not None and not hist.empty:
            break
        _time.sleep(0.8 * (attempt + 1))
    if hist is None or hist.empty:
        return _empty_chart(ticker, rng)
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


def _fetch_chart_stooq(ticker: str, rng: str) -> dict:
    """Key-free OHLCV fallback (Stooq) for when Yahoo blocks the cloud IP.

    Stooq serves daily history as CSV with no API key and works from datacenter
    IPs, so the page is never blank just because Yahoo throttled this server.
    """
    import csv
    import io
    import urllib.request

    # Stooq uses lowercase symbols with a market suffix; dotted classes use '-'.
    sym = ticker.lower().replace(".", "-")
    url = f"https://stooq.com/q/d/l/?s={sym}.us&i=d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception:
        return _empty_chart(ticker, rng)

    dates, o, h, l, c, v = [], [], [], [], [], []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            close = float(row["Close"])
        except (KeyError, ValueError, TypeError):
            continue  # header note / "N/D" rows
        dates.append(row["Date"])
        o.append(round(float(row.get("Open") or close), 4))
        h.append(round(float(row.get("High") or close), 4))
        l.append(round(float(row.get("Low") or close), 4))
        c.append(round(close, 4))
        try:
            v.append(int(float(row.get("Volume") or 0)))
        except (ValueError, TypeError):
            v.append(0)
    if not c:
        return _empty_chart(ticker, rng)
    # Stooq returns the full daily history ascending; trim for the short range.
    if rng != "max" and len(dates) > 130:
        dates, o, h, l, c, v = (x[-130:] for x in (dates, o, h, l, c, v))
    return {"ticker": ticker, "range": rng, "dates": dates,
            "open": o, "high": h, "low": l, "close": c, "volume": v}


def _fetch_chart_live(ticker: str, rng: str) -> dict:
    data = _fetch_chart_yahoo(ticker, rng)
    if data["close"]:
        return data
    # Yahoo returned nothing (likely a transient cloud-IP block) — fall back to a
    # key-free source so the chart/drift table is never blank.
    return _fetch_chart_stooq(ticker, rng)


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


def _business_summary(tk) -> str | None:
    try:
        info = tk.get_info()
    except Exception:
        try:
            info = tk.info
        except Exception:
            return None
    if not isinstance(info, dict):
        return None
    return info.get("longBusinessSummary")


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

    from . import translate

    tk = yf.Ticker(ticker)
    try:
        raw = tk.news
    except Exception:
        raw = []
    news = _news_items(raw)
    # Translate the headline we actually display (first item) to Korean.
    if news:
        news[0]["title_ko"] = translate.to_korean(news[0]["title"])
    earnings_recent, earnings_date = _earnings_recent(tk)
    return {
        "ticker": ticker,
        "description": translate.summary_korean(_business_summary(tk)),
        "news": news,
        "earnings_recent": earnings_recent,
        "earnings_date": earnings_date,
    }


def get_reason(ticker: str) -> dict:
    ticker = ticker.upper().strip()

    def producer():
        return demo_data.demo_reason(ticker) if _demo() else _fetch_reason_live(ticker)

    return cache.get_or_set(f"reason:{ticker}", REASON_TTL, producer)
