"""FastAPI app serving the 52-week-high dashboard and its JSON API."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import (__version__, backlog, breadth, charts, correl, earnings, kr,
               krquarterly, news, quarterly, screener)
from .base import get_screen as base_get_screen
from .flat import get_screen as flat_get_screen
from .turnaround import get_screen as turnaround_get_screen

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

# Regime Lab 의 분석 응답은 Plotly figure JSON 이라 한 번에 ~1MB 나간다. 숫자 배열은
# 잘 압축돼서(≈270KB) 느린 회선에서 체감 차이가 크다. 작은 응답은 건드리지 않는다.
app.add_middleware(GZipMiddleware, minimum_size=1024)

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


# Regime Lab API 가 붙지 못했을 때의 이유(의존성 누락 등). 아래 include_router 에서 채운다.
_REGIME_ERROR: str | None = None


@app.get("/api/health")
def health():
    """살아 있는지 + 어떤 프로그램이 실제로 서빙되는지.

    Regime Lab 은 의존성이 없으면 조용히 빠진 채로 뜬다. 그러면 화면에는 /api/regime/*
    가 404 로만 보여서 '주소가 틀렸나' 로 오해하게 된다 — 이유를 여기서 같이 알려 준다.
    """
    return {
        "status": "ok", "version": __version__, "demo": screener._demo(),
        "regime": {"ok": _REGIME_ERROR is None, "error": _REGIME_ERROR},
    }


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


@app.get("/api/turnaround")
def turnaround_screen():
    """Turnaround Screener: US stocks building a healthy base at the BOTTOM and
    sitting at that base's right edge.

    Fills the gap between the other two screeners — the base screen requires an
    uptrend and cannot look below the 200-day, while the flat screen makes
    flatness mandatory and so misses VCP/cup/irregular bottom bases. Heavy —
    caches server-side; the static build writes data/turnaround.json.
    """
    try:
        return turnaround_get_screen()
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": "턴어라운드 스크리너 실행에 실패했습니다.", "detail": str(e)},
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


@app.get("/api/breadth")
def us_breadth():
    """미장 마켓 브레스: %>이평선·A/D·신고가/신저가 + 리스크 레짐 + 종합점수.

    수집은 tools/breadth_us.py (breadth.yml 워크플로)가 하고 data/breadth_us.json
    에 시계열로 쌓는다. 여기서는 그 스냅샷을 읽어 구간 판정만 붙여 돌려준다 —
    요청마다 외부를 때리지 않으므로 빠르고, 정적 페이지와 값이 같다.
    """
    try:
        return breadth.get_breadth()
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": "마켓 브레스 데이터를 불러오지 못했습니다.", "detail": str(e)},
        )


@app.get("/api/correl")
def correl_snapshot():
    """티커 상관관계 스냅샷 전체(압축 포맷).

    화면은 이 파일 하나를 받아 들고 있다가 티커를 바꿀 때마다 클라이언트에서
    펼친다 — 종목마다 왕복하지 않아 입력이 즉시 반응한다. 정적 배포도 같은
    파일을 읽으므로 코드 경로가 하나다.
    """
    data = correl._load()
    if data is None:
        return JSONResponse(
            status_code=503,
            content={"error": "아직 수집된 상관 데이터가 없습니다. correl 워크플로를 실행하세요."},
        )
    return data


@app.get("/api/correl/{ticker}")
def correl_for(ticker: str):
    """한 티커의 상관 이웃 목록(펼친 형태) — 프로그램적으로 쓸 때."""
    try:
        return correl.get_correl(ticker)
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"{ticker} 상관 데이터를 불러오지 못했습니다.", "detail": str(e)},
        )


@app.get("/api/fundamentals/{ticker}")
def fundamentals_for(ticker: str):
    """한 종목의 분기 실적 표 + 12M forward PER 차트.

    **입력받은 티커만** 그때 받아 온다 — 미리 전 종목을 모으지 않는다. EDGAR
    companyfacts 는 분기에 한 번 바뀌므로 길게 캐시된다(app/secdata.py).
    """
    try:
        return quarterly.build(ticker)
    except LookupError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content={"error": f"{ticker} 실적을 불러오지 못했습니다.", "detail": str(e)},
        )


@app.get("/api/kr/fundamentals/{code}")
def kr_fundamentals_for(code: str):
    """국장 한 종목의 분기 실적 표 + 12M forward PER 차트.

    미장과 **같은 모양**으로 낸다 — 같은 화면이 그린다. 재료만 다르다:
    실적·발표일은 DART, 컨센은 네이버, 주가는 네이버/KRX.
    """
    try:
        return krquarterly.build(code)
    except LookupError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content={"error": f"{code} 실적을 불러오지 못했습니다.", "detail": str(e)},
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
# Market Regime Lab — 정적 UI(app/static/regime)가 쓰는 분석 API.
# 다른 프로그램과 같은 구조: 정적 페이지 + /api/regime/* 백엔드. 라우터는
# StaticFiles catch-all 보다 먼저 등록한다. pandas/plotly 같은 의존성이 없으면
# 대시보드는 그대로 뜨고 이 프로그램만 비활성으로 남는다.
try:
    from .regime_api import router as regime_router

    app.include_router(regime_router)
except Exception as _regime_err:  # pragma: no cover - surfaces via /api/health + 로그
    import logging

    _REGIME_ERROR = str(_regime_err) or _regime_err.__class__.__name__
    logging.getLogger(__name__).warning("regime lab API not mounted: %s", _regime_err)

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def main():
    import uvicorn

    host = os.environ.get("SUH_DH_HOST", "127.0.0.1")
    port = int(os.environ.get("SUH_DH_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
