from typing import Optional, Dict, Any
import time
from src.config.settings import get_settings
from src.market_data.telemetry import telemetry


def place_entry_order_with_gate(
    polymarket,
    token_id: str,
    price: float,
    size: float,
    side: str = "BUY",
    confidence: Optional[int] = None,
    market_quality_healthy: Optional[bool] = None,
    adapter: Optional[object] = None,
    risk_manager: Optional[object] = None,
) -> Dict[str, Any]:
    """
    Central chokepoint for placing entry orders.
    Returns dict:
      - allowed: bool
      - reason: str
      - details: dict
      - order_id: str (if allowed)
    """
    details = {"token_id": token_id, "price": price, "size": size, "side": side, "ts": time.time()}
    # Use provided risk_manager if given; else try to obtain from running app or fallback to local instance
    rm = risk_manager
    if rm is None:
        try:
            from webhook_server_fastapi import get_risk_manager
            rm = get_risk_manager()
        except Exception:
            try:
                from agents.application.risk_manager import RiskManager
                settings = get_settings()
                rm = RiskManager(settings.INITIAL_EQUITY, settings.MAX_EXPOSURE_PCT, settings.BASE_RISK_PCT)
            except Exception:
                rm = None

    if rm and getattr(rm, "check_entry_allowed", None):
        allowed, reason, gate_details = rm.check_entry_allowed(
            token_id=token_id,
            confidence=confidence,
            market_quality_healthy=market_quality_healthy,
            adapter=adapter or polymarket,
            now_ts=time.time(),
            proposed_size=size,
        )
        details.update(gate_details or {})
        if not allowed:
            # telemetry increments are done in RiskManager; ensure a log-friendly return
            return {"allowed": False, "reason": reason, "details": details}
    # Deterministic A/B routing (50/50) based on token_id
    settings = get_settings()
    filters_enabled = False
    try:
        if getattr(settings, "ENTRY_FILTERS_AB_ENABLED", False):
            import hashlib
            h = hashlib.sha256(str(token_id).encode()).digest()[0]
            variant = h % 2
            # variant 1 = filters enabled
            filters_enabled = (variant == 1)
    except Exception:
        filters_enabled = False

    # If filters_enabled, apply simple entry filters using adapter/orderbook if available
    if filters_enabled:
        # MAX_ENTRY_PRICE
        try:
            max_price = getattr(settings, "MAX_ENTRY_PRICE", None)
            if max_price is not None and price is not None:
                if float(price) > float(max_price):
                    telemetry.incr("market_data_blocked_max_entry_price_total", 1)
                    details["blocked_by"] = "max_entry_price"
                    details["max_entry_price"] = max_price
                    return {"allowed": False, "reason": "max_entry_price", "details": details}
        except Exception:
            pass
        # --- Conservative sizing for Variant (apply only in AB variant) ---
        try:
            # helpers to get equity & open exposure
            def get_current_equity() -> float:
                try:
                    from webhook_server_fastapi import get_risk_manager
                    rm_local = get_risk_manager()
                    if rm_local and getattr(rm_local, "current_equity", None) is not None:
                        return float(rm_local.current_equity)
                except Exception:
                    pass
                # fallback to settings
                try:
                    telemetry.incr("sizing_fallback_equity_total", 1)
                except Exception:
                    pass
                return float(get_settings().INITIAL_EQUITY)

            def get_open_exposure_notional() -> float:
                try:
                    from webhook_server_fastapi import get_position_manager
                    pm_local = get_position_manager()
                    if pm_local:
                        total = 0.0
                        for t in getattr(pm_local, "active_trades", {}).values():
                            try:
                                total += float(getattr(t, "total_size", 0.0) or 0.0)
                            except Exception:
                                pass
                        return total
                except Exception:
                    pass
                try:
                    telemetry.incr("sizing_fallback_exposure_total", 1)
                except Exception:
                    pass
                return 0.0

            equity = get_current_equity()
            open_exposure = get_open_exposure_notional()
            budget_total = float(getattr(settings, "MAX_TOTAL_EXPOSURE_PCT", 0.10)) * equity
            budget_left = max(0.0, budget_total - float(open_exposure))
            desired = float(getattr(settings, "POSITION_RISK_PCT_PER_TRADE", 0.02)) * equity
            final_size = min(desired, budget_left)
            if final_size <= 0:
                try:
                    telemetry.incr("sizing_budget_exhausted_total", 1)
                except Exception:
                    pass
                details["blocked_by"] = "exposure_budget_exhausted"
                details["budget_total"] = budget_total
                details["open_exposure"] = open_exposure
                details["budget_left"] = budget_left
                return {"allowed": False, "reason": "exposure_budget_exhausted", "details": details}
            # apply final size (may be capped)
            if final_size < size:
                try:
                    telemetry.incr("sizing_capped_total", 1)
                except Exception:
                    pass
            try:
                telemetry.incr("sizing_variant_applied_total", 1)
            except Exception:
                pass
            size = float(final_size)
            details["sizing_applied"] = True
            details["final_size"] = size
        except Exception:
            # sizing fallback: proceed with original size
            pass

        # Need orderbook to compute edge and spread
        try:
            ob = None
            provider = adapter or polymarket
            if provider and getattr(provider, "get_orderbook", None):
                ob = provider.get_orderbook(token_id)
            if ob:
                try:
                    bids = getattr(ob, "bids", []) or []
                    asks = getattr(ob, "asks", []) or []
                    best_bid = float(bids[0].price) if bids else None
                    best_ask = float(asks[0].price) if asks else None
                    mid = None
                    if best_bid is not None and best_ask is not None:
                        mid = (best_bid + best_ask) / 2.0
                    # MIN_EDGE_CENTS check (absolute difference)
                    min_edge = getattr(settings, "MIN_EDGE_CENTS", None)
                    if min_edge is not None and mid is not None and price is not None:
                        edge = abs(float(price) - float(mid))
                        if edge < float(min_edge):
                            telemetry.incr("market_data_blocked_min_edge_total", 1)
                            details["blocked_by"] = "min_edge"
                            details["edge"] = edge
                            details["min_edge"] = min_edge
                            return {"allowed": False, "reason": "min_edge", "details": details}
                    # MAX_SPREAD_PCT check
                    max_sp = getattr(settings, "MAX_SPREAD_PCT", None)
                    if max_sp is not None and best_bid is not None and best_ask is not None and mid is not None and mid > 0:
                        spread_pct = (best_ask - best_bid) / mid
                        if spread_pct > float(max_sp):
                            telemetry.incr("market_data_blocked_max_spread_total", 1)
                            details["blocked_by"] = "max_spread_pct"
                            details["spread_pct"] = spread_pct
                            details["max_spread_pct"] = max_sp
                            return {"allowed": False, "reason": "max_spread_pct", "details": details}
                except Exception:
                    pass
        except Exception:
            pass

    # Allowed: perform the order via polymarket, ensuring gate_checked flag
    try:
        order_id = polymarket.execute_order(price=price, size=size, side=side, token_id=token_id, gate_checked=True)
        return {"allowed": True, "reason": "ok", "details": details, "order_id": order_id}
    except Exception as e:
        telemetry.incr("market_data_execute_order_error_total", 1)
        return {"allowed": False, "reason": "execute_error", "details": {**details, "error": str(e)}}

