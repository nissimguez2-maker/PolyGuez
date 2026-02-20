from __future__ import annotations
from fastapi import FastAPI, Request, HTTPException
from typing import Any
import asyncio
import logging
import time
import httpx

from src.config.settings import get_settings
from src.market_data.telemetry import telemetry
from src.market_discovery.btc_updown import (
    NoCurrentMarket,
    derive_btc_updown_slug_from_signal_id,
    find_current_btc_updown_market,
)

logger = logging.getLogger(__name__)


def _resolve_adapter(request: Request):
    """Resolve canonical adapter (app.state first, then webhook helper/global fallback)."""
    adapter = getattr(request.app.state, "market_data_adapter", None)
    if adapter is not None:
        return adapter
    try:
        import webhook_server_fastapi as ws  # type: ignore

        if getattr(ws, "_get_market_data_adapter", None):
            adapter = ws._get_market_data_adapter(request.app)
        if adapter is None:
            adapter = getattr(ws, "_market_data_adapter", None)
        if adapter is not None:
            request.app.state.market_data_adapter = adapter
        return adapter
    except Exception:
        return None


def register(app: FastAPI) -> None:
    @app.get("/market-data/metrics")
    async def market_data_metrics() -> Any:
        return telemetry.get_snapshot()

    @app.get("/market-data/health")
    async def market_data_health() -> Any:
        metrics = telemetry.get_snapshot()
        last_msg_age = metrics.get("last_msg_age_s")
        eventbus_dropped = metrics.get("counters", {}).get("market_data_eventbus_dropped_total", 0)

        # Determine adapter presence primarily from telemetry gauge to avoid
        # brittle cross-module introspection in some runtime setups.
        notes = []
        gauges = metrics.get("gauges", {})
        ws_connected = bool(gauges.get("market_data_ws_connected", 0))
        adapter_present = ws_connected
        active_subs = 0
        stale_tokens = 0
        if not adapter_present:
            notes.append("adapter_not_initialized")
            # If adapter import previously failed, surface that error for diagnostics
            try:
                import webhook_server_fastapi as ws  # type: ignore
                err = getattr(ws, "_adapter_import_error", None)
                if err:
                    notes.append(f"adapter_import_error:{err}")
            except Exception:
                pass

        # Prefer adapter internal state for active_subscriptions to avoid divergence
        try:
            adapter = getattr(app.state, "market_data_adapter", None)
            if adapter is None:
                import webhook_server_fastapi as ws  # type: ignore

                if getattr(ws, "_get_market_data_adapter", None):
                    adapter = ws._get_market_data_adapter(app)
                if adapter is None:
                    adapter = getattr(ws, "_market_data_adapter", None)
            if adapter is not None:
                subs = set(getattr(adapter, "_subs", set()) or set())
                active_subs = len(subs)
        except Exception:
            # fallback to telemetry gauge
            try:
                active_subs = int(metrics.get("gauges", {}).get("market_data_active_subscriptions", 0))
            except Exception:
                active_subs = active_subs

        ok = adapter_present and ws_connected
        return {
            "ok": ok,
            "ws_connected": ws_connected,
            "last_msg_age_s": last_msg_age,
            "active_subscriptions": active_subs,
            "stale_tokens": stale_tokens,
            "eventbus_dropped_total": eventbus_dropped,
            "notes": notes,
        }

    @app.post("/market-data/admin/subscribe")
    async def market_data_admin_subscribe(body: dict) -> Any:
        """
        Admin helper to request a best-effort subscription for a token.
        Body: {"token": "<token_id>"}
        """
        token = body.get("token")
        if not token:
            return {"ok": False, "error": "token required"}
        try:
            # import lazily to avoid circular import at module load
            from webhook_server_fastapi import _market_data_adapter  # type: ignore
            if _market_data_adapter and getattr(_market_data_adapter, "subscribe", None):
                try:
                    import asyncio
                    loop = asyncio.get_running_loop()
                    loop.create_task(_market_data_adapter.subscribe(token))
                except RuntimeError:
                    import threading
                    threading.Thread(target=lambda: __import__("asyncio").run(_market_data_adapter.subscribe(token))).start()
                return {"ok": True, "scheduled": True, "token": token}
            else:
                return {"ok": False, "scheduled": False, "reason": "adapter_unavailable"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/market-data/subscriptions")
    async def market_data_subscriptions(request: Request) -> Any:
        """
        Return current subscriptions with refcount (best-effort) and missing_cycles from reconcile state.
        """
        settings = get_settings()
        # protect debug/admin endpoint
        if not getattr(settings, "DEBUG_ENDPOINTS_ENABLED", False):
            raise HTTPException(status_code=403, detail="debug endpoints disabled")
        token_required = getattr(settings, "DEBUG_ENDPOINTS_TOKEN", None)
        if token_required:
            header_token = request.headers.get("X-Debug-Token")
            if header_token != token_required:
                raise HTTPException(status_code=403, detail="invalid debug token")
        try:
            # lazy import to avoid circular module init issues
            import webhook_server_fastapi as ws  # type: ignore
            adapter = getattr(ws, "_market_data_adapter", None)
            desired_refcount = getattr(ws, "_market_data_desired_refcount", {}) or {}
            reconcile_state = getattr(ws, "_market_data_reconcile_state", None)
            if adapter is None:
                return {"ok": False, "error": "adapter_unavailable", "active_subscriptions": 0, "tokens": []}

            subs = set(getattr(adapter, "_subs", set()) or set())
            tokens = []
            # union of known tokens (adapter subs + last desired)
            all_tokens = sorted(set(list(subs) + list(desired_refcount.keys())))
            for tk in all_tokens:
                refcount = int(desired_refcount.get(tk, 1 if tk in subs else 0))
                missing = 0
                if reconcile_state is not None:
                    missing = int(getattr(reconcile_state, "missing_count", {}).get(tk, 0))
                tokens.append({"token_id": tk, "refcount": refcount, "missing_cycles": missing})

            return {"ok": True, "active_subscriptions": len(subs), "tokens": tokens}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _require_debug_access(request: Request) -> None:
        settings = get_settings()
        if not getattr(settings, "DEBUG_ENDPOINTS_ENABLED", False):
            # hide endpoint when disabled
            raise HTTPException(status_code=404, detail="not found")
        token_required = getattr(settings, "DEBUG_ENDPOINTS_TOKEN", None)
        if token_required:
            header_token = request.headers.get("X-Debug-Token")
            if header_token != token_required:
                raise HTTPException(status_code=403, detail="invalid debug token")

    @app.post("/market-data/admin/discover-subscribe")
    async def market_data_admin_discover_subscribe(request: Request) -> Any:
        """
        Debug one-shot: discover 5m/15m market, optionally subscribe adapter to clob tokens,
        wait a few seconds and report telemetry + subscriptions.
        """
        _require_debug_access(request)
        body = await request.json()
        timeframe_minutes = int(body.get("timeframe_minutes", 5))
        signal_id = body.get("signal_id")
        dry_run = bool(body.get("dry_run", False))
        wait_seconds = int(body.get("wait_seconds", 8))
        wait_seconds = max(0, min(wait_seconds, 20))

        notes: list[str] = []
        derived_slug = None
        market_slug = None
        market_id = None
        clob_token_ids: list[str] = []
        subscribed_count = 0

        def _sample_payload() -> dict[str, Any]:
            unknown_sample = None
            raw_sample = None
            parse_error_sample = None
            try:
                adapter_local = getattr(request.app.state, "market_data_adapter", None)
                if adapter_local is not None:
                    if getattr(adapter_local, "get_unknown_sample", None):
                        unknown_sample = adapter_local.get_unknown_sample()
                    if getattr(adapter_local, "get_last_raw_sample", None):
                        raw_sample = adapter_local.get_last_raw_sample()
                    if getattr(adapter_local, "get_last_parse_error_sample", None):
                        parse_error_sample = adapter_local.get_last_parse_error_sample()
            except Exception:
                pass
            return {
                "unknown_sample": unknown_sample,
                "raw_sample": raw_sample,
                "parse_error_sample": parse_error_sample,
            }

        try:
            now_ts = time.time()
            if signal_id:
                try:
                    derived_slug = derive_btc_updown_slug_from_signal_id(signal_id, timeframe_minutes)
                except Exception:
                    derived_slug = None

            # attempt discovery
            try:
                mi = find_current_btc_updown_market(timeframe_minutes, now_ts, http_client=httpx.Client(timeout=10), signal_id=signal_id)
                market = mi.get("market") or {}
                market_slug = market.get("slug")
                market_id = market.get("id")
                clob = market.get("clobTokenIds") or mi.get("clobTokenIds") or []
                if isinstance(clob, str):
                    try:
                        import json as _json
                        clob = _json.loads(clob)
                    except Exception:
                        clob = [clob]
                clob_token_ids = [str(x) for x in (clob or [])]
            except NoCurrentMarket as e:
                notes.append(f"no_current_market: {e}")
                return {"ok": False, "derived_slug": derived_slug, "notes": notes, "metrics": telemetry.get_snapshot(), "subscriptions": {"active_subscriptions": 0, "tokens": []}, **_sample_payload()}
            except Exception as e:
                notes.append(f"discovery_error: {e}")
                return {"ok": False, "notes": notes, "metrics": telemetry.get_snapshot(), "subscriptions": {"active_subscriptions": 0, "tokens": []}, **_sample_payload()}

            # telemetry snapshot before
            snap_before = telemetry.get_snapshot()
            raw_before = snap_before.get("counters", {}).get("market_data_raw_messages_total", 0)
            msg_before = snap_before.get("counters", {}).get("market_data_messages_total", 0)

            # perform subscribe if requested and adapter available via app.state or module globals
            adapter_subscribed = False
            try:
                adapter = _resolve_adapter(request)
                if adapter is None:
                    notes.append("adapter_unavailable")
                    logger.warning("discover-subscribe: skipped subscribe because adapter unavailable")
                elif dry_run:
                    logger.info("discover-subscribe: dry_run enabled; skipping subscribe for market_id=%s token_count=%d", str(market_id), len(clob_token_ids))
                elif not clob_token_ids:
                    notes.append("no_clob_token_ids")
                    logger.info("discover-subscribe: no tokens to subscribe for market_id=%s", str(market_id))
                else:
                    logger.info("discover-subscribe: subscribing market_id=%s token_count=%d", str(market_id), len(clob_token_ids))
                    for tk in clob_token_ids:
                        try:
                            await adapter.subscribe(tk)
                            logger.info("discover-subscribe: subscribed token=%s", str(tk)[:24])
                        except Exception:
                            notes.append(f"subscribe_failed:{tk[:8]}")
                            logger.exception("discover-subscribe: subscribe failed for token=%s", str(tk)[:24])
                    subscribed_count = len(clob_token_ids)
                    adapter_subscribed = True
            except Exception as e:
                notes.append(f"adapter_access_error:{e}")

            # wait for traffic
            await asyncio.sleep(wait_seconds)

            snap_after = telemetry.get_snapshot()
            raw_after = snap_after.get("counters", {}).get("market_data_raw_messages_total", 0)
            msg_after = snap_after.get("counters", {}).get("market_data_messages_total", 0)
            last_msg_age_s = snap_after.get("last_msg_age_s")

            # build subscriptions snapshot best-effort
            try:
                adapter2 = _resolve_adapter(request)
                import webhook_server_fastapi as ws  # type: ignore
                desired_refcount = getattr(ws, "_market_data_desired_refcount", {}) or {}
                reconcile_state = getattr(ws, "_market_data_reconcile_state", None)

                subs = set(getattr(adapter2, "_subs", set()) or set()) if adapter2 else set()
                subs_list = []
                all_tokens = sorted(set(list(subs) + list(desired_refcount.keys())))
                for tk in all_tokens:
                    refcount = int(desired_refcount.get(tk, 1 if tk in subs else 0))
                    missing = 0
                    if reconcile_state is not None:
                        missing = int(getattr(reconcile_state, "missing_count", {}).get(tk, 0))
                    subs_list.append({"token_id": tk, "refcount": refcount, "missing_cycles": missing})
                subscriptions = {"active_subscriptions": len(subs), "tokens": subs_list}
            except Exception:
                subscriptions = {"ok": False, "error": "could_not_read_adapter_state"}

            metrics = snap_after
            # attempt to surface unknown sample from provider if available
            unknown_sample = None
            try:
                provider_unknown = None
                if adapter2:
                    provider_unknown = getattr(adapter2, "get_unknown_sample", None)
                    if provider_unknown:
                        unknown_sample = provider_unknown()
                if unknown_sample is None:
                    # fallback to module-level adapter
                    import webhook_server_fastapi as ws  # type: ignore
                    adapter_glob = getattr(ws, "_market_data_adapter", None)
                    if adapter_glob and getattr(adapter_glob, "get_unknown_sample", None):
                        unknown_sample = adapter_glob.get_unknown_sample()
            except Exception:
                unknown_sample = None

            # attempt to surface debug samples from adapter.get_debug_samples()
            raw_sample = None
            parse_error_sample = None
            try:
                ds = None
                if adapter2 and getattr(adapter2, "get_debug_samples", None):
                    ds = adapter2.get_debug_samples()
                if ds is None:
                    import webhook_server_fastapi as ws  # type: ignore
                    adapter_glob = getattr(ws, "_market_data_adapter", None)
                    if adapter_glob and getattr(adapter_glob, "get_debug_samples", None):
                        ds = adapter_glob.get_debug_samples()
                # if adapter2 itself exposes individual getters, use them as fallback
                if ds is None and adapter2:
                    try:
                        if getattr(adapter2, "get_last_raw_sample", None):
                            raw_sample = adapter2.get_last_raw_sample()
                        if getattr(adapter2, "get_last_parse_error_sample", None):
                            parse_error_sample = adapter2.get_last_parse_error_sample()
                        if unknown_sample is None and getattr(adapter2, "get_unknown_sample", None):
                            unknown_sample = adapter2.get_unknown_sample()
                    except Exception:
                        pass
                if isinstance(ds, dict):
                    raw_sample = ds.get("raw_sample")
                    parse_error_sample = ds.get("parse_error_sample")
                    if unknown_sample is None:
                        unknown_sample = ds.get("unknown_sample")
            except Exception:
                raw_sample = None
                parse_error_sample = None

            traffic_check = {
                "raw_messages_before": raw_before,
                "raw_messages_after": raw_after,
                "messages_before": msg_before,
                "messages_after": msg_after,
                "last_msg_age_s": last_msg_age_s,
            }

            return {
                "ok": True,
                "derived_slug": derived_slug,
                "market_slug": market_slug,
                "market_id": market_id,
                "clob_token_ids": clob_token_ids,
                "subscribed_count": subscribed_count,
                "adapter_subscribed": adapter_subscribed,
                "traffic_check": traffic_check,
                "metrics": metrics,
                "subscriptions": subscriptions,
                "unknown_sample": unknown_sample,
                "raw_sample": raw_sample,
                "parse_error_sample": parse_error_sample,
                "notes": notes,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "notes": notes}

