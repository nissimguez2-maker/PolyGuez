"""PolyGuez Dashboard — FastAPI backend with WebSocket live updates."""

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

load_dotenv()

app = FastAPI(title="PolyGuez Dashboard")

# Shared runner reference — set by the CLI entrypoint
_runner = None
_DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "")
_FRONTEND_PATH = Path(__file__).parent.parent / "frontend" / "dashboard.html"


def set_runner(runner):
    """Called by the CLI to inject the active PolyGuezRunner."""
    global _runner
    _runner = runner


def _check_auth(secret: str = ""):
    if _DASHBOARD_SECRET and secret != _DASHBOARD_SECRET:
        raise HTTPException(status_code=403, detail="Invalid dashboard secret")


# -- HTML dashboard --------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(secret: str = Query(default="")):
    _check_auth(secret)
    if _FRONTEND_PATH.exists():
        return HTMLResponse(_FRONTEND_PATH.read_text())
    return HTMLResponse("<h1>Dashboard HTML not found</h1>")


# -- REST API --------------------------------------------------------------

@app.get("/api/state")
async def get_state(secret: str = Query(default="")):
    _check_auth(secret)
    if _runner is None:
        return JSONResponse({"error": "Runner not active"}, status_code=503)
    return JSONResponse(json.loads(_runner.get_snapshot().model_dump_json()))


@app.get("/api/config")
async def get_config(secret: str = Query(default="")):
    _check_auth(secret)
    if _runner is None:
        return JSONResponse({"error": "Runner not active"}, status_code=503)
    return JSONResponse(json.loads(_runner.config.model_dump_json()))


@app.post("/api/config")
async def update_config(request: Request, secret: str = Query(default="")):
    _check_auth(secret)
    if _runner is None:
        return JSONResponse({"error": "Runner not active"}, status_code=503)
    body = await request.json()
    await _runner.update_config(body)
    return JSONResponse({"status": "ok", "config": json.loads(_runner.config.model_dump_json())})


@app.post("/api/kill")
async def kill_switch(secret: str = Query(default="")):
    _check_auth(secret)
    if _runner is None:
        return JSONResponse({"error": "Runner not active"}, status_code=503)
    await _runner.kill()
    return JSONResponse({"status": "killed"})


@app.get("/api/trades")
async def get_trades(secret: str = Query(default="")):
    _check_auth(secret)
    if _runner is None:
        return JSONResponse({"error": "Runner not active"}, status_code=503)
    trades = [json.loads(t.model_dump_json()) for t in _runner._rolling_stats.trades]
    return JSONResponse(trades)


@app.post("/api/mode")
async def set_mode(request: Request, secret: str = Query(default="")):
    _check_auth(secret)
    if _runner is None:
        return JSONResponse({"error": "Runner not active"}, status_code=503)
    body = await request.json()
    new_mode = body.get("mode", "")
    confirm = body.get("confirm", "")

    if new_mode == "live":
        if _runner.is_killed:
            return JSONResponse(
                {"error": "Cannot switch to live while kill switch is active. Restart the bot."},
                status_code=400,
            )
        if confirm != "CONFIRM":
            return JSONResponse(
                {"error": "Type CONFIRM to enable live trading"},
                status_code=400,
            )

    if new_mode not in ("dry-run", "paper", "live"):
        return JSONResponse({"error": f"Invalid mode: {new_mode}"}, status_code=400)

    await _runner.update_config({"mode": new_mode})
    return JSONResponse({"status": "ok", "mode": new_mode})


# -- WebSocket for live updates -------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, secret: str = Query(default="")):
    if _DASHBOARD_SECRET and secret != _DASHBOARD_SECRET:
        await websocket.close(code=4003)
        return

    await websocket.accept()
    try:
        while True:
            if _runner:
                snapshot = _runner.get_snapshot()
                await websocket.send_text(snapshot.model_dump_json())
            else:
                await websocket.send_text(json.dumps({"error": "Runner not active"}))
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
