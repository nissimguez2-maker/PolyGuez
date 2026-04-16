"""PolyGuez Dashboard — FastAPI backend with WebSocket live updates."""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv()

app = FastAPI(title="PolyGuez Dashboard")

# Shared runner reference — set by the CLI entrypoint
_runner = None
_FRONTEND_PATH = Path(__file__).parent.parent / "frontend" / "dashboard.html"
_STATIC_PATH = Path(__file__).parent.parent / "frontend"


def set_runner(runner):
    """Called by the CLI to inject the active PolyGuezRunner."""
    global _runner
    _runner = runner


def _get_dashboard_secret():
    """Get dashboard secret from runner (auto-generated or env-set), or from env as fallback."""
    if _runner and hasattr(_runner, 'config') and _runner.config.dashboard_secret:
        return _runner.config.dashboard_secret
    return os.getenv("DASHBOARD_SECRET", "")


def _check_auth(secret: str = ""):
    dashboard_secret = _get_dashboard_secret()
    if dashboard_secret and secret != dashboard_secret:
        raise HTTPException(status_code=403, detail="Invalid dashboard secret")


# -- Static file auth middleware -------------------------------------------
class StaticAuthMiddleware(BaseHTTPMiddleware):
    """Protect /static/ routes with the same dashboard secret."""
    async def dispatch(self, request, call_next):
        if request.url.path.startswith('/static/'):
            secret = _get_dashboard_secret()
            if secret:
                qs_ok = request.query_params.get('secret') == secret
                ref_ok = secret in (request.headers.get('referer') or '')
                cookie_ok = request.cookies.get('dboard_secret') == secret
                if not (qs_ok or ref_ok or cookie_ok):
                    from fastapi.responses import Response as _R
                    return _R('Forbidden', status_code=403)
        return await call_next(request)

app.add_middleware(StaticAuthMiddleware)
app.mount('/static', StaticFiles(directory=str(_STATIC_PATH)), name='static')


# -- Health check (Railway / load balancer) --------------------------------

@app.get("/health")
async def health():
    """Real health signal for Railway / load balancers.

    Returns 200 only when all of these hold:
      - runner is attached
      - runner is not in killed state
      - BTC feed is connected (the bot has no signal without it)
      - main loop ticked within HEALTH_MAX_STALE_SECONDS (default 120s)

    Returns 503 otherwise so Railway restarts the instance instead of sending
    traffic to a dead event loop whose FastAPI thread is still alive.
    """
    max_stale = float(os.environ.get("HEALTH_MAX_STALE_SECONDS", "120"))
    now = time.time()
    if _runner is None:
        return JSONResponse({"status": "starting", "runner_active": False}, status_code=503)
    killed = bool(getattr(_runner, "is_killed", False))
    btc_ok = bool(getattr(getattr(_runner, "_btc_feed", None), "is_connected", False))
    last_tick = float(getattr(_runner, "_loop_heartbeat_ts", 0.0) or 0.0)
    loop_age = (now - last_tick) if last_tick else float("inf")
    loop_ok = loop_age <= max_stale
    healthy = (not killed) and btc_ok and loop_ok
    payload = {
        "status": "ok" if healthy else "unhealthy",
        "runner_active": True,
        "killed": killed,
        "btc_feed_connected": btc_ok,
        "loop_age_seconds": round(loop_age, 1) if last_tick else None,
        "loop_stale_threshold_seconds": max_stale,
    }
    return JSONResponse(payload, status_code=200 if healthy else 503)


# -- HTML dashboard --------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(secret: str = Query(default="")):
    _check_auth(secret)
    if _FRONTEND_PATH.exists():
        return HTMLResponse(
            _FRONTEND_PATH.read_text(),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )
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


@app.get("/api/stats")
async def get_stats(secret: str = Query(default="")):
    """Subset of the rolling_stats singleton safe to return to an authed dashboard.

    Replaces the frontend's direct Supabase read of the `rolling_stats` row,
    which exposed full strategy state (reset_token, win_rate, trade_count,
    etc.) to anyone who extracted the anon JWT from the dashboard JS.
    """
    _check_auth(secret)
    if _runner is None:
        return JSONResponse({"error": "Runner not active"}, status_code=503)
    rs = _runner._rolling_stats
    return JSONResponse({
        "simulated_balance": rs.simulated_balance,
        "updated_at": getattr(rs, "updated_at", None),
        "total_trades": len(rs.trades),
    })


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
    dashboard_secret = _get_dashboard_secret()
    if dashboard_secret and secret != dashboard_secret:
        await websocket.close(code=4003)
        return

    await websocket.accept()
    try:
        while True:
            if _runner:
                try:
                    snapshot = _runner.get_snapshot()
                    await websocket.send_text(snapshot.model_dump_json())
                except Exception:
                    break
            else:
                await websocket.send_text(json.dumps({"error": "Runner not active"}))
            await asyncio.sleep(0.1)
    except (WebSocketDisconnect, Exception):
        pass
