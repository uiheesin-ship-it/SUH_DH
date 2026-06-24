"""FastAPI app serving the 52-week-high dashboard and its JSON API."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, charts, earnings, news, screener

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="SUH_DH - US 52-Week High Dashboard", version=__version__)

# Allow the static GitHub Pages site (a different origin) to call this API as a
# backend for any ticker. Read-only public data, so default to any origin;
# restrict with SUH_DH_CORS_ORIGINS="https://a.com,https://b.com" if desired.
_cors = os.environ.get("SUH_DH_CORS_ORIGINS", "*").strip()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _cors == "*" else [o.strip() for o in _cors.split(",") if o.strip()],
    allow_methods=["GET"],
    allow_headers=["*"],
)


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
