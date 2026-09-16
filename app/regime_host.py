"""Host the Market Regime Lab (Streamlit) inside the FastAPI dashboard.

The lab is a Streamlit app, so it cannot be a plain static page like the other
programs. Instead of forking its logic into a second implementation, the
dashboard *runs and proxies* it:

    브라우저 ──► FastAPI /regime/        (대시보드 스타일 랜딩 + iframe)
                       /regime/app/**    ──► 127.0.0.1:8501 (Streamlit, 같은 머신)

Streamlit is started with ``--server.baseUrlPath regime/app`` so every URL it
emits already carries the prefix and a prefix-preserving proxy is enough — one
origin for the browser, so it also works through ngrok or any tunnel the
dashboard is already reachable on.

Nothing here touches the analysis: this module only starts a process and moves
bytes. If Streamlit (or httpx) is not installed the endpoints report that
plainly and the landing page explains how to install them.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse, Response

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app" / "regime" / "streamlit_app.py"
BASE_PATH = "regime/app"
PORT = int(os.environ.get("SUH_DH_REGIME_PORT", "8501"))
HOST = "127.0.0.1"
START_TIMEOUT = float(os.environ.get("SUH_DH_REGIME_START_TIMEOUT", "60"))
# 대시보드가 켜질 때마다 자동으로 띄우지는 않는다 — 사용자가 카드를 눌러야 시작.
AUTOSTART = os.environ.get("SUH_DH_REGIME_AUTOSTART", "0") not in ("", "0", "false", "False")

_proc: subprocess.Popen | None = None
_lock = threading.Lock()

router = APIRouter()


# ------------------------------------------------------------------ capability

def _have(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None


def missing_requirements() -> list[str]:
    return [m for m in ("streamlit", "httpx") if not _have(m)]


def _port_open(port: int = PORT, timeout: float = 0.35) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((HOST, port)) == 0


def is_running() -> bool:
    """A Streamlit answering on the port counts, even if we did not spawn it —
    the user may have started ``./run_regime.sh`` themselves."""
    global _proc
    if _proc is not None and _proc.poll() is not None:
        _proc = None
    return _port_open()


def _spawn() -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(SCRIPT),
        "--server.port", str(PORT),
        "--server.address", HOST,
        "--server.baseUrlPath", BASE_PATH,
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--server.fileWatcherType", "none",
    ]
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(ROOT))
    log.info("starting Market Regime Lab: %s", " ".join(cmd))
    return subprocess.Popen(cmd, cwd=str(ROOT), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def start(timeout: float = START_TIMEOUT) -> dict:
    """Start Streamlit (idempotent) and wait until the port answers."""
    global _proc
    missing = missing_requirements()
    if missing:
        return {"ok": False, "running": False, "missing": missing,
                "error": "필요한 패키지가 없습니다: " + ", ".join(missing)}
    if not SCRIPT.exists():
        return {"ok": False, "running": False, "error": f"{SCRIPT} 를 찾을 수 없습니다."}
    with _lock:
        if is_running():
            return {"ok": True, "running": True, "already": True}
        _proc = _spawn()
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            if _proc.poll() is not None:
                _proc = None
                return {"ok": False, "running": False,
                        "error": "Streamlit 프로세스가 곧바로 종료됐습니다. "
                                 "터미널에서 ./run_regime.sh 로 직접 실행해 오류를 확인하세요."}
            if _port_open():
                return {"ok": True, "running": True, "already": False}
            time.sleep(0.4)
        return {"ok": False, "running": False,
                "error": f"{timeout:.0f}초 안에 준비되지 않았습니다."}


def stop() -> dict:
    """Stop only a process this module started (a user's own run is left alone)."""
    global _proc
    with _lock:
        if _proc is None:
            return {"ok": True, "running": is_running(), "note": "이 대시보드가 띄운 프로세스가 없습니다."}
        _proc.terminate()
        try:
            _proc.wait(timeout=10)
        except Exception:
            _proc.kill()
        _proc = None
    return {"ok": True, "running": False}


def status() -> dict:
    return {
        "available": not missing_requirements(),
        "missing": missing_requirements(),
        "running": is_running(),
        "owned": _proc is not None,
        "port": PORT,
        "path": f"/{BASE_PATH}/",
        "script": str(SCRIPT.relative_to(ROOT)),
    }


# ------------------------------------------------------------------- endpoints

@router.get("/api/regime/status")
def api_status():
    return status()


@router.post("/api/regime/start")
def api_start():
    result = start()
    return JSONResponse(result, status_code=200 if result.get("ok") else 503)


@router.post("/api/regime/stop")
def api_stop():
    return stop()


HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade",
              "proxy-authenticate", "proxy-authorization", "te", "trailer"}


@router.get("/regime/app")
def proxy_root_redirect():
    """/regime/app → /regime/app/ (Streamlit 은 슬래시가 있는 경로에서 동작한다)."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse("/regime/app/")


# 경로에 슬래시를 요구한다 — `/regime/app.js` 같은 랜딩 페이지 자산까지
# 프록시가 가로채면 정적 파일이 404 가 된다.
@router.api_route("/regime/app/{path:path}",
                  methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy_http(path: str, request: Request):
    """Prefix-preserving HTTP proxy to the local Streamlit server."""
    if missing_requirements():
        return JSONResponse({"error": "streamlit/httpx 가 설치되어 있지 않습니다.",
                             "missing": missing_requirements()}, status_code=503)
    if not is_running():
        return JSONResponse({"error": "Market Regime Lab 이 실행 중이 아닙니다.",
                             "hint": "/api/regime/start 로 시작하세요."}, status_code=503)
    import httpx

    url = f"http://{HOST}:{PORT}/{BASE_PATH}/{path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP
               and k.lower() != "host"}
    body = await request.body()
    async with httpx.AsyncClient(timeout=60.0) as client:
        upstream = await client.request(request.method, url, headers=headers,
                                        params=dict(request.query_params), content=body)
    out = {k: v for k, v in upstream.headers.items()
           if k.lower() not in HOP_BY_HOP and k.lower() != "content-encoding"}
    out.pop("content-length", None)
    return Response(content=upstream.content, status_code=upstream.status_code, headers=out)


@router.websocket("/regime/app/_stcore/stream")
async def proxy_ws(ws: WebSocket):
    """Streamlit's message channel. Without this the page loads and then hangs."""
    if missing_requirements() or not is_running():
        await ws.close(code=1013)
        return
    import websockets

    requested = ws.scope.get("subprotocols") or []
    url = f"ws://{HOST}:{PORT}/{BASE_PATH}/_stcore/stream"
    try:
        upstream = await websockets.connect(url, subprotocols=requested or None,
                                            max_size=None, open_timeout=15)
    except Exception as exc:  # pragma: no cover - upstream died between checks
        log.warning("regime ws upstream failed: %s", exc)
        await ws.close(code=1011)
        return

    negotiated = getattr(upstream, "subprotocol", None)
    await ws.accept(subprotocol=negotiated)

    async def client_to_server() -> None:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                await upstream.send(msg["bytes"])
            elif msg.get("text") is not None:
                await upstream.send(msg["text"])

    async def server_to_client() -> None:
        async for message in upstream:
            if isinstance(message, (bytes, bytearray)):
                await ws.send_bytes(bytes(message))
            else:
                await ws.send_text(message)

    tasks = [asyncio.create_task(client_to_server()), asyncio.create_task(server_to_client())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    except Exception as exc:  # pragma: no cover
        log.debug("regime ws closed: %s", exc)
    finally:
        await upstream.close()
        try:
            await ws.close()
        except Exception:
            pass


def attach(app) -> None:
    """Mount the routes (call before the catch-all StaticFiles mount)."""
    app.include_router(router)

    @app.on_event("startup")
    def _maybe_autostart():
        if AUTOSTART:
            start()

    @app.on_event("shutdown")
    def _shutdown():
        if _proc is not None:
            stop()
