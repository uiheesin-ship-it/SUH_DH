"""FastAPI app serving the 52-week-high dashboard and its JSON API."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, charts, screener

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="SUH_DH - US 52-Week High Dashboard", version=__version__)


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


# Static dashboard (index.html at "/"). Mounted last so /api/* wins.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def main():
    import uvicorn

    host = os.environ.get("SUH_DH_HOST", "127.0.0.1")
    port = int(os.environ.get("SUH_DH_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
