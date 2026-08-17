"""FastAPI app serving the 52-week-high dashboard and its JSON API."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, backlog, charts, earnings, kr, news, qtable, screener
from .base import get_screen as base_get_screen
from .flat import get_screen as flat_get_screen

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="SUH_DH - US 52-Week High Dashboard", version=__version__)

# Allow the static GitHub Pages site (a different origin) to call this API as a
# backend for any ticker. Read-only public data, so default to any origin;
# restrict with SUH_DH_CORS_ORIGINS="https://a.com,https://b.com" if desired.
_cors = os.environ.get("SUH_DH_CORS_ORIGINS", "*").strip()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _cors == "*" else [o.strip() for o in _cors.split(",") if o.strip()],
    # eai adds POST endpoints (seed/upload/run-batch) for the Next.js frontend.
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Earnings-AI subsystem (conference-call analysis → investment themes). Mounted
# under /api/eai/* as a separate bounded context; kept optional so a missing
# async/DB dependency never blocks the legacy price dashboards.
try:
    from .eai.router import include_private, init_eai
    from .eai.router import router as eai_router

    app.include_router(eai_router)
    include_private(app)  # login-gated /api/eai/private/* (transcripts/search/download)

    @app.on_event("startup")
    async def _eai_startup():  # create tables (MVP) + recover interrupted jobs
        if os.environ.get("EAI_AUTO_INIT", "1") == "1":
            await init_eai()
except Exception as _eai_err:  # pragma: no cover - surfaces as a log line only
    import logging

    logging.getLogger(__name__).warning("eai subsystem not mounted: %s", _eai_err)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__, "demo": screener._demo()}


@app.get("/api/highs")
def highs():
    """Grouped new-high stocks: sector -> industry -> stocks (by market cap)."""
    try:
        data = screener.get_dashboard()
    except Exception as e:  # surface upstream/network failures cleanly to the UI
        return JSONResponse(
            status_code=502,
            content={"error": "Failed to fetch new highs from Finviz.", "detail": str(e)},
        )
    return data


@app.get("/api/reason/{ticker}")
def reason(ticker: str):
    try:
        return charts.get_reason(ticker)
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Failed to fetch reason for {ticker}.", "detail": str(e)},
        )


@app.get("/api/chart/{ticker}")
def chart(ticker: str, range: str = "max"):
    if range not in charts.VALID_RANGES:
        raise HTTPException(status_code=400, detail=f"range must be one of {charts.VALID_RANGES}")
    try:
        return charts.get_chart(ticker, range)
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Failed to fetch chart for {ticker}.", "detail": str(e)},
        )


@app.get("/api/earnings/{ticker}")
def earnings_history(ticker: str):
    """Recent earnings dates + EPS consensus beat/miss/inline tags."""
    try:
        return earnings.get_earnings(ticker)
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Failed to fetch earnings for {ticker}.", "detail": str(e)},
        )


@app.get("/api/drift/{ticker}")
def earnings_drift(ticker: str):
    """Earnings table + post-earnings price drift (직전1일 / D+1·7·30·60 + 평균)."""
    try:
        return earnings.get_drift(ticker)
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Failed to compute drift for {ticker}.", "detail": str(e)},
        )


@app.get("/api/guidance/tickers")
def registered_guidance_tickers():
    """Tickers that have curated guidance-vs-consensus data (for the side panel)."""
    return {"tickers": earnings.guidance_tickers(),
            "groups": earnings.guidance_groups()}


# Declared before /api/qtable/{ticker} so "tickers" isn't read as a symbol.
@app.get("/api/qtable/tickers")
def quarter_table_tickers():
    """가이던스 큐레이션이 입력된 종목(사이드 패널용)."""
    return {"tickers": qtable.curated_tickers()}


@app.get("/api/qtable/{ticker}")
def quarter_table(ticker: str, past: int = qtable.PAST_QUARTERS,
                  ahead: int = qtable.AHEAD_QUARTERS):
    """분기 실적표: 과거 가이던스·컨센서스·실적·향후 가이던스(연간/QoQ)."""
    past = max(1, min(past, 16))
    ahead = max(0, min(ahead, 12))
    try:
        return qtable.get_table(ticker, past=past, ahead=ahead)
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"{ticker} 분기 실적표를 만들지 못했습니다.", "detail": str(e)},
        )


@app.get("/api/kr/drift/{ticker}")
def kr_drift(ticker: str):
    """Korean post-earnings price drift (상승률 only; curated earnings dates)."""
    try:
        return kr.get_kr_drift(ticker)
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Failed to compute KR drift for {ticker}.", "detail": str(e)},
        )


@app.get("/api/kr/tickers")
def kr_registered_tickers():
    """Curated Korean tickers grouped by sector (for the picker)."""
    return {"tickers": kr.kr_tickers(), "groups": kr.kr_groups()}


@app.get("/api/krbase")
def kr_base_screen():
    """Korean (KOSPI+KOSDAQ) healthy-base screener — 국장 base watchlist."""
    try:
        from .base import get_screen_kr
        return get_screen_kr()
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": "국장 베이스 스크리너 실행에 실패했습니다.", "detail": str(e)},
        )


@app.get("/api/krchart/{code}")
def kr_chart(code: str, market: str | None = None):
    """Same-day Korean OHLCV chart (FDR/Naver, Yahoo fallback) for KR pages."""
    try:
        from . import krdata
        return krdata.kr_chart(code, market)
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"{code} 차트를 불러오지 못했습니다.", "detail": str(e)},
        )


@app.get("/api/krhighs")
def kr_highs():
    """Korean (KOSPI+KOSDAQ) 52-week-high stocks, grouped by sector."""
    try:
        from . import krhighs
        return krhighs.get_dashboard()
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": "국장 신고가를 불러오지 못했습니다.", "detail": str(e)},
        )


@app.get("/api/krhighs60")
def kr_highs60():
    """Korean (KOSPI+KOSDAQ) 60-trading-day-high stocks, grouped by sector."""
    try:
        from . import krhighs60
        return krhighs60.get_dashboard()
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": "국장 60일 신고가를 불러오지 못했습니다.", "detail": str(e)},
        )


@app.get("/api/base")
def base_screen():
    """Healthy-base screener: scored watchlist of stocks forming a base.

    Heavy (fetches OHLCV for the whole candidate universe), so the result is
    cached server-side. The static GitHub Pages build pre-computes the same
    payload into data/base.json.
    """
    try:
        return base_get_screen()
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": "베이스 스크리너 실행에 실패했습니다.", "detail": str(e)},
        )


@app.get("/api/flat")
def flat_screen():
    """Flat Base Screener: US stocks currently in a flat, horizontal, tight base.

    Measures only how flat the current base is (no volume/ATR/VCP/MA/RS/sector in
    the score). Heavy — caches server-side; the static build writes data/flat.json.
    """
    try:
        return flat_get_screen()
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": "평평 스크리너 실행에 실패했습니다.", "detail": str(e)},
        )


@app.get("/api/backlog")
def kr_backlog():
    """Korean quarterly order backlog (수주잔고) from DART periodic reports.

    Serves the committed data/kr_backlog.json view (built by
    tools/kr_dart_backlog.py). Static GitHub Pages reads the same JSON directly.
    """
    try:
        return backlog.get_dashboard()
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": "수주잔고 데이터를 불러오지 못했습니다.", "detail": str(e)},
        )


@app.get("/api/backlog/{stock_code}")
def kr_backlog_company(stock_code: str):
    """Live single-company backlog refresh from DART (needs DART_API_KEY)."""
    try:
        rec = backlog.refresh_company(stock_code)
        if not rec:
            raise HTTPException(status_code=404, detail="수주잔고 공시를 찾지 못했습니다.")
        return backlog._company_view(rec)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": "수주잔고 조회에 실패했습니다.", "detail": str(e)},
        )


@app.get("/api/news")
def global_news():
    """Curated global financial-news digest (10~20 items, Korean summaries)."""
    try:
        return news.get_news()
    except Exception as e:  # surface upstream/network failures cleanly to the UI
        return JSONResponse(
            status_code=502,
            content={"error": "Failed to build the global news digest.", "detail": str(e)},
        )


# Static dashboard (index.html at "/"). Mounted last so /api/* wins.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def main():
    import uvicorn

    host = os.environ.get("SUH_DH_HOST", "127.0.0.1")
    port = int(os.environ.get("SUH_DH_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
