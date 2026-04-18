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


# -- Supabase diagnostics (no auth — read-only internal state) ------------

@app.get("/api/supabase-status")
async def supabase_status():
    """Expose Supabase + Chainlink state for remote diagnosis without Railway log access."""
    import time as _time
    from agents.utils import supabase_logger as _sb
    client_ok = _sb._supabase_client is not None
    failed_at = _sb._supabase_init_failed_at
    failures = _sb._consecutive_write_failures
    drops = _sb._log_drops
    age_since_fail = round(_time.time() - failed_at, 1) if failed_at else None
    url_set = bool(os.environ.get("SUPABASE_URL"))
    key_set = bool(os.environ.get("SUPABASE_SERVICE_KEY"))

    # Chainlink buffer state — the P2B gate blocks every cycle if this is empty
    cl_buf_size = 0
    cl_latest_age = None
    cl_oldest_age = None
    p2b_skips = None
    p2b_consecutive = None
    if _runner is not None:
        feed = getattr(_runner, "_btc_feed", None)
        if feed is not None:
            buf = getattr(feed, "_chainlink_buffer", None)
            if buf:
                cl_buf_size = len(buf)
                now_m = _time.time()
                cl_latest_age = round(now_m - buf[-1][0], 1)
                cl_oldest_age = round(now_m - buf[0][0], 1)
        p2b_skips = getattr(getattr(_runner, "_rolling_stats", None), "p2b_skips", None)
        p2b_consecutive = getattr(_runner, "_p2b_consecutive_failures", None)

    gamma_ok = getattr(_runner, "_gamma_ok", None) if _runner else None
    discovery_misses = getattr(_runner, "_discovery_misses", None) if _runner else None

    return JSONResponse({
        "client_initialised": client_ok,
        "init_attempted": _sb._supabase_init_attempted,
        "init_failed_at_age_seconds": age_since_fail,
        "consecutive_write_failures": failures,
        "log_queue_drops": drops,
        "supabase_url_set": url_set,
        "supabase_key_set": key_set,
        "chainlink_buffer_size": cl_buf_size,
        "chainlink_latest_sample_age_seconds": cl_latest_age,
        "chainlink_oldest_sample_age_seconds": cl_oldest_age,
        "p2b_skips_total": p2b_skips,
        "p2b_consecutive_failures": p2b_consecutive,
        "gamma_ok": gamma_ok,
        "discovery_misses": discovery_misses,
    })


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


def _evaluate_live_gates() -> list[dict]:
    """MODEL-01: compute the state of each live-mode gate.

    Returns a list of {name, passed, required, value, note} dicts. The
    programmatic live-mode gate in /api/mode refuses to flip unless every
    `passed=True`. /api/live-readiness exposes this list as JSON so the
    dashboard can render a readiness scoreboard.

    Gates:
      1. CONFIRM string        — checked inline in /api/mode (not here)
      2. kill_switch_off       — bot is not killed
      3. trade_count >= 100    — V5 session has accumulated enough trades
      4. brier <= 0.25         — model calibration is at least random-or-better
      5. min_net_edge > 0.02   — operator has enabled the net-edge gate
    """
    gates: list[dict] = []

    killed = bool(getattr(_runner, "is_killed", False)) if _runner else True
    gates.append({
        "name": "kill_switch_off",
        "passed": not killed,
        "required": "kill-switch must be off",
        "value": {"killed": killed},
    })

    cfg = getattr(_runner, "config", None) if _runner else None
    session_tag = getattr(cfg, "session_tag", "V5") if cfg else "V5"

    trade_count = None
    brier_value = None
    brier_n = None
    try:
        # Lazy-import the service-role client used by the bot's own logger
        # so we reuse the Supabase connection and env vars.
        from agents.utils.supabase_logger import _client as _supa_client
        supa = _supa_client()
        if supa is not None:
            count_resp = (
                supa.table("trade_log")
                .select("id", count="exact")
                .eq("session_tag", session_tag)
                .execute()
            )
            trade_count = int(count_resp.count or 0)
            brier_resp = supa.rpc("get_session_brier", {"p_session_tag": session_tag}).execute()
            if getattr(brier_resp, "data", None):
                row = brier_resp.data[0]
                brier_value = float(row.get("brier")) if row.get("brier") is not None else None
                brier_n = int(row.get("n_trades") or 0)
    except Exception as exc:
        gates.append({
            "name": "supabase_reachable",
            "passed": False,
            "required": "Supabase queries succeed",
            "value": {"error": str(exc)},
        })

    gates.append({
        "name": "trade_count_ge_100",
        "passed": bool(trade_count is not None and trade_count >= 100),
        "required": f"session {session_tag} trade_count >= 100",
        "value": {"trade_count": trade_count, "session_tag": session_tag},
    })
    gates.append({
        "name": "brier_le_0_25",
        "passed": bool(brier_value is not None and brier_value <= 0.25),
        "required": "Brier score <= 0.25 (model at least as good as random)",
        "value": {"brier": brier_value, "n_trades": brier_n},
    })

    min_net_edge = float(getattr(cfg, "min_net_edge", 0.0) or 0.0) if cfg else 0.0
    gates.append({
        "name": "min_net_edge_gt_0_02",
        "passed": min_net_edge > 0.02,
        "required": "PolyGuezConfig.min_net_edge > 0.02 (net-edge gate enabled)",
        "value": {"min_net_edge": min_net_edge},
    })
    return gates


@app.get("/api/live-readiness")
async def live_readiness(secret: str = Query(default="")):
    """Scoreboard of every live-mode gate. All must pass before /api/mode
    will accept `mode=live`. Useful for the dashboard to surface WHY a live
    flip is not yet allowed."""
    _check_auth(secret)
    if _runner is None:
        return JSONResponse({"error": "Runner not active"}, status_code=503)
    gates = _evaluate_live_gates()
    return JSONResponse({
        "gates": gates,
        "all_pass": all(g.get("passed") for g in gates),
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
        # Gate 1 (CONFIRM) is checked inline so we don't run expensive
        # Supabase queries when the operator didn't even type the string.
        if confirm != "CONFIRM":
            return JSONResponse(
                {"error": "Type CONFIRM to enable live trading"},
                status_code=400,
            )
        # Gates 2..5 — MODEL-01 programmatic live-mode gate. Every gate
        # must pass; the full scoreboard is surfaced via /api/live-readiness.
        gates = _evaluate_live_gates()
        failed = [g for g in gates if not g.get("passed")]
        if failed:
            return JSONResponse({
                "error": "Live-mode gate failed — one or more prerequisites not met.",
                "failed": failed,
                "all_gates": gates,
            }, status_code=400)

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
