"""
FastAPI Webhook Server for TradingView → Polymarket Bot (DRY RUN)
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, Union
import time
import requests
import json
import uuid
import shutil
import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

# Infrastructure imports
from src.config.settings import get_settings, is_live_trading_allowed, is_paper_trading, get_trading_mode_str
from src.utils.logger import setup_logging, get_logger
from src.utils.exceptions import BotError, ValidationError, APIError
from src.utils.helpers import (
    parse_bool, parse_int, parse_float, normalize_signal,
    utc_now_iso, calc_session
)

# Initialize settings and logging
settings = get_settings()
setup_logging(settings)
logger = get_logger(__name__)

app = FastAPI(
    title="TradingView → Polymarket Bot",
    description=f"Mode: {get_trading_mode_str()}"
)

# Server startup time for uptime calculation
_server_start_time = None

# Metrics tracking
_confirm_requests_total = 0
_confirm_requests_409 = 0

# Phase 2 Block Counters
_blocked_conf_high = 0  # rawConf >= 6
_blocked_conf_low = 0   # rawConf < 4
_blocked_session_ny = 0  # NY session blocked (legacy, kept for backward compatibility)
_blocked_ny_no_botmove = 0  # NY session blocked: botMove=false AND mr=false
_blocked_conf_missing = 0  # rawConf missing (UNKNOWN)

# Run marker tracking
_current_run_id = None

# Rehydration metrics
_rehydrated_trades_count = 0
_rehydrate_errors = 0

# Signal ID Deduplication Cache
# Format: {signal_id: timestamp}
_signal_id_cache: Dict[str, float] = {}
_signal_id_cache_ttl_seconds = 30 * 60  # 30 minutes
_duplicate_signals_count = 0

# Startup event
@app.on_event("startup")
async def startup_event():
    global _server_start_time, _current_run_id
    _server_start_time = time.time()
    
    # Log Phase 2 Run Marker
    _current_run_id = utc_now_iso()
    logger.info("=" * 60)
    logger.info(f"PHASE_2_START run_id={_current_run_id}")
    logger.info("=" * 60)
    
    # Trading Mode Guard
    from src.config.settings import is_live_trading_allowed, is_paper_trading
    
    trading_mode = settings.TRADING_MODE.upper()
    is_paper = is_paper_trading()
    
    # Log trading mode clearly
    logger.info("=" * 60)
    if is_paper:
        logger.info("📝 TRADING MODE: PAPER")
        logger.info(f"   Paper log: {settings.PAPER_LOG_PATH}")
        logger.info(f"   Token set: no (paper mode)")
        logger.info(f"   Kill Switch: {'ENABLED' if settings.LIVE_KILL_SWITCH else 'disabled'}")
    else:
        # Check if live trading is actually allowed
        allowed, reason = is_live_trading_allowed()
        token_set = "yes" if settings.LIVE_CONFIRMATION_TOKEN else "no"
        kill_switch_status = "ENABLED" if settings.LIVE_KILL_SWITCH else "disabled"
        if allowed:
            logger.warning("=" * 60)
            logger.warning("⚠️  TRADING MODE: LIVE")
            logger.warning("⚠️  REAL ORDERS WILL BE EXECUTED!")
            logger.warning(f"   Token set: {token_set}")
            logger.warning(f"   Kill Switch: {kill_switch_status}")
            logger.warning("=" * 60)
        else:
            # HARD FAIL by default (no silent fallback)
            if settings.ALLOW_FALLBACK_TO_PAPER:
                logger.error("=" * 60)
                logger.error("❌ LIVE TRADING MODE REQUESTED BUT NOT ALLOWED")
                logger.error(f"   Token set: {token_set}")
                logger.error(f"   ALLOW_LIVE: {settings.ALLOW_LIVE}")
                logger.error(f"   Kill Switch: {kill_switch_status}")
                logger.error(f"   Reason: {reason}")
                logger.error("   ALLOW_FALLBACK_TO_PAPER=true: Falling back to PAPER mode")
                logger.error("=" * 60)
                # Force paper mode if fallback allowed
                settings.TRADING_MODE = "paper"
                is_paper = True
            else:
                logger.error("=" * 60)
                logger.error("❌ LIVE TRADING MODE REQUESTED BUT NOT ALLOWED")
                logger.error(f"   Token set: {token_set}")
                logger.error(f"   ALLOW_LIVE: {settings.ALLOW_LIVE}")
                logger.error(f"   Kill Switch: {kill_switch_status}")
                logger.error(f"   Reason: {reason}")
                logger.error("   HARD FAIL: Server will start, but order execution will fail")
                logger.error("   Set ALLOW_FALLBACK_TO_PAPER=true to enable fallback to paper mode")
                logger.error("=" * 60)
                # Keep live mode, but orders will fail with BotError
    
    logger.info(f"Server starting on {settings.APP_HOST}:{settings.APP_PORT}")
    logger.info("=" * 60)
    
    # ─────────────────────────────────────────────
    # SESSION MANAGEMENT: Initialize SESSION_ID and PHASE2_SESSION_ID
    # ─────────────────────────────────────────────
    if is_paper_trading():
        # Generate SESSION_ID if not set
        if not settings.SESSION_ID:
            import uuid
            settings.SESSION_ID = f"session_{uuid.uuid4().hex[:8]}_{int(time.time())}"
            logger.info(f"Generated new SESSION_ID: {settings.SESSION_ID}")
        else:
            logger.info(f"Using existing SESSION_ID: {settings.SESSION_ID}")
        
        # Generate PHASE2_SESSION_ID if not set (separate from SESSION_ID)
        if not settings.PHASE2_SESSION_ID:
            import uuid
            settings.PHASE2_SESSION_ID = f"phase2_{uuid.uuid4().hex[:8]}_{int(time.time())}"
            logger.info(f"Generated new PHASE2_SESSION_ID: {settings.PHASE2_SESSION_ID}")
        else:
            logger.info(f"Using existing PHASE2_SESSION_ID: {settings.PHASE2_SESSION_ID}")
        
        # Archive old paper_trades.jsonl if enabled and file exists
        if settings.ARCHIVE_ON_STARTUP:
            log_path = Path(settings.PAPER_LOG_PATH)
            if log_path.exists() and log_path.stat().st_size > 0:
                legacy_path = Path("paper_trades_legacy.jsonl")
                # If legacy file exists, append timestamp to make it unique
                if legacy_path.exists():
                    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    legacy_path = Path(f"paper_trades_legacy_{timestamp}.jsonl")
                
                try:
                    shutil.copy2(log_path, legacy_path)
                    logger.info(f"Archived {settings.PAPER_LOG_PATH} → {legacy_path}")
                    
                    # Clear the original file (start fresh)
                    log_path.write_text("", encoding="utf-8")
                    logger.info(f"Cleared {settings.PAPER_LOG_PATH} (starting fresh session)")
                except Exception as e:
                    logger.error(f"Failed to archive paper_trades.jsonl: {e}")
            else:
                logger.info(f"No existing {settings.PAPER_LOG_PATH} to archive (file empty or missing)")
    
    # Log Risk Management Parameters (sanitized)
    logger.info("=" * 60)
    logger.info("RISK MANAGEMENT CONFIGURATION")
    logger.info("=" * 60)
    logger.info(f"  BASE_RISK_PCT: {settings.BASE_RISK_PCT} ({settings.BASE_RISK_PCT * 100:.1f}% of equity per trade)")
    logger.info(f"  MAX_EXPOSURE_PCT: {settings.MAX_EXPOSURE_PCT} ({settings.MAX_EXPOSURE_PCT * 100:.1f}% of equity max)")
    logger.info(f"  SOFT_STOP_ADVERSE_MOVE: {settings.SOFT_STOP_ADVERSE_MOVE} (adverse move threshold)")
    logger.info(f"  TIME_STOP_BARS: {settings.TIME_STOP_BARS} (bars before time-stop exit)")
    logger.info(f"  ENABLE_SESSION_FILTER: {settings.ENABLE_SESSION_FILTER}")
    logger.info(f"  INITIAL_EQUITY: {settings.INITIAL_EQUITY} USDC")
    logger.info(f"  MIN_CONFIDENCE: {settings.MIN_CONFIDENCE}")
    logger.info(f"  MAX_CONFIDENCE: {settings.MAX_CONFIDENCE}")
    logger.info(f"  ALLOW_CONF_4: {settings.ALLOW_CONF_4}")
    logger.info(f"  CONFIRM_TTL_SECONDS: {settings.CONFIRM_TTL_SECONDS}s")
    logger.info("=" * 60)
    
    # Log Auto-Close Configuration
    logger.info("=" * 60)
    logger.info("AUTO-CLOSE CONFIGURATION")
    logger.info("=" * 60)
    logger.info(f"  AUTO_CLOSE_ENABLED: {settings.AUTO_CLOSE_ENABLED}")
    logger.info(f"  AUTO_CLOSE_TTL_MINUTES: {settings.AUTO_CLOSE_TTL_MINUTES}")
    logger.info(f"  AUTO_CLOSE_ON_MARKET_END: {settings.AUTO_CLOSE_ON_MARKET_END}")
    logger.info(f"  AUTO_CLOSE_PRICE_POLL_INTERVAL: {settings.AUTO_CLOSE_PRICE_POLL_INTERVAL}s")
    logger.info("=" * 60)
    
    # Start background cleanup task for timeout trades
    import asyncio
    async def cleanup_task():
        pm = get_position_manager()
        while True:
            try:
                await asyncio.sleep(5.0)  # Check every 5 seconds
                cleaned = pm.cleanup_timeout_trades()
                if cleaned > 0:
                    logger.info(f"Cleaned up {cleaned} timed out trades")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup task error: {e}")
    
    # Start cleanup task in background
    asyncio.create_task(cleanup_task())
    logger.info("Background cleanup task started")
    
    # Rehydrate active paper trades from paper_trades.jsonl
    if is_paper_trading():
        rehydrated_count = rehydrate_paper_trades()
        if rehydrated_count > 0:
            logger.info(f"Rehydrated {rehydrated_count} active paper trades into PositionManager")
        cleaned_file_orphans = cleanup_orphan_paper_trades()
        if cleaned_file_orphans > 0:
            logger.warning(f"ORPHAN FILE CLEANUP: Closed {cleaned_file_orphans} trades on startup")
    
    # Orphan Cleanup Task (closes old open trades)
    async def orphan_cleanup_task():
        """Background task to close orphan trades (old open trades)."""
        if not settings.ORPHAN_CLEANUP_ENABLED:
            logger.debug("Orphan cleanup task disabled")
            return
        
        pm = get_position_manager()
        poll_interval = 60.0  # Check every 60 seconds
        
        while True:
            try:
                await asyncio.sleep(poll_interval)
                
                if not is_paper_trading():
                    continue
                
                from datetime import datetime, timezone, timedelta
                import time as time_module
                
                # Get all active trades from PositionManager
                from agents.application.position_manager import TradeStatus
                active_trades = [
                    trade for trade in pm.active_trades.values()
                    if trade.status in (
                        TradeStatus.PENDING,
                        TradeStatus.CONFIRMED,
                        TradeStatus.ADDED,
                        TradeStatus.HEDGED,
                    )
                    and not trade.exited
                    and not trade.closing
                ]
                
                now_utc = datetime.now(timezone.utc)
                max_age_seconds = settings.MAX_OPEN_AGE_MIN * 60.0  # Convert minutes to seconds
                max_age_bars = settings.MAX_OPEN_AGE_BARS
                
                closed_count = 0
                for trade in active_trades:
                    try:
                        # Calculate age
                        trade_time_str = trade.created_at_utc
                        if not trade_time_str:
                            # Fallback: use monotonic time
                            age_seconds = time_module.monotonic() - trade.created_at
                            age_minutes = age_seconds / 60.0
                            age_bars = int(age_seconds / 900)  # 15min = 1 bar
                        else:
                            try:
                                trade_time = datetime.fromisoformat(str(trade_time_str).replace("Z", "+00:00"))
                                age_delta = now_utc - trade_time
                                age_seconds = age_delta.total_seconds()
                                age_minutes = age_seconds / 60.0
                                age_bars = int(age_seconds / 900)  # 15min = 1 bar
                            except (ValueError, AttributeError):
                                # Fallback
                                age_seconds = time_module.monotonic() - trade.created_at
                                age_minutes = age_seconds / 60.0
                                age_bars = int(age_seconds / 900)
                        
                        # Check if trade is too old
                        is_orphan = False
                        if age_minutes > settings.MAX_OPEN_AGE_MIN:
                            is_orphan = True
                        elif age_bars > max_age_bars:
                            is_orphan = True
                        
                        if is_orphan:
                            logger.warning(
                                f"ORPHAN CLEANUP: Closing trade {trade.trade_id} "
                                f"(age: {age_minutes:.1f}min / {age_bars} bars, "
                                f"max: {settings.MAX_OPEN_AGE_MIN}min / {max_age_bars} bars)"
                            )
                            
                            # Get exit price - HARD RULE: must have best_bid
                            exit_price = _get_exit_price_only(trade)
                            if exit_price is None:
                                # No best_bid = cannot close = skip (trade stays open)
                                logger.warning(
                                    f"ORPHAN CLEANUP: Trade {trade.trade_id} has no exit price (no best_bid). "
                                    f"Trade stays OPEN - no fake exit price allowed."
                                )
                                continue
                            
                            # Close trade (we have a real exit price)
                            exit_result = pm.exit_trade(
                                trade_id=trade.trade_id,
                                exit_price=exit_price,
                                exit_reason="orphan_cleanup",
                                exit_request_id=f"orphan_cleanup_{trade.trade_id}_{int(time.time() * 1000)}",
                            )
                            
                            if exit_result.get("ok") and not exit_result.get("already_handled"):
                                realized_pnl = exit_result.get("realized_pnl")
                                
                                # Update paper_trades.jsonl
                                update_paper_trade_close(
                                    log_path=settings.PAPER_LOG_PATH,
                                    trade_id=trade.trade_id,
                                    realized_pnl=realized_pnl,  # May be None if invalid
                                    exit_price=exit_price,
                                    exit_reason="orphan_cleanup",
                                    exit_time_utc=utc_now_iso(),
                                )
                                
                                closed_count += 1
                                logger.info(
                                    f"ORPHAN CLEANUP: Closed trade {trade.trade_id} "
                                    f"(realized_pnl={realized_pnl}, exit_price={exit_price:.4f})"
                                )
                            elif exit_result.get("already_handled"):
                                logger.debug(f"ORPHAN CLEANUP: Trade {trade.trade_id} already closed")
                    
                    except Exception as e:
                        logger.error(f"ORPHAN CLEANUP: Error processing trade {trade.trade_id}: {e}")
                        continue
                
                if closed_count > 0:
                    logger.info(f"ORPHAN CLEANUP: Closed {closed_count} orphan trades")
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Orphan cleanup task error: {e}")
    
    async def orphan_file_cleanup_task():
        """Background task to close file-only orphan trades."""
        if not settings.ORPHAN_CLEANUP_ENABLED:
            logger.debug("Orphan file cleanup task disabled")
            return

        poll_interval = 120.0  # Check every 2 minutes
        while True:
            try:
                await asyncio.sleep(poll_interval)
                if not is_paper_trading():
                    continue
                cleanup_orphan_paper_trades()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Orphan file cleanup task error: {e}")

        # Start orphan cleanup task
        if settings.ORPHAN_CLEANUP_ENABLED:
            asyncio.create_task(orphan_cleanup_task())
            logger.info("Orphan cleanup task started")
        asyncio.create_task(orphan_file_cleanup_task())
        logger.info("Orphan file cleanup task started")
        
        # Start signal ID cache cleanup task
        asyncio.create_task(signal_id_cache_cleanup_task())
        logger.info("Signal ID cache cleanup task started")
    
    # Start risk management monitoring task (soft-stop, time-stop)
    async def risk_monitoring_task():
        pm = get_position_manager()
        rm = get_risk_manager()
        mt = get_metrics_tracker()
        
        # Use AUTO_CLOSE_PRICE_POLL_INTERVAL for polling frequency
        poll_interval = settings.AUTO_CLOSE_PRICE_POLL_INTERVAL
        
        while True:
            try:
                await asyncio.sleep(poll_interval)  # Check every N seconds (default: 30s)
                
                from agents.application.position_manager import TradeStatus
                
                # Get active trades (exclude already exited or closing)
                active_trades = [
                    trade for trade in pm.active_trades.values()
                    if trade.status in (
                        TradeStatus.PENDING,
                        TradeStatus.CONFIRMED,
                        TradeStatus.ADDED,
                        TradeStatus.HEDGED,
                    )
                    and not trade.exited
                    and not trade.closing  # Skip trades that are already closing
                ]
                
                for trade in active_trades:
                    # Update current_price for Paper Trades (price polling)
                    # Uses MID PRICE (consistent with entry/exit) for Paper Trading
                    if is_paper_trading() and settings.AUTO_CLOSE_ENABLED and trade.token_id:
                        try:
                            from agents.polymarket.polymarket import Polymarket
                            if not hasattr(risk_monitoring_task, '_polymarket'):
                                risk_monitoring_task._polymarket = Polymarket()
                            
                            # Fetch full orderbook to get MID PRICE (consistent with entry/exit)
                            orderbook = risk_monitoring_task._polymarket.get_orderbook(trade.token_id)
                            
                            # Extract best bid/ask
                            best_bid = None
                            best_ask = None
                            
                            if orderbook.bids and len(orderbook.bids) > 0:
                                best_bid = float(orderbook.bids[0].price)
                            
                            if orderbook.asks and len(orderbook.asks) > 0:
                                best_ask = float(orderbook.asks[0].price)
                            
                            # Use MID PRICE (consistent with entry/exit)
                            if best_bid and best_ask:
                                current_price = (best_bid + best_ask) / 2.0
                            elif best_ask:
                                current_price = best_ask
                            elif best_bid:
                                current_price = best_bid
                            else:
                                # Fallback to simple price fetch if orderbook is empty
                                current_price = risk_monitoring_task._polymarket.get_orderbook_price(trade.token_id)
                            
                            trade.current_price = current_price
                        except Exception as e:
                            # Fallback: use entry_price if price fetch fails
                            if not trade.current_price:
                                trade.current_price = trade.entry_price
                            logger.debug(f"Price update failed for trade {trade.trade_id}: {e}")
                    
                    # Update PnL
                    if trade.current_price:
                        pm.update_pnl(trade.trade_id, trade.current_price)
                    
                    # Check soft-stop (only if not already closing)
                    if trade.current_price and not trade.closing:
                        soft_stop_check = rm.check_soft_stop(trade, trade.current_price)
                        if soft_stop_check.should_exit:
                            # DEBUG: Log close reason details
                            now_ts = time.monotonic()
                            opened_ts = trade.created_at
                            age_seconds = now_ts - opened_ts
                            ttl_seconds_computed = settings.AUTO_CLOSE_TTL_MINUTES * 60.0
                            slot_duration_seconds = 15 * 60
                            market_end_due = age_seconds >= slot_duration_seconds
                            exit_reason_final = soft_stop_check.reason.value if soft_stop_check.reason else "soft_stop"
                            
                            logger.info(
                                f"DEBUG CLOSE: trade_id={trade.trade_id}, "
                                f"opened_at={opened_ts:.2f}, now={now_ts:.2f}, age_seconds={age_seconds:.2f}, "
                                f"ttl_minutes_config={settings.AUTO_CLOSE_TTL_MINUTES}, "
                                f"ttl_seconds_computed={ttl_seconds_computed:.2f}, "
                                f"market_end_due={market_end_due}, soft_stop_triggered=True, "
                                f"no_progress_triggered=False, which_rule_fired=soft_stop, exit_reason={exit_reason_final}"
                            )
                            # Execute exit - HARD RULE: must have best_bid
                            exit_price = _get_exit_price_only(trade)
                            if exit_price is None:
                                logger.warning(
                                    f"SOFT STOP: Trade {trade.trade_id} has no exit price (no best_bid). "
                                    f"Trade stays OPEN - no fake exit price allowed."
                                )
                                continue
                            exit_result = pm.exit_trade(
                                trade_id=trade.trade_id,
                                exit_price=exit_price,
                                exit_reason=exit_reason_final,
                                exit_request_id=f"soft_stop_{trade.trade_id}_{int(time.time() * 1000)}",
                            )
                            if exit_result.get("ok") and not exit_result.get("already_handled"):
                                realized_pnl = exit_result.get("realized_pnl", 0.0)
                                exit_reason_str = soft_stop_check.reason.value if soft_stop_check.reason else "soft_stop"
                                
                                # Detailed logging for PnL debug
                                logger.info(
                                    f"PnL DEBUG CLOSE: trade_id={trade.trade_id}, "
                                    f"side={trade.side}, entry_price={trade.entry_price:.6f}, "
                                    f"exit_price={exit_price:.6f}, shares={trade.total_size:.2f}, "
                                    f"realized_pnl_raw={realized_pnl:.6f}, realized_pnl={realized_pnl:.2f}"
                                )
                                
                                # Update paper_trades.jsonl with realized_pnl (for Paper Trades)
                                if is_paper_trading():
                                    update_paper_trade_close(
                                        log_path=settings.PAPER_LOG_PATH,
                                        trade_id=trade.trade_id,
                                        realized_pnl=realized_pnl,
                                        exit_price=exit_price,
                                        exit_reason=exit_reason_str,
                                        exit_time_utc=utc_now_iso(),
                                    )
                                
                                # Update metrics (include MAE/MFE for Soft-Stop validation)
                                # Read spread_entry from trade record
                                spread_entry = get_spread_entry_from_trade_record(
                                    trade_id=trade.trade_id,
                                    log_path=settings.PAPER_LOG_PATH
                                )
                                mt.complete_trade(
                                    trade_id=trade.trade_id,
                                    exit_price=exit_price,
                                    realized_pnl=realized_pnl,
                                    exit_reason=exit_reason_str,
                                    mae=trade.mae,
                                    mfe=trade.mfe,
                                    spread_entry=spread_entry,
                                )
                                # Update risk manager equity
                                rm.update_equity(realized_pnl)
                                logger.info(
                                    f"Soft-stop exit executed for trade {trade.trade_id}: "
                                    f"realized_pnl={realized_pnl:.2f}, "
                                    f"mae={trade.mae:.2f}, mfe={trade.mfe:.2f}, "
                                    f"exit_request_id={exit_result.get('exit_request_id', 'N/A')}"
                                )
                            elif exit_result.get("already_handled"):
                                logger.debug(
                                    f"Soft-stop exit already handled for trade {trade.trade_id} "
                                    f"(status={exit_result.get('status')})"
                                )
                    
                    # Check Market-End auto-close (for Paper Trades)
                    if is_paper_trading() and settings.AUTO_CLOSE_ON_MARKET_END and not trade.closing:
                        try:
                            # For 15m markets: Auto-close after 15 minutes (slot duration)
                            # Markets expire when the 15min slot ends
                            now_ts = time.monotonic()
                            opened_ts = trade.created_at
                            age_seconds = now_ts - opened_ts
                            slot_duration_seconds = 15 * 60  # 15 minutes
                            ttl_seconds_computed = settings.AUTO_CLOSE_TTL_MINUTES * 60.0
                            
                            if age_seconds >= slot_duration_seconds:
                                # DEBUG: Log close reason details
                                exit_reason_final = "market_end"
                                logger.info(
                                    f"DEBUG CLOSE: trade_id={trade.trade_id}, "
                                    f"opened_at={opened_ts:.2f}, now={now_ts:.2f}, age_seconds={age_seconds:.2f}, "
                                    f"ttl_minutes_config={settings.AUTO_CLOSE_TTL_MINUTES}, "
                                    f"ttl_seconds_computed={ttl_seconds_computed:.2f}, "
                                    f"market_end_due=True, soft_stop_triggered=False, "
                                    f"no_progress_triggered=False, which_rule_fired=market_end, exit_reason={exit_reason_final}"
                                )
                                # Market slot expired - auto-close
                                # HARD RULE: must have best_bid for exit
                                exit_price = _get_exit_price_only(trade)
                                if exit_price is None:
                                    logger.warning(
                                        f"MARKET END: Trade {trade.trade_id} has no exit price (no best_bid). "
                                        f"Trade stays OPEN - no fake exit price allowed. "
                                        f"(Market may be expired, orderbook empty)"
                                    )
                                    continue
                                exit_result = pm.exit_trade(
                                    trade_id=trade.trade_id,
                                    exit_price=exit_price,
                                    exit_reason=exit_reason_final,
                                    exit_request_id=f"market_end_{trade.trade_id}_{int(time.time() * 1000)}",
                                )
                                if exit_result.get("ok") and not exit_result.get("already_handled"):
                                    realized_pnl = exit_result.get("realized_pnl", 0.0)
                                    # Detailed logging for PnL debug
                                    logger.info(
                                        f"PnL DEBUG CLOSE: trade_id={trade.trade_id}, "
                                        f"side={trade.side}, entry_price={trade.entry_price:.6f}, "
                                        f"exit_price={exit_price:.6f}, shares={trade.total_size:.2f}, "
                                        f"realized_pnl_raw={realized_pnl:.6f}, realized_pnl={realized_pnl:.2f}"
                                    )
                                    update_paper_trade_close(
                                        log_path=settings.PAPER_LOG_PATH,
                                        trade_id=trade.trade_id,
                                        realized_pnl=realized_pnl,
                                        exit_price=exit_price,
                                        exit_reason="market_end",
                                        exit_time_utc=utc_now_iso(),
                                    )
                                    # Read spread_entry from trade record
                                    spread_entry = get_spread_entry_from_trade_record(
                                        trade_id=trade.trade_id,
                                        log_path=settings.PAPER_LOG_PATH
                                    )
                                    mt.complete_trade(
                                        trade_id=trade.trade_id,
                                        exit_price=exit_price,
                                        realized_pnl=realized_pnl,
                                        exit_reason="market_end",
                                        mae=trade.mae,
                                        mfe=trade.mfe,
                                        spread_entry=spread_entry,
                                    )
                                    rm.update_equity(realized_pnl)
                                    logger.info(
                                        f"Market-end auto-close executed for trade {trade.trade_id}: "
                                        f"realized_pnl={realized_pnl:.2f}"
                                    )
                        except Exception as e:
                            logger.debug(f"Market-end check failed for trade {trade.trade_id}: {e}")
                    
                    # Check TTL-based auto-close (for Paper Trades)
                    if is_paper_trading() and settings.AUTO_CLOSE_ENABLED and not trade.closing:
                        now_ts = time.monotonic()
                        opened_ts = trade.created_at
                        age_seconds = now_ts - opened_ts
                        ttl_seconds_computed = settings.AUTO_CLOSE_TTL_MINUTES * 60.0
                        slot_duration_seconds = 15 * 60
                        market_end_due = age_seconds >= slot_duration_seconds
                        
                        # Check if TTL exceeded (using seconds-based comparison for precision)
                        if age_seconds >= ttl_seconds_computed:
                            # Sanity check: Ensure we're not closing too early
                            if age_seconds < ttl_seconds_computed:
                                # This should never happen due to the if condition, but log error if it does
                                logger.error(
                                    f"TTL SANITY CHECK FAILED: trade_id={trade.trade_id}, "
                                    f"age_seconds={age_seconds:.2f} < ttl_seconds_computed={ttl_seconds_computed:.2f} "
                                    f"(ttl_minutes_config={settings.AUTO_CLOSE_TTL_MINUTES}). "
                                    f"NOT closing via TTL - this is a bug!"
                                )
                            else:
                                # DEBUG: Log close reason details
                                exit_reason_final = "auto_close_ttl"
                                time_elapsed_minutes = age_seconds / 60.0
                                logger.info(
                                    f"DEBUG CLOSE: trade_id={trade.trade_id}, "
                                    f"opened_at={opened_ts:.2f}, now={now_ts:.2f}, age_seconds={age_seconds:.2f}, "
                                    f"ttl_minutes_config={settings.AUTO_CLOSE_TTL_MINUTES}, "
                                    f"ttl_seconds_computed={ttl_seconds_computed:.2f}, "
                                    f"market_end_due={market_end_due}, soft_stop_triggered=False, "
                                    f"no_progress_triggered=False, which_rule_fired=auto_close_ttl, exit_reason={exit_reason_final}"
                                )
                                # TTL exceeded - auto-close
                                # HARD RULE: must have best_bid for exit
                                exit_price = _get_exit_price_only(trade)
                                if exit_price is None:
                                    logger.warning(
                                        f"TTL CLOSE: Trade {trade.trade_id} has no exit price (no best_bid). "
                                        f"Trade stays OPEN - no fake exit price allowed."
                                    )
                                    continue
                                exit_result = pm.exit_trade(
                                    trade_id=trade.trade_id,
                                    exit_price=exit_price,
                                    exit_reason=exit_reason_final,
                                    exit_request_id=f"ttl_close_{trade.trade_id}_{int(time.time() * 1000)}",
                                )
                                if exit_result.get("ok") and not exit_result.get("already_handled"):
                                    realized_pnl = exit_result.get("realized_pnl", 0.0)
                                    # Detailed logging for PnL debug
                                    logger.info(
                                        f"PnL DEBUG CLOSE: trade_id={trade.trade_id}, "
                                        f"side={trade.side}, entry_price={trade.entry_price:.6f}, "
                                        f"exit_price={exit_price:.6f}, shares={trade.total_size:.2f}, "
                                        f"realized_pnl_raw={realized_pnl:.6f}, realized_pnl={realized_pnl:.2f}"
                                    )
                                    # Update paper_trades.jsonl with realized_pnl
                                    update_paper_trade_close(
                                        log_path=settings.PAPER_LOG_PATH,
                                        trade_id=trade.trade_id,
                                        realized_pnl=realized_pnl,
                                        exit_price=exit_price,
                                        exit_reason=exit_reason_final,
                                        exit_time_utc=utc_now_iso(),
                                    )
                                    # Update metrics
                                    # Read spread_entry from trade record
                                    spread_entry = get_spread_entry_from_trade_record(
                                        trade_id=trade.trade_id,
                                        log_path=settings.PAPER_LOG_PATH
                                    )
                                    mt.complete_trade(
                                        trade_id=trade.trade_id,
                                        exit_price=exit_price,
                                        realized_pnl=realized_pnl,
                                        exit_reason=exit_reason_final,
                                        mae=trade.mae,
                                        mfe=trade.mfe,
                                        spread_entry=spread_entry,
                                    )
                                    rm.update_equity(realized_pnl)
                                    logger.info(
                                        f"TTL auto-close executed for trade {trade.trade_id}: "
                                        f"realized_pnl={realized_pnl:.2f}, elapsed={time_elapsed_minutes:.1f}min"
                                    )
                    
                    # Check time-stop (only for LIVE trades, not Paper Trades)
                    # Phase-2: Time-Stop (30m) ist aus/irrelevant für Paper-Trades
                    # Paper-Trades werden primär durch Market-End (15m) oder TTL (18m) geschlossen
                    # Time-Stop bleibt nur für Live-Trades aktiv (falls benötigt)
                    if not is_paper_trading() and trade.current_price and not trade.closing:
                        # Calculate bars elapsed (approximate: 15min = 1 bar)
                        now_ts = time.monotonic()
                        opened_ts = trade.created_at
                        age_seconds = now_ts - opened_ts
                        bars_elapsed = int(age_seconds / 900)  # 900s = 15min
                        trade.bars_elapsed = bars_elapsed
                        ttl_seconds_computed = settings.AUTO_CLOSE_TTL_MINUTES * 60.0
                        slot_duration_seconds = 15 * 60
                        market_end_due = age_seconds >= slot_duration_seconds
                        
                        time_stop_check = rm.check_time_stop(trade, trade.current_price, bars_elapsed)
                        if time_stop_check.should_exit:
                            # DEBUG: Log close reason details
                            exit_reason_final = time_stop_check.reason.value if time_stop_check.reason else "time_stop_no_progress"
                            logger.info(
                                f"DEBUG CLOSE: trade_id={trade.trade_id}, "
                                f"opened_at={opened_ts:.2f}, now={now_ts:.2f}, age_seconds={age_seconds:.2f}, "
                                f"ttl_minutes_config={settings.AUTO_CLOSE_TTL_MINUTES}, "
                                f"ttl_seconds_computed={ttl_seconds_computed:.2f}, "
                                f"market_end_due={market_end_due}, soft_stop_triggered=False, "
                                f"no_progress_triggered=True, which_rule_fired=time_stop, exit_reason={exit_reason_final}"
                            )
                            # Execute exit - HARD RULE: must have best_bid
                            exit_price = _get_exit_price_only(trade)
                            if exit_price is None:
                                logger.warning(
                                    f"TIME STOP: Trade {trade.trade_id} has no exit price (no best_bid). "
                                    f"Trade stays OPEN - no fake exit price allowed."
                                )
                                continue
                            exit_result = pm.exit_trade(
                                trade_id=trade.trade_id,
                                exit_price=exit_price,
                                exit_reason=exit_reason_final,
                                exit_request_id=f"time_stop_{trade.trade_id}_{int(time.time() * 1000)}",
                            )
                            if exit_result.get("ok") and not exit_result.get("already_handled"):
                                realized_pnl = exit_result.get("realized_pnl", 0.0)
                                exit_reason_str = time_stop_check.reason.value if time_stop_check.reason else "time_stop"
                                
                                # Detailed logging for PnL debug
                                logger.info(
                                    f"PnL DEBUG CLOSE: trade_id={trade.trade_id}, "
                                    f"side={trade.side}, entry_price={trade.entry_price:.6f}, "
                                    f"exit_price={exit_price:.6f}, shares={trade.total_size:.2f}, "
                                    f"realized_pnl_raw={realized_pnl:.6f}, realized_pnl={realized_pnl:.2f}"
                                )
                                
                                # Update paper_trades.jsonl with realized_pnl (for Paper Trades)
                                if is_paper_trading():
                                    update_paper_trade_close(
                                        log_path=settings.PAPER_LOG_PATH,
                                        trade_id=trade.trade_id,
                                        realized_pnl=realized_pnl,
                                        exit_price=exit_price,
                                        exit_reason=exit_reason_str,
                                        exit_time_utc=utc_now_iso(),
                                    )
                                
                                # Update metrics (include MAE/MFE for Soft-Stop validation)
                                # Read spread_entry from trade record
                                spread_entry = get_spread_entry_from_trade_record(
                                    trade_id=trade.trade_id,
                                    log_path=settings.PAPER_LOG_PATH
                                ) if is_paper_trading() else None
                                mt.complete_trade(
                                    trade_id=trade.trade_id,
                                    exit_price=exit_price,
                                    realized_pnl=realized_pnl,
                                    exit_reason=exit_reason_str,
                                    mae=trade.mae,
                                    mfe=trade.mfe,
                                    spread_entry=spread_entry,
                                )
                                # Update risk manager equity
                                rm.update_equity(realized_pnl)
                                logger.info(
                                    f"Time-stop exit executed for trade {trade.trade_id}: "
                                    f"realized_pnl={realized_pnl:.2f}, "
                                    f"mae={trade.mae:.2f}, mfe={trade.mfe:.2f}, "
                                    f"exit_request_id={exit_result.get('exit_request_id', 'N/A')}"
                                )
                            elif exit_result.get("already_handled"):
                                logger.debug(
                                    f"Time-stop exit already handled for trade {trade.trade_id} "
                                    f"(status={exit_result.get('status')})"
                                )
                
                # Update metrics snapshot
                from agents.application.position_manager import TradeStatus
                total_pnl = pm.get_total_pnl()
                current_exposure = sum(
                    t.total_size for t in pm.active_trades.values()
                    if t.status in (
                        TradeStatus.PENDING,
                        TradeStatus.CONFIRMED,
                        TradeStatus.ADDED,
                        TradeStatus.HEDGED,
                    )
                )
                mt.update_snapshot(
                    unrealized_pnl=total_pnl.get("unrealized_pnl", 0.0),
                    realized_pnl=total_pnl.get("realized_pnl", 0.0),
                    exposure=current_exposure,
                )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Risk monitoring task error: {e}")
    
    # Start risk monitoring task
    asyncio.create_task(risk_monitoring_task())
    logger.info("Risk monitoring task started")

# ─────────────────────────────────────────────
# Slot-Lock State (global, simpel)
# ─────────────────────────────────────────────
last_slot = None

# ─────────────────────────────────────────────
# Fast Entry Engine Integration (optional)
# ─────────────────────────────────────────────
fast_entry_engine = None  # Will be set if Fast Entry Engine is running
position_manager = None  # Will be set if Fast Entry Engine is running
risk_manager = None  # Risk Manager instance
metrics_tracker = None  # Metrics tracker instance

def set_fast_entry_engine(engine, pos_manager):
    """Set Fast Entry Engine and Position Manager for confirmation actions."""
    global fast_entry_engine, position_manager
    fast_entry_engine = engine
    position_manager = pos_manager
    logger.info("Fast Entry Engine integration enabled")

def get_position_manager():
    """Get or create Position Manager instance."""
    global position_manager
    if position_manager is None:
        from agents.application.position_manager import PositionManager
        position_manager = PositionManager(default_timeout_seconds=settings.CONFIRM_TTL_SECONDS)
        logger.info("Position Manager initialized (default instance)")
    return position_manager

def get_risk_manager():
    """Get or create Risk Manager instance."""
    global risk_manager
    if risk_manager is None:
        from agents.application.risk_manager import RiskManager
        risk_manager = RiskManager(
            initial_equity=settings.INITIAL_EQUITY,
            max_exposure_pct=settings.MAX_EXPOSURE_PCT,
            base_risk_pct=settings.BASE_RISK_PCT,
        )
        logger.info("Risk Manager initialized")
    return risk_manager

def get_metrics_tracker():
    """Get or create Metrics Tracker instance."""
    global metrics_tracker
    if metrics_tracker is None:
        from agents.application.trade_metrics import TradeMetricsTracker
        metrics_tracker = TradeMetricsTracker(initial_equity=settings.INITIAL_EQUITY)
        logger.info("Metrics Tracker initialized")
    return metrics_tracker

def get_trading_mode_info():
    """
    Get trading mode information for API responses.
    
    Returns:
        dict with trading_mode_requested, trading_mode_effective, allow_live, token_set, 
        kill_switch_enabled, live_allowed_now
    """
    from src.config.settings import is_live_trading_allowed
    trading_mode_requested = settings.TRADING_MODE.upper() if settings.TRADING_MODE else "PAPER"
    trading_mode_effective = get_trading_mode_str()  # Effective mode (may differ if fallback occurred)
    allow_live = settings.ALLOW_LIVE
    token_set = bool(settings.LIVE_CONFIRMATION_TOKEN)
    kill_switch_enabled = settings.LIVE_KILL_SWITCH
    live_allowed_now, _ = is_live_trading_allowed()
    
    return {
        "trading_mode_requested": trading_mode_requested,
        "trading_mode_effective": trading_mode_effective,
        "allow_live": allow_live,
        "token_set": token_set,
        "kill_switch_enabled": kill_switch_enabled,
        "live_allowed_now": live_allowed_now,
    }

def current_slot_start(ts: int) -> int:
    # 15 Minuten = 900 Sekunden
    return (ts // 900) * 900

def slug_for_slot(slot_start: int) -> str:
    return f"{settings.PREFIX}-{slot_start}"

def fetch_market_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch market data from Polymarket API."""
    try:
        # Use connection pooling for better performance
        import httpx
        # Create persistent client (can be reused)
        if not hasattr(fetch_market_by_slug, '_client'):
            fetch_market_by_slug._client = httpx.Client(
                timeout=10.0,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        r = fetch_market_by_slug._client.get(
            f"{settings.GAMMA_API}/markets",
            params={"slug": slug},
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        return data[0]
    except requests.RequestException as e:
        logger.error(f"MARKET FETCH ERROR: {repr(e)}")
        raise APIError(f"Failed to fetch market: {str(e)}")
    except Exception as e:
        logger.error(f"MARKET FETCH ERROR: {repr(e)}")
        return None

def resolve_up_down_tokens(market: dict):
    """Extract UP and DOWN token IDs from market data."""
    clob_ids = market.get("clobTokenIds")

    # Falls als JSON-String geliefert → parsen
    if isinstance(clob_ids, str):
        try:
            clob_ids = json.loads(clob_ids)
        except Exception as e:
            logger.warning(f"CLOB PARSE ERROR: {e}")
            return None, None

    # Jetzt sicher als Liste behandeln
    if isinstance(clob_ids, list) and len(clob_ids) >= 2:
        up_token = str(clob_ids[0])
        down_token = str(clob_ids[1])
        return up_token, down_token

    return None, None

def append_jsonl(path: str, obj: dict) -> None:
    """Append JSON object to JSONL file."""
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"Failed to write to {path}: {e}")


def log_decision(
    request_id: str,
    slug: str,
    slot: int,
    action: str,
    signal: str,
    chosen_token: Optional[str],
    conf: int,
    regime: str,
    outcome: str,
    outcome_reason: str,
    market_quality_result=None,
    pattern_gate_result=None,
) -> None:
    """
    Log webhook decision to paper_decisions.jsonl for Phase-2 analysis.
    
    Called for EVERY webhook that passes slot check, regardless of whether
    trade is opened or rejected (e.g., no_entry_price, blocked by gate).
    """
    try:
        decision_record = {
            "timestamp": utc_now_iso(),
            "request_id": request_id,
            "slug": slug,
            "slot": slot,
            "action": action,
            "signal": signal,
            "chosen_token": chosen_token[:24] + "..." if chosen_token and len(chosen_token) > 24 else chosen_token,
            "confidence": conf,
            "session": calc_session(datetime.now(timezone.utc).hour),
            "regime": regime,
            
            # Outcome (opened, rejected, blocked)
            "outcome": outcome,
            "outcome_reason": outcome_reason,
            
            # Market Quality Gate results
            "mq_healthy": market_quality_result.is_healthy if market_quality_result else None,
            "mq_reason": market_quality_result.reason if market_quality_result else None,
            "mq_best_bid": market_quality_result.best_bid if market_quality_result else None,
            "mq_best_ask": market_quality_result.best_ask if market_quality_result else None,
            "mq_spread_pct": round(market_quality_result.spread_pct, 4) if market_quality_result and market_quality_result.spread_pct else None,
            
            # Pattern Gate results
            "pg_setup": pattern_gate_result.setup_type.value if pattern_gate_result else None,
            "pg_p": round(pattern_gate_result.pattern_probability, 4) if pattern_gate_result else None,
            "pg_implied": round(pattern_gate_result.implied_probability, 4) if pattern_gate_result and pattern_gate_result.implied_probability is not None else None,
            "pg_edge": round(pattern_gate_result.edge, 4) if pattern_gate_result else None,
            "pg_samples": pattern_gate_result.samples if pattern_gate_result else None,
            "pg_decision": "ALLOW" if (pattern_gate_result and pattern_gate_result.should_trade) else "BLOCK" if pattern_gate_result else None,
            "pg_reason": pattern_gate_result.reason if pattern_gate_result else None,
            
            # Edge validity (for filtering in analysis)
            "edge_valid": (pattern_gate_result is not None and pattern_gate_result.implied_probability is not None),
            "edge_invalid_reason": None if (pattern_gate_result is None or pattern_gate_result.implied_probability is not None) else "implied_unavailable",
        }
        append_jsonl("paper_decisions.jsonl", decision_record)
        logger.debug(f"[{request_id}] Decision logged: outcome={outcome}, reason={outcome_reason}")
    except Exception as e:
        logger.warning(f"[{request_id}] Failed to log decision: {e}")


def is_phase2_trade(trade: dict) -> bool:
    """
    Prüft ob ein Trade ein Phase-2 Trade ist.
    
    Kriterien:
    - source="tradingview" ODER mode!="test"
    - conf in {4,5} (rawConf oder confidence)
    - session != NY (oder NY mit botMove/mr)
    """
    # Prüfe source oder mode: Phase-2 nur wenn source="tradingview" ODER mode!="test"
    source = str(trade.get("source", "")).lower().strip()
    mode = str(trade.get("mode", "")).lower().strip()
    
    # Phase-2 Tagging: source="tradingview" ODER mode!="test"
    is_phase2_source = (source == "tradingview") or (mode != "" and mode != "test")
    
    if not is_phase2_source:
        return False
    
    # Prüfe confidence (rawConf hat Priorität, sonst confidence)
    conf = trade.get("rawConf") or trade.get("confidence")
    if conf is None:
        return False
    
    # Prüfe ob conf in {4,5}
    try:
        conf_int = int(conf)
        if conf_int not in [4, 5]:
            return False
    except (ValueError, TypeError):
        return False
    
    # Prüfe session (NY only allowed if botMove OR mr is true)
    session = str(trade.get("session", "")).upper()
    if session == "NY":
        # NY trades are Phase-2 only if botMove=true OR mr=true
        bot_move = trade.get("botMove") or trade.get("bot_move")
        mr_flag = trade.get("mr")
        # Parse boolean values
        bot_move_bool = parse_bool(bot_move) if bot_move is not None else False
        mr_bool = parse_bool(mr_flag) if mr_flag is not None else False
        # Block if both are false
        if not bot_move_bool and not mr_bool:
            return False
    
    return True


def is_trade_invalid(trade: dict) -> tuple[bool, Optional[str]]:
    """
    Check if a trade is invalid (e.g., missing entry_price or exit_price).
    
    A trade is invalid if:
    - entry_price is missing/None (cannot calculate PnL)
    - exit_price is missing/None for closed trades (cannot calculate PnL)
    
    Returns:
        (is_invalid: bool, invalid_reason: Optional[str])
    """
    # Check for missing entry_price
    entry_price = trade.get("entry_price") or trade.get("price")
    if entry_price is None:
        return True, "missing_entry_price"
    
    # Check if entry_price is explicitly None (not just missing)
    if entry_price == "None" or entry_price == "":
        return True, "missing_entry_price"
    
    # For closed trades, also check exit_price
    if trade.get("status") == "closed":
        exit_price = trade.get("exit_price")
        if exit_price is None:
            return True, "missing_exit_price"
        
        # Check if exit_price is explicitly None (not just missing)
        if exit_price == "None" or exit_price == "":
            return True, "missing_exit_price"
    
    return False, None


def check_go_no_go(
    orphan_trades_count: int,
    open_trades_file_count: int,
    open_trades_ram_count: int,
    phase2_trades_total: int,
    phase2_valid_closed_trades: int,
) -> dict:
    """
    Go/No-Go Regel (knallhart).
    
    NO-GO, solange eins davon zutrifft:
    1. orphan_trades_count > 0
    2. open_trades_ram_count << open_trades_file_count (deutlich weniger, z.B. ram < file * 0.8)
    3. valid_closed_trades == 0 nach 5 neuen Trades (phase2_trades_total >= 5 und valid_closed == 0)
    
    Returns:
        dict with:
            - go: bool (True = GO, False = NO-GO)
            - reasons: list[str] (Liste der NO-GO Gründe)
    """
    reasons = []
    go = True
    
    # Bedingung 1: orphan_trades_count > 0
    if orphan_trades_count > 0:
        go = False
        reasons.append(f"orphan_trades_count > 0 ({orphan_trades_count})")
    
    # Bedingung 2: open_trades_ram_count << open_trades_file_count
    # "Deutlich weniger" = ram < file * 0.8 (20% Diskrepanz)
    if open_trades_file_count > 0:
        threshold = open_trades_file_count * 0.8
        if open_trades_ram_count < threshold:
            go = False
            reasons.append(
                f"open_trades_ram_count ({open_trades_ram_count}) << open_trades_file_count ({open_trades_file_count}) "
                f"(threshold: {threshold:.1f})"
            )
    
    # Bedingung 3: valid_closed_trades == 0 nach 5 neuen Trades
    # WICHTIG: phase2_trades_total zählt alle Phase-2 Trades (inkl. invalid/test), 
    # aber wir prüfen nur valid_closed_trades für das Ziel
    if phase2_trades_total >= 5 and phase2_valid_closed_trades == 0:
        go = False
        reasons.append(
            f"valid_closed_trades == 0 nach {phase2_trades_total} neuen Trades "
            f"(mindestens 5 valide geschlossene Trades erwartet, aber keine gefunden - invalid/test werden ignoriert)"
        )
    
    return {
        "go": go,
        "reasons": reasons,
    }

def get_phase2_stats() -> dict:
    """Berechnet Phase-2 Statistiken (nur für aktuelle SESSION_ID)."""
    trades = []
    if Path(settings.PAPER_LOG_PATH).exists():
        with open(settings.PAPER_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    trades.append(trade)
                except json.JSONDecodeError:
                    continue
    
    # Filter by current SESSION_ID (only count trades from current session)
    current_session_id = settings.SESSION_ID
    if current_session_id:
        trades = [t for t in trades if t.get("session_id") == current_session_id]
        logger.debug(f"Phase-2 Stats: Filtering by SESSION_ID={current_session_id}, found {len(trades)} trades")
    else:
        logger.warning("Phase-2 Stats: No SESSION_ID set, counting all trades (legacy mode)")
    
    # Filter out test trades (mode="test" or smoke_test=True)
    # Phase-2 zählt nur echte Trades, keine Test-Trades
    non_test_trades = []
    for t in trades:
        mode = str(t.get("mode", "")).lower().strip()
        smoke_test = t.get("smoke_test", False)
        if mode != "test" and not smoke_test:
            non_test_trades.append(t)
    
    logger.debug(f"Phase-2 Stats: Filtered out {len(trades) - len(non_test_trades)} test trades, {len(non_test_trades)} non-test trades remaining")
    
    # Phase-2 Trades: source="tradingview" OR mode!="test" (already filtered above)
    phase2_trades = [t for t in non_test_trades if is_phase2_trade(t)]
    phase2_closed = [t for t in phase2_trades if t.get("status") == "closed"]
    
    # Separate valid and invalid trades
    valid_closed = []
    invalid_closed = []
    invalid_reasons = {}
    
    for trade in phase2_closed:
        is_invalid, invalid_reason = is_trade_invalid(trade)
        if is_invalid:
            invalid_closed.append(trade)
            if invalid_reason:
                invalid_reasons[invalid_reason] = invalid_reasons.get(invalid_reason, 0) + 1
        else:
            valid_closed.append(trade)
    
    # Berechne Winrate (nur für VALIDE Trades mit entry_price UND exit_price)
    # Ein Trade wird nur als WIN/LOSS/TIE klassifiziert, wenn beide Preise gesetzt sind
    valid_trades_with_prices = []
    for t in valid_closed:
        entry_price = t.get("entry_price") or t.get("price")
        exit_price = t.get("exit_price")
        # Nur Trades mit beiden Preisen zählen
        if entry_price is not None and exit_price is not None:
            # Prüfe, ob Preise gültig sind (nicht "None" String)
            if entry_price != "None" and entry_price != "" and exit_price != "None" and exit_price != "":
                valid_trades_with_prices.append(t)
    
    wins = sum(1 for t in valid_trades_with_prices if t.get("realized_pnl") is not None and t.get("realized_pnl", 0) > 0)
    losses = sum(1 for t in valid_trades_with_prices if t.get("realized_pnl") is not None and t.get("realized_pnl", 0) < 0)
    ties = sum(1 for t in valid_trades_with_prices if t.get("realized_pnl") is not None and t.get("realized_pnl", 0) == 0)
    total_valid_closed = len(valid_trades_with_prices)  # Nur Trades mit beiden Preisen
    winrate = (wins / total_valid_closed * 100) if total_valid_closed > 0 else 0.0
    
    # Exit Reasons (nur für VALIDE Trades mit beiden Preisen)
    exit_reasons = {}
    for trade in valid_trades_with_prices:
        reason = trade.get("exit_reason", "unknown")
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
    
    # Total PnL (nur für VALIDE Trades mit beiden Preisen, realized_pnl muss nicht None sein)
    total_pnl = sum(
        t.get("realized_pnl", 0) 
        for t in valid_trades_with_prices 
        if t.get("realized_pnl") is not None
    )
    
    # Active trades: calculate from total - closed (more accurate than PositionManager count)
    # PositionManager only has trades that are currently in RAM (rehydrated or recently created)
    # But we want to count ALL Phase-2 trades that are not closed, regardless of RAM status
    phase2_open_count = len(phase2_trades) - len(phase2_closed)
    
    # Phase-2 Ziel: Nur valid_closed_trades zählen (ignoriert invalid + test)
    # phase2_trades_total wird nur für interne Berechnungen verwendet (z.B. Go/No-Go)
    return {
        "phase2_trades_total": len(phase2_trades),  # Internal: total Phase-2 trades (for Go/No-Go checks)
        "phase2_closed_trades": len(phase2_closed),  # Internal: all closed Phase-2 trades
        "phase2_valid_closed_trades": total_valid_closed,  # ZIEL: Nur valide geschlossene Trades (ignoriert invalid + test)
        "phase2_invalid_closed_trades": len(invalid_closed),  # Invalid trades (missing entry_price or exit_price) - IGNORIERT
        "phase2_open_trades": phase2_open_count,
        "target": 20,  # Phase-2 Startregel: 20 valide closed trades
        "remaining": max(0, 20 - total_valid_closed),  # Based on valid trades only (with both prices)
        "progress_pct": round((total_valid_closed / 20 * 100) if 20 > 0 else 0.0, 2),
        "winrate": round(winrate, 2),  # Only for trades with both entry_price and exit_price
        "wins": wins,  # Only for trades with both prices
        "losses": losses,  # Only for trades with both prices
        "ties": ties,  # Only for trades with both prices (realized_pnl=0, not missing)
        "total_pnl": round(total_pnl, 2),  # Only for trades with both prices
        "exit_reasons": exit_reasons,  # Only for trades with both prices
        "invalid_trades_count": len(invalid_closed),
        "invalid_reasons": invalid_reasons,
    }


def _get_entry_price_for_trade(token_id: str) -> Optional[Dict[str, Any]]:
    """
    Get entry price for a trade from orderbook.
    
    PRICE DEFINITION (Paper Trading - REALISTIC EXECUTION):
    - For BUY orders: ALWAYS use best_ask (the price we must pay to buy)
    - NO MID PRICE - that's a fictional price that doesn't exist in the orderbook
    - NO FALLBACK to best_bid - if there are no sellers, we cannot buy!
    
    HARD RULE: Without best_ask, trade is REJECTED (not opened with fake price)
    
    RETRY LOGIC:
    - If orderbook is empty: retry 1x after 50ms
    - If still empty after retry: return None (trade will be skipped)
    
    Args:
        token_id: Token ID to fetch orderbook for
    
    Returns:
        Dict with:
            - entry_price: float (best_ask for BUY orders)
            - entry_method: str ("best_ask")
            - entry_ob_timestamp: str (ISO timestamp of orderbook fetch)
            - best_bid: Optional[float]
            - best_ask: Optional[float]
            - price_source: str ("orderbook")
            - retry_used: bool (whether retry was used)
        None if orderbook fetch fails or best_ask not available
    """
    if not token_id:
        logger.warning("_get_entry_price_for_trade: token_id is None")
        return None
    
    try:
        from agents.polymarket.polymarket import Polymarket
        from datetime import datetime, timezone
        import time as time_module
        
        if not hasattr(_get_entry_price_for_trade, '_polymarket'):
            _get_entry_price_for_trade._polymarket = Polymarket()
        
        # Timing for debugging
        fetch_start = time_module.monotonic()
        
        # Fetch full orderbook (not just price) - ATTEMPT 1
        orderbook = _get_entry_price_for_trade._polymarket.get_orderbook(token_id)
        fetch_time_ms = (time_module.monotonic() - fetch_start) * 1000
        
        # Log orderbook snapshot for debugging
        bids_count = len(orderbook.bids) if orderbook.bids else 0
        asks_count = len(orderbook.asks) if orderbook.asks else 0
        logger.debug(
            f"ENTRY PRICE FETCH (attempt 1): token_id={token_id[:16]}..., "
            f"bids={bids_count}, asks={asks_count}, fetch_time_ms={fetch_time_ms:.2f}"
        )
        
        # Extract best bid/ask from orderbook
        best_bid = None
        best_ask = None
        
        if orderbook.bids and len(orderbook.bids) > 0:
            best_bid = float(orderbook.bids[0].price)
        
        if orderbook.asks and len(orderbook.asks) > 0:
            best_ask = float(orderbook.asks[0].price)
        
        # Check if orderbook is empty (no bid and no ask)
        retry_used = False
        bids_count_retry = bids_count
        asks_count_retry = asks_count
        if best_bid is None and best_ask is None:
            # Orderbook is empty - RETRY 1x after 50ms
            logger.warning(
                f"ENTRY PRICE FETCH: Empty orderbook for token {token_id[:16]}... "
                f"(bids={bids_count}, asks={asks_count}). Retrying after 50ms..."
            )
            time_module.sleep(0.05)  # 50ms retry delay
            
            # RETRY ATTEMPT
            fetch_start_retry = time_module.monotonic()
            orderbook = _get_entry_price_for_trade._polymarket.get_orderbook(token_id)
            fetch_time_retry_ms = (time_module.monotonic() - fetch_start_retry) * 1000
            retry_used = True
            
            # Re-extract after retry
            best_bid = None
            best_ask = None
            
            if orderbook.bids and len(orderbook.bids) > 0:
                best_bid = float(orderbook.bids[0].price)
            
            if orderbook.asks and len(orderbook.asks) > 0:
                best_ask = float(orderbook.asks[0].price)
            
            bids_count_retry = len(orderbook.bids) if orderbook.bids else 0
            asks_count_retry = len(orderbook.asks) if orderbook.asks else 0
            
            logger.debug(
                f"ENTRY PRICE FETCH (retry): token_id={token_id[:16]}..., "
                f"bids={bids_count_retry}, asks={asks_count_retry}, fetch_time_ms={fetch_time_retry_ms:.2f}"
            )
        
        # HARD RULE: For BUY orders, we MUST have best_ask (the price we pay to buy)
        # NO MID PRICE - that's fictional and doesn't exist in orderbook
        # NO FALLBACK to best_bid - if there are no sellers, we cannot buy!
        # Gates are shadow mode, but EXECUTION is hard: no ask = no trade
        
        if best_ask is None:
            # No sellers = cannot buy = REJECT TRADE (even in shadow mode for gates)
            total_fetch_time_ms = (time_module.monotonic() - fetch_start) * 1000
            final_bids = bids_count_retry if retry_used else bids_count
            final_asks = asks_count_retry if retry_used else asks_count
            logger.error(
                f"ENTRY PRICE FETCH FAILED: No best_ask available for token {token_id[:16]}... "
                f"(bids={final_bids}, asks={final_asks}, retry_used={retry_used}, total_time_ms={total_fetch_time_ms:.2f}). "
                f"Cannot buy without sellers! Trade will be REJECTED. "
                f"(Gates may be shadow, but execution is hard - no fake prices)"
            )
            return None
        
        # Entry price = best_ask (realistic: this is what we'd actually pay)
        entry_price = best_ask
        entry_method = "best_ask"
        
        # Validate entry_price
        if entry_price is None or entry_price <= 0 or entry_price >= 1:
            total_fetch_time_ms = (time_module.monotonic() - fetch_start) * 1000
            logger.error(
                f"ENTRY PRICE FETCH FAILED: Invalid entry_price={entry_price} for token {token_id[:16]}... "
                f"(retry_used={retry_used}, total_time_ms={total_fetch_time_ms:.2f})"
            )
            return None
        
        # Get timestamp
        entry_ob_timestamp = datetime.now(timezone.utc).isoformat()
        total_fetch_time_ms = (time_module.monotonic() - fetch_start) * 1000
        
        logger.info(
            f"ENTRY PRICE FETCH SUCCESS: token_id={token_id[:16]}..., "
            f"entry_price={entry_price:.6f}, method={entry_method} (REALISTIC: best_ask for BUY), "
            f"best_bid={best_bid}, best_ask={best_ask}, "
            f"price_source=orderbook, retry_used={retry_used}, total_time_ms={total_fetch_time_ms:.2f}"
        )
        
        return {
            "entry_price": entry_price,
            "entry_method": entry_method,
            "entry_ob_timestamp": entry_ob_timestamp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "price_source": "orderbook",
            "retry_used": retry_used,
        }
        
    except Exception as e:
        logger.error(
            f"ENTRY PRICE FETCH EXCEPTION: Failed to fetch entry price from orderbook for token {token_id[:16]}...: {e}",
            exc_info=True
        )
        return None


def _get_exit_price_for_trade(trade) -> Optional[Dict[str, Any]]:
    """
    Get exit price for a trade - ALWAYS fetch fresh from orderbook.
    
    PRICE DEFINITION (Paper Trading - REALISTIC EXECUTION):
    - For SELL orders: ALWAYS use best_bid (the price we receive when selling)
    - NO MID PRICE - that's fictional and doesn't exist in orderbook
    - NO FALLBACK to entry_price - if there are no buyers, trade stays OPEN
    - IGNORE trade.current_price - it may contain fake/fallback values (0.5)
    
    HARD RULE: Without best_bid, return None (trade stays open, not closed with fake price)
    
    Args:
        trade: ActiveTrade object
    
    Returns:
        Dict with exit_price, exit_method, exit_best_bid, exit_best_ask
        or None if best_bid not available
    """
    from datetime import datetime, timezone
    
    # NOTE: We ALWAYS fetch from orderbook, ignoring trade.current_price
    # because current_price may contain fake fallback values (0.5, entry_price)
    # that would corrupt our PnL calculations.
    
    # Otherwise, fetch from orderbook - need best_bid for SELL
    if trade.token_id:
        try:
            from agents.polymarket.polymarket import Polymarket
            
            if not hasattr(_get_exit_price_for_trade, '_polymarket'):
                _get_exit_price_for_trade._polymarket = Polymarket()
            
            # Fetch full orderbook to get best_bid (price we'd receive when selling)
            orderbook = _get_exit_price_for_trade._polymarket.get_orderbook(trade.token_id)
            
            # Extract best bid (for SELL)
            best_bid = None
            best_ask = None
            
            if orderbook.bids and len(orderbook.bids) > 0:
                best_bid = float(orderbook.bids[0].price)
            
            if orderbook.asks and len(orderbook.asks) > 0:
                best_ask = float(orderbook.asks[0].price)
            
            exit_ob_timestamp = datetime.now(timezone.utc).isoformat()
            
            # HARD RULE: For SELL, we MUST have best_bid (the price we receive)
            # NO MID PRICE, NO FALLBACK
            if best_bid is None:
                logger.warning(
                    f"EXIT PRICE FETCH: No best_bid for trade {trade.trade_id}, "
                    f"token={trade.token_id[:16]}... - trade stays OPEN (no fake exit price). "
                    f"(best_ask={best_ask})"
                )
                return None
            
            exit_price = best_bid
            exit_method = "best_bid"
            
            logger.info(
                f"EXIT PRICE FETCH SUCCESS for trade {trade.trade_id}: "
                f"{exit_price:.6f} (method={exit_method}, REALISTIC: best_bid for SELL), "
                f"best_bid={best_bid}, best_ask={best_ask}, token={trade.token_id[:16]}..."
            )
            return {
                "exit_price": exit_price,
                "exit_method": exit_method,
                "exit_best_bid": best_bid,
                "exit_best_ask": best_ask,
                "exit_ob_timestamp": exit_ob_timestamp,
            }
            
        except Exception as e:
            logger.warning(
                f"EXIT PRICE FETCH EXCEPTION for trade {trade.trade_id}: {e}. "
                f"Trade stays OPEN (no fallback to entry_price)."
            )
            return None
    
    # No token_id = cannot fetch price
    logger.warning(
        f"EXIT PRICE FETCH: No token_id for trade {trade.trade_id}. "
        f"Trade stays OPEN (no fallback)."
    )
    return None


def _get_exit_price_only(trade) -> Optional[float]:
    """
    Wrapper for backward compatibility - returns only exit_price (float) or None.
    Use _get_exit_price_for_trade for full exit data including exit_method.
    """
    exit_data = _get_exit_price_for_trade(trade)
    if exit_data is None:
        return None
    return exit_data.get("exit_price")


def rehydrate_paper_trades() -> int:
    """
    Rehydrate active paper trades from paper_trades.jsonl on startup.
    
    Reads paper_trades.jsonl, finds trades with status != "closed".
    If FULL_REHYDRATE_ON_STARTUP=True, loads ALL open trades regardless of age.
    Otherwise, only loads trades within REHYDRATE_MAX_AGE_HOURS.
    
    Returns:
        Number of trades successfully rehydrated
    """
    global _rehydrated_trades_count, _rehydrate_errors
    
    if not is_paper_trading():
        logger.debug("Skipping rehydration (not in paper trading mode)")
        return 0
    
    log_path = settings.PAPER_LOG_PATH
    path = Path(log_path)
    
    if not path.exists():
        logger.debug(f"Paper log file not found: {log_path}, skipping rehydration")
        return 0
    
    try:
        from datetime import datetime, timezone, timedelta
        import time as time_module
        
        # Check if full rehydration is enabled
        full_rehydrate = settings.FULL_REHYDRATE_ON_STARTUP
        
        # Calculate cutoff time (only used if full_rehydrate=False)
        max_age_hours = settings.REHYDRATE_MAX_AGE_HOURS
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours) if not full_rehydrate else None
        
        # Read all trades from JSONL
        trades_by_id = {}  # trade_id -> latest record
        
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    trade_id = trade.get("trade_id")
                    if not trade_id:
                        continue
                    
                    # Keep only the latest record for each trade_id
                    if trade_id not in trades_by_id:
                        trades_by_id[trade_id] = trade
                    else:
                        # Compare timestamps to keep the latest
                        current_ts = trades_by_id[trade_id].get("utc_time") or trades_by_id[trade_id].get("ts_utc")
                        new_ts = trade.get("utc_time") or trade.get("ts_utc")
                        if new_ts and current_ts:
                            try:
                                # Parse ISO timestamps
                                current_dt = datetime.fromisoformat(str(current_ts).replace("Z", "+00:00"))
                                new_dt = datetime.fromisoformat(str(new_ts).replace("Z", "+00:00"))
                                if new_dt > current_dt:
                                    trades_by_id[trade_id] = trade
                            except (ValueError, AttributeError):
                                # If parsing fails, keep the new one
                                trades_by_id[trade_id] = trade
                        else:
                            # If no timestamp, keep the new one
                            trades_by_id[trade_id] = trade
                except json.JSONDecodeError:
                    continue
        
        # Filter active trades (status != "closed")
        # If full_rehydrate=True, load ALL open trades regardless of age
        # Otherwise, only load trades within max_age_hours
        active_trades = []
        for trade_id, trade in trades_by_id.items():
            # Skip closed trades
            if trade.get("status") == "closed":
                continue
            
            # If full rehydration is enabled, skip age check
            if full_rehydrate:
                active_trades.append(trade)
                continue
            
            # Otherwise, check age (must be within max_age_hours)
            trade_time_str = trade.get("utc_time") or trade.get("ts_utc")
            if not trade_time_str:
                # If no timestamp and not full rehydrate, skip (can't determine age)
                continue
            
            try:
                # Parse ISO timestamp
                trade_time = datetime.fromisoformat(str(trade_time_str).replace("Z", "+00:00"))
                if trade_time < cutoff_time:
                    # Trade is too old, skip
                    continue
                
                active_trades.append(trade)
            except (ValueError, AttributeError):
                # If parsing fails, skip
                continue
        
        # Register active trades into PositionManager
        pm = get_position_manager()
        rehydrated = 0
        
        # Count total open trades in file for verification
        total_open_in_file = len(active_trades)
        
        for trade in active_trades:
            try:
                trade_id = trade.get("trade_id")
                if not trade_id:
                    logger.warning(f"Rehydration skipped: missing trade_id")
                    _rehydrate_errors += 1
                    continue
                
                market_id = str(trade.get("market_id") or f"paper_{trade.get('slot', 'unknown')}")
                token_id = trade.get("token_id")
                side = trade.get("side", "UP")  # Default to UP if missing
                size = float(trade.get("size") or trade.get("size_usdc") or 2.0)
                
                # CRITICAL: Allow rehydration even without entry_price (will be marked as invalid later)
                entry_price_raw = trade.get("price") or trade.get("entry_price")
                if entry_price_raw is None or entry_price_raw == "None" or entry_price_raw == "":
                    # Use default price for rehydration (will be invalid, but trade will be in RAM)
                    entry_price = 0.5
                    logger.warning(f"Rehydrating trade {trade_id} WITHOUT entry_price (will be invalid)")
                else:
                    try:
                        entry_price = float(entry_price_raw)
                        if not (0 < entry_price < 1):
                            entry_price = 0.5
                            logger.warning(f"Rehydrating trade {trade_id} with invalid entry_price (will be invalid)")
                    except (ValueError, TypeError):
                        entry_price = 0.5
                        logger.warning(f"Rehydrating trade {trade_id} with unparseable entry_price (will be invalid)")
                
                leg1_entry_id = trade.get("leg1_entry_id") or trade.get("entry_id") or f"rehydrated_{trade_id}"
                
                # CRITICAL: Allow rehydration even without token_id (will be handled by orphan cleanup)
                if not token_id:
                    token_id = f"orphan_{trade_id}"  # Placeholder token_id
                    logger.warning(f"Rehydrating trade {trade_id} WITHOUT token_id (orphan, will be cleaned up)")
                
                # Convert side to UP/DOWN format if needed
                if side.upper() in ("BULL", "BUY", "UP"):
                    side = "UP"
                elif side.upper() in ("BEAR", "SELL", "DOWN"):
                    side = "DOWN"
                else:
                    # Try to infer from signal
                    signal = trade.get("signal", "").upper()
                    if signal == "BULL":
                        side = "UP"
                    elif signal == "BEAR":
                        side = "DOWN"
                    else:
                        logger.warning(f"Rehydration skipped for {trade_id}: unknown side '{side}'")
                        _rehydrate_errors += 1
                        continue
                
                # Check if market is already locked (might be from previous rehydration attempt)
                if market_id in pm.market_locks:
                    existing_trade_id = pm.market_locks[market_id]
                    if existing_trade_id != trade_id:
                        logger.warning(
                            f"Rehydration skipped for {trade_id}: market {market_id} already locked by {existing_trade_id}"
                        )
                        _rehydrate_errors += 1
                        continue
                
                # Create trade in PositionManager
                # Use existing trade_id if possible, otherwise PositionManager will generate one
                # For rehydration, we need to manually create the ActiveTrade object
                from agents.application.position_manager import ActiveTrade, TradeStatus
                
                # Parse trade creation time
                trade_time_str = trade.get("utc_time") or trade.get("ts_utc")
                if trade_time_str:
                    try:
                        trade_time = datetime.fromisoformat(str(trade_time_str).replace("Z", "+00:00"))
                        # Convert to monotonic time (approximate: use current monotonic - age)
                        now_monotonic = time_module.monotonic()
                        trade_age_seconds = (datetime.now(timezone.utc) - trade_time).total_seconds()
                        created_at_monotonic = now_monotonic - trade_age_seconds
                    except (ValueError, AttributeError):
                        created_at_monotonic = time_module.monotonic()
                else:
                    created_at_monotonic = time_module.monotonic()
                
                # Create ActiveTrade object
                active_trade = ActiveTrade(
                    trade_id=trade_id,
                    market_id=market_id,
                    token_id=token_id,
                    side=side,
                    leg1_size=size,
                    leg1_price=entry_price,
                    leg1_entry_id=leg1_entry_id,
                    created_at=created_at_monotonic,
                    created_at_utc=trade_time_str or utc_now_iso(),
                    status=TradeStatus.PENDING,  # Rehydrated trades start as PENDING
                    confirmation_timeout_seconds=9999,  # Very long timeout (same as new paper trades)
                    total_size=size,
                    entry_price=entry_price,
                )
                
                # Register in PositionManager
                pm.active_trades[trade_id] = active_trade
                pm.market_locks[market_id] = trade_id
                
                rehydrated += 1
                logger.debug(
                    f"Rehydrated trade {trade_id} (market={market_id}, side={side}, size={size}, price={entry_price:.4f})"
                )
                
            except Exception as e:
                logger.error(f"Error rehydrating trade {trade.get('trade_id', 'unknown')}: {e}")
                _rehydrate_errors += 1
                continue
        
        _rehydrated_trades_count = rehydrated
        rehydrate_mode = "FULL (all open trades)" if full_rehydrate else f"AGE-LIMITED (max {max_age_hours}h)"
        logger.info(f"REHYDRATE: loaded {rehydrated} active trades from paper_trades.jsonl ({rehydrate_mode})")
        
        # VERIFICATION: Log discrepancy if rehydrated != total_open_in_file
        if rehydrated != total_open_in_file:
            logger.warning(
                f"REHYDRATE VERIFICATION: Found {total_open_in_file} open trades in file, "
                f"but only {rehydrated} rehydrated. "
                f"Orphan count: {total_open_in_file - rehydrated}"
            )
        else:
            logger.info(f"REHYDRATE VERIFICATION: ✅ All {rehydrated} open trades successfully rehydrated")
        
        return rehydrated
        
    except Exception as e:
        logger.error(f"Error during rehydration: {e}")
        _rehydrate_errors += 1
        return 0


def get_spread_entry_from_trade_record(trade_id: str, log_path: str) -> Optional[float]:
    """
    Read spread_entry from trade record in paper_trades.jsonl.
    
    Args:
        trade_id: Trade ID to look up
        log_path: Path to paper_trades.jsonl file
    
    Returns:
        spread_entry value if found, None otherwise
    """
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    if trade.get("trade_id") == trade_id:
                        # Check if spread_entry is directly stored
                        spread_entry = trade.get("spread_entry")
                        if spread_entry is not None:
                            return float(spread_entry)
                        # Fallback: calculate from best_bid and best_ask
                        best_bid = trade.get("entry_best_bid")
                        best_ask = trade.get("entry_best_ask")
                        if best_bid is not None and best_ask is not None:
                            return float(best_ask) - float(best_bid)
                        return None
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
        return None
    except Exception as e:
        logger.debug(f"Failed to read spread_entry for trade {trade_id}: {e}")
        return None

def update_paper_trade_close(
    log_path: str,
    trade_id: str,
    realized_pnl: Optional[float],
    exit_price: float,
    exit_reason: str,
    exit_time_utc: str,
) -> bool:
    """
    Update paper_trades.jsonl with realized_pnl when trade closes.
    
    Searches for the trade entry by matching token_id + slot + utc_time,
    then appends a new entry with realized_pnl and status=closed.
    
    IMPORTANT: Checks for duplicate close entries to prevent writing multiple close events.
    
    Args:
        log_path: Path to paper_trades.jsonl
        trade_id: Trade ID (for logging)
        realized_pnl: Realized PnL
        exit_price: Exit price
        exit_reason: Exit reason
        exit_time_utc: Exit time (UTC ISO)
    
    Returns:
        True if update was written, False otherwise
    """
    try:
        path = Path(log_path)
        if not path.exists():
            logger.warning(f"Paper log file not found: {log_path}")
            return False
        
        # Check for existing close entry to prevent duplicates
        has_close_entry = False
        original_trade = None
        if path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trade = json.loads(line)
                        if trade.get("trade_id") == trade_id:
                            if trade.get("status") == "closed":
                                has_close_entry = True
                                logger.warning(
                                    f"Close entry already exists for trade {trade_id}. "
                                    f"Skipping duplicate close entry."
                                )
                            elif trade.get("status") != "closed":
                                original_trade = trade
                    except json.JSONDecodeError:
                        continue
        
        # If close entry already exists, don't write another one
        if has_close_entry:
            return False
        
        # Check if trade is invalid (missing entry_price or exit_price)
        is_invalid = False
        invalid_reason = None
        
        # Create a temporary trade dict to check validity (includes exit_price)
        temp_trade = original_trade.copy() if original_trade else {}
        temp_trade["status"] = "closed"
        temp_trade["exit_price"] = exit_price
        
        # Check validity of the complete trade (entry + exit)
        if original_trade:
            is_invalid, invalid_reason = is_trade_invalid(temp_trade)
            if is_invalid:
                # If invalid, set realized_pnl to None (not 0) to exclude from stats
                realized_pnl = None
                logger.warning(
                    f"Trade {trade_id} is invalid ({invalid_reason}). "
                    f"Setting realized_pnl=None (not 0) to exclude from stats. "
                    f"Trade will not be counted as WIN/LOSS/TIE."
                )
        
        # Append close entry (new line with realized_pnl + Phase-2 fields)
        close_entry = {
            "trade_id": trade_id,
            "realized_pnl": realized_pnl,  # Can be None if trade is invalid
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "exit_time_utc": exit_time_utc,
            "status": "closed",
        }
        
        # Add invalid_reason if trade is invalid
        if is_invalid and invalid_reason:
            close_entry["invalid_reason"] = invalid_reason
        
        # Copy Phase-2 relevant fields from original trade (including session_id and phase2_session_id)
        # Ensure close_entry always has trade_id and session_id
        if original_trade:
            # Copy session_id from original trade (REQUIRED)
            if "session_id" in original_trade:
                close_entry["session_id"] = original_trade["session_id"]
            else:
                # Fallback: use settings.SESSION_ID if not in original trade
                if settings.SESSION_ID:
                    close_entry["session_id"] = settings.SESSION_ID
                    logger.warning(f"Close entry: session_id missing in original trade, using settings.SESSION_ID={settings.SESSION_ID}")
            
            # Copy phase2_session_id if present in original trade
            if "phase2_session_id" in original_trade:
                close_entry["phase2_session_id"] = original_trade["phase2_session_id"]
            elif settings.PHASE2_SESSION_ID:
                # Check if this is a Phase-2 trade and add phase2_session_id
                source = str(original_trade.get("source", "")).lower().strip()
                mode = str(original_trade.get("mode", "")).lower().strip()
                is_phase2_source = (source == "tradingview") or (mode != "" and mode != "test")
                if is_phase2_source:
                    close_entry["phase2_session_id"] = settings.PHASE2_SESSION_ID
            
            # Copy signal_id and source from original trade (for tracking)
            if "signal_id" in original_trade:
                close_entry["signal_id"] = original_trade["signal_id"]
            if "source" in original_trade:
                close_entry["source"] = original_trade["source"]
            elif "source" not in close_entry:
                close_entry["source"] = "unknown"  # Default if missing
            
            # Copy entry_price for validation
            if "entry_price" in original_trade:
                close_entry["entry_price"] = original_trade["entry_price"]
            elif "price" in original_trade:
                close_entry["entry_price"] = original_trade["price"]
            
            if "rawConf" in original_trade:
                close_entry["rawConf"] = original_trade["rawConf"]
            if "confidence" in original_trade:
                close_entry["confidence"] = original_trade["confidence"]
            if "session" in original_trade:
                close_entry["session"] = original_trade["session"]
            # Copy botMove and mr fields for NY session Phase-2 detection
            if "botMove" in original_trade:
                close_entry["botMove"] = original_trade["botMove"]
            if "bot_move" in original_trade:
                close_entry["botMove"] = original_trade["bot_move"]
            if "mr" in original_trade:
                close_entry["mr"] = original_trade["mr"]
        else:
            # If no original_trade found, at least ensure session_id is set
            if settings.SESSION_ID:
                close_entry["session_id"] = settings.SESSION_ID
                logger.warning(f"Close entry: No original trade found for trade_id={trade_id}, using settings.SESSION_ID={settings.SESSION_ID}")
        
        append_jsonl(log_path, close_entry)
        pnl_str = f"{realized_pnl:.2f}" if realized_pnl is not None else "None (invalid)"
        logger.info(
            f"Paper trade close logged: trade_id={trade_id}, "
            f"realized_pnl={pnl_str}, reason={exit_reason}"
            + (f", invalid_reason={invalid_reason}" if is_invalid else "")
        )
        return True
    except Exception as e:
        logger.error(f"Failed to update paper trade close: {e}")
        return False

class WebhookPayload(BaseModel):
    signal: Optional[str] = None
    side: Optional[str] = None
    score: Optional[Union[float, str]] = None
    signal_id: Optional[str] = None  # TradingView signal ID for tracking
    source: Optional[str] = None  # Source of signal (e.g., "tradingview")
    mode: Optional[str] = None  # Mode (e.g., "test" or "live")
    confidence: Optional[Union[int, str]] = None
    rawConf: Optional[Union[int, str]] = None  # Raw confidence from TradingView (Phase 2: must be in {4,5})
    size: Optional[Union[float, str]] = None
    speedRatio: Optional[Union[float, str]] = None
    rt: Optional[Union[bool, str]] = False
    sw: Optional[Union[bool, str]] = False
    mr: Optional[Union[bool, str]] = False
    botMove: Optional[Union[bool, str]] = False
    regime: Optional[str] = None
    dislocation: Optional[Union[bool, str]] = False
    session: Optional[str] = None  # Session from TradingView (ASIA, LONDON, NY, OFF)


class ConfirmationPayload(BaseModel):
    """Payload for TradingView confirmation actions."""
    trade_id: str  # Required: trade_id from Fast Entry Engine
    action: str  # "ADD", "HEDGE", or "EXIT"
    action_id: Optional[str] = None  # Optional: for idempotency (auto-generated if missing)
    size: Optional[Union[float, str]] = None  # Required for ADD action (alias for additional_size)
    additional_size: Optional[Union[float, str]] = None  # Required for ADD action
    reason: Optional[str] = None  # Optional reason for action
    rawConf: Optional[Union[int, str]] = None  # Optional raw confidence
    botMove: Optional[Union[bool, str]] = None  # Optional botMove flag
    dislocation: Optional[Union[bool, str]] = None  # Optional dislocation flag

@app.post("/mark_run")
def mark_run():
    """
    Manually set a new run marker in the logs.
    Useful for marking the start of a new test phase or run.
    
    Returns:
        dict with run_id and timestamp
    """
    global _current_run_id
    _current_run_id = utc_now_iso()
    logger.info("=" * 60)
    logger.info(f"PHASE_2_START run_id={_current_run_id}")
    logger.info("=" * 60)
    return {
        "ok": True,
        "run_id": _current_run_id,
        "timestamp": _current_run_id,
        "message": f"Run marker set: {_current_run_id}"
    }

@app.get("/health/cis")
async def get_cis_health():
    """
    CIS Health Endpoint.
    
    Returns:
    - schema_ok: Whether trade schema is valid
    - drift_alert: Whether drift detection shows alerts
    - invalid_rate: Percentage of invalid trades
    - orphan_count: Number of orphan trades
    """
    try:
        from tools.research.schema import load_trades_from_jsonl, validate_trades
        from tools.research.drift import compute_drift
        from src.config.settings import get_settings
        
        settings = get_settings()
        
        # Load trades
        trades = load_trades_from_jsonl(settings.PAPER_LOG_PATH)
        
        # Validate schema
        valid_trades, invalid_trades = validate_trades(trades)
        schema_ok = len(invalid_trades) == 0
        invalid_rate = (len(invalid_trades) / len(trades) * 100.0) if trades else 0.0
        
        # Compute drift
        drift = compute_drift(valid_trades)
        drift_alert = drift.get("health_status") == "DRIFT_ALERT"
        
        # Get orphan count from risk metrics
        from agents.application.position_manager import TradeStatus
        pm = get_position_manager()
        open_trades_file_count = get_open_trades_file_count()
        open_trades_ram_count = len([
            t for t in pm.active_trades.values()
            if t.status in (
                TradeStatus.PENDING,
                TradeStatus.CONFIRMED,
                TradeStatus.ADDED,
                TradeStatus.HEDGED,
            )
            and not t.exited
        ])
        orphan_count = max(0, open_trades_file_count - open_trades_ram_count)
        
        return {
            "ok": True,
            "schema_ok": schema_ok,
            "drift_alert": drift_alert,
            "invalid_rate": round(invalid_rate, 2),
            "orphan_count": orphan_count,
            "summary": {
                "total_trades": len(trades),
                "valid_trades": len(valid_trades),
                "invalid_trades": len(invalid_trades),
                "drift_status": drift.get("health_status", "UNKNOWN"),
                "critical_alerts": drift.get("critical_alerts_count", 0) if drift.get("has_drift_data") else 0,
            }
        }
    except Exception as e:
        logger.error(f"Error computing CIS health: {e}")
        return {
            "ok": False,
            "error": str(e),
            "schema_ok": False,
            "drift_alert": False,
            "invalid_rate": 0.0,
            "orphan_count": 0,
        }


@app.get("/health")
def health():
    """Health check endpoint with version info."""
    health_status = "ok"
    orphan_info = {}
    
    # Check for orphan trades (only in paper mode)
    if is_paper_trading():
        open_trades_file_count = get_open_trades_file_count()
        pm = get_position_manager()
        from agents.application.position_manager import TradeStatus
        open_trades_ram_count = len([
            t for t in pm.active_trades.values()
            if t.status in (
                TradeStatus.PENDING,
                TradeStatus.CONFIRMED,
                TradeStatus.ADDED,
                TradeStatus.HEDGED,
            )
            and not t.exited
        ])
        orphan_trades_count = max(0, open_trades_file_count - open_trades_ram_count)
        
        if orphan_trades_count > 0:
            health_status = "DEGRADED"
            orphan_info = {
                "open_trades_file_count": open_trades_file_count,
                "open_trades_ram_count": open_trades_ram_count,
                "orphan_trades_count": orphan_trades_count,
            }
    
    return {
        "status": health_status,
        "mode": get_trading_mode_str(),
        "version": settings.APP_VERSION,
        "current_run_id": _current_run_id,
        "auto_close": {
            "enabled": settings.AUTO_CLOSE_ENABLED,
            "ttl_minutes": settings.AUTO_CLOSE_TTL_MINUTES,
            "on_market_end": settings.AUTO_CLOSE_ON_MARKET_END,
            "price_poll_interval": settings.AUTO_CLOSE_PRICE_POLL_INTERVAL,
        },
        "orphan_info": orphan_info if orphan_info else None,
    }

def get_open_trades_file_count() -> int:
    """Count open trades in paper_trades.jsonl file."""
    try:
        log_path = settings.PAPER_LOG_PATH
        path = Path(log_path)
        if not path.exists():
            return 0

        # Track latest status per trade_id (last entry wins)
        status_by_id = {}
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    trade_id = trade.get("trade_id")
                    status = trade.get("status")
                    if trade_id:
                        status_by_id[trade_id] = status
                except json.JSONDecodeError:
                    continue

        open_trade_ids = {
            trade_id
            for trade_id, status in status_by_id.items()
            if status != "closed"
        }
        return len(open_trade_ids)
    except Exception as e:
        logger.warning(f"Failed to count open trades in file: {e}")
        return 0


def cleanup_orphan_paper_trades() -> int:
    """Close paper trades that exist only in file (not in RAM)."""
    if not is_paper_trading():
        return 0
    try:
        log_path = settings.PAPER_LOG_PATH
        path = Path(log_path)
        if not path.exists():
            return 0

        # Build latest entry per trade_id to find open trades
        latest_by_id = {}
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                except json.JSONDecodeError:
                    continue
                trade_id = trade.get("trade_id")
                if not trade_id:
                    continue
                latest_by_id[trade_id] = trade

        # Active trades in RAM
        pm = get_position_manager()
        from agents.application.position_manager import TradeStatus
        active_ids = set(
            t.trade_id
            for t in pm.active_trades.values()
            if t.status in (
                TradeStatus.PENDING,
                TradeStatus.CONFIRMED,
                TradeStatus.ADDED,
                TradeStatus.HEDGED,
            )
            and not t.exited
        )

        closed_count = 0
        for trade_id, trade in latest_by_id.items():
            status = trade.get("status")
            if status == "closed":
                continue
            if trade_id in active_ids:
                continue
            entry_price = trade.get("entry_price")
            if entry_price is None:
                logger.warning(
                    f"ORPHAN FILE CLEANUP: Trade {trade_id} missing entry_price; cannot close safely."
                )
                continue
            if update_paper_trade_close(
                log_path=log_path,
                trade_id=trade_id,
                realized_pnl=None,
                exit_price=float(entry_price),
                exit_reason="orphan_file_cleanup",
                exit_time_utc=utc_now_iso(),
            ):
                closed_count += 1

        if closed_count > 0:
            logger.info(f"ORPHAN FILE CLEANUP: Closed {closed_count} orphan file trades")
        return closed_count
    except Exception as e:
        logger.warning(f"ORPHAN FILE CLEANUP: failed ({e})")
        return 0

@app.get("/metrics/risk")
async def get_risk_metrics():
    """
    Risk management and trade metrics endpoint.
    
    Returns:
    - Trade statistics (wins, losses, win rate, expectancy)
    - Equity curve data
    - Max drawdown
    - Sample size per confidence bucket
    - Current exposure
    - Orphan trade tracking (open_trades_file_count, open_trades_ram_count, orphan_trades_count)
    - Health status (DEGRADED if orphan_trades_count > 0)
    """
    try:
        rm = get_risk_manager()
        mt = get_metrics_tracker()
        pm = get_position_manager()
        
        # Get statistics
        stats = mt.get_statistics()
        sample_report = mt.get_sample_size_report()
        
        # Get current exposure
        from agents.application.position_manager import TradeStatus
        total_pnl = pm.get_total_pnl()
        current_exposure = sum(
            t.total_size for t in pm.active_trades.values()
            if t.status in (
                TradeStatus.PENDING,
                TradeStatus.CONFIRMED,
                TradeStatus.ADDED,
                TradeStatus.HEDGED,
            )
        )
        
        # Orphan tracking (only for paper trading)
        open_trades_file_count = 0
        open_trades_ram_count = 0
        orphan_trades_count = 0
        health_status = "ok"
        
        if is_paper_trading():
            open_trades_file_count = get_open_trades_file_count()
            open_trades_ram_count = len([
                t for t in pm.active_trades.values()
                if t.status in (
                    TradeStatus.PENDING,
                    TradeStatus.CONFIRMED,
                    TradeStatus.ADDED,
                    TradeStatus.HEDGED,
                )
                and not t.exited
            ])
            orphan_trades_count = max(0, open_trades_file_count - open_trades_ram_count)
            
            if orphan_trades_count > 0:
                health_status = "DEGRADED"
        
        # Get trading mode info
        trading_info = get_trading_mode_info()
        
        # Build response with all required fields
        response = {
            "mode": get_trading_mode_str(),  # Legacy field
            "trading_mode_requested": trading_info["trading_mode_requested"],
            "trading_mode_effective": trading_info["trading_mode_effective"],
            "allow_live": trading_info["allow_live"],
            "token_set": trading_info["token_set"],
            "kill_switch_enabled": trading_info["kill_switch_enabled"],
            "live_allowed_now": trading_info["live_allowed_now"],
            "timestamp_utc": utc_now_iso(),
            "equity": {
                "initial": rm.initial_equity,
                "current": rm.current_equity,
                "unrealized_pnl": total_pnl.get("unrealized_pnl", 0.0),
                "realized_pnl": total_pnl.get("realized_pnl", 0.0),
            },
            "exposure": {
                "current": current_exposure,
                "peak": mt.exposure_peak,
                "max_allowed": rm.current_equity * rm.max_exposure_pct,
                "max_pct": rm.max_exposure_pct * 100,
            },
            # Required fields at top level
            "total_trades": stats.get("total_trades", 0),
            "wins": stats.get("wins", 0),
            "losses": stats.get("losses", 0),
            "winrate": stats.get("win_rate", 0.0),
            "expectancy": stats.get("expectancy", 0.0),
            "avg_win": stats.get("avg_win", 0.0),
            "avg_loss": stats.get("avg_loss", 0.0),
            "profit_factor": stats.get("profit_factor", 0.0),
            "max_drawdown": stats.get("max_drawdown", 0.0),
            "current_drawdown": stats.get("current_drawdown", 0.0),
            "exposure_current": current_exposure,
            "exposure_peak": mt.exposure_peak,
            "time_in_trade_avg": stats.get("avg_time_in_trade_seconds", 0.0),
            "time_in_trade_p90": stats.get("time_in_trade_p90_seconds", 0.0),
            # MAE/MFE for Soft-Stop validation
            "avg_mae": stats.get("avg_mae", 0.0),  # Average Maximum Adverse Excursion
            "worst_mae": stats.get("worst_mae", 0.0),  # Worst MAE across all trades
            "avg_mfe": stats.get("avg_mfe", 0.0),  # Average Maximum Favorable Excursion
            "best_mfe": stats.get("best_mfe", 0.0),  # Best MFE across all trades
            # Spread statistics (for liquidity analysis)
            "avg_spread_at_entry": stats.get("avg_spread_at_entry", 0.0),  # Average spread at entry
            "spread_p90": stats.get("spread_p90", 0.0),  # 90th percentile spread
            "spread_max": stats.get("spread_max", 0.0),  # Maximum spread observed
            "n_spread_samples": stats.get("n_spread_samples", 0),  # Number of trades with valid spread data
            # Additional statistics
            "statistics": stats,
            "sample_size_report": sample_report,
            # Orphan tracking
            "open_trades_file_count": open_trades_file_count,
            "open_trades_ram_count": open_trades_ram_count,
            "orphan_trades_count": orphan_trades_count,
            "health_status": health_status,
            # Signal ID Deduplication
            "signal_dedupe": signal_dedupe_info,
        }
        
        return response
    except Exception as e:
        logger.exception(f"Error getting risk metrics: {e}")
        return {
            "error": str(e),
            "mode": get_trading_mode_str(),
        }

@app.get("/phase2/status")
async def get_phase2_status():
    """
    Get Phase-2 progress status.
    
    Phase-2 Trade = (source="tradingview" OR mode!="test") AND conf in {4,5} AND (session != NY OR (session == NY AND (botMove == true OR mr == true)))
    Phase-2 CLOSED Trade = Phase-2 Trade + status="closed"
    
    Phase-2 Startregel: 20 VALIDE CLOSED Trades
    - Zählt nur: valid_closed_trades (entry_price + exit_price gesetzt, realized_pnl != None)
    - Ignoriert: invalid Trades (fehlende Preise)
    - Ignoriert: test Trades (mode="test" oder smoke_test=True)
    - Confirm-Alerts: OFF
    - Spread-Gates: AUS (nur messen)
    
    Note: NY trades are allowed only if botMove=true OR mr=true (mirrors Pine Script logic)
    
    Go/No-Go Regel (knallhart):
    NO-GO, solange eins davon zutrifft:
    1. orphan_trades_count > 0
    2. open_trades_ram_count << open_trades_file_count (deutlich weniger)
    3. valid_closed_trades == 0 nach 5 neuen Trades
    """
    stats = get_phase2_stats()
    
    # Get orphan tracking data for Go/No-Go check
    orphan_trades_count = 0
    open_trades_file_count = 0
    open_trades_ram_count = 0
    
    if is_paper_trading():
        open_trades_file_count = get_open_trades_file_count()
        pm = get_position_manager()
        from agents.application.position_manager import TradeStatus
        open_trades_ram_count = len([
            t for t in pm.active_trades.values()
            if t.status in (
                TradeStatus.PENDING,
                TradeStatus.CONFIRMED,
                TradeStatus.ADDED,
                TradeStatus.HEDGED,
            )
            and not t.exited
        ])
        orphan_trades_count = max(0, open_trades_file_count - open_trades_ram_count)
    
    # Check Go/No-Go (knallhart)
    go_no_go_check = check_go_no_go(
        orphan_trades_count=orphan_trades_count,
        open_trades_file_count=open_trades_file_count,
        open_trades_ram_count=open_trades_ram_count,
        phase2_trades_total=stats["phase2_trades_total"],
        phase2_valid_closed_trades=stats["phase2_valid_closed_trades"],
    )
    
    return {
        "ok": True,
        "definition": {
            "conf_range": [4, 5],
            "ny_session_rule": "NY trades allowed only if botMove=true OR mr=true",
            "blocked_sessions": "NY (only when botMove=false AND mr=false)",
            "target_valid_closed_trades": 20,  # Phase-2 Startregel: 20 VALIDE CLOSED Trades (ignoriert invalid + test)
            "filters": {
                "ignores_invalid": True,  # Trades ohne entry_price/exit_price werden ignoriert
                "ignores_test": True,  # Trades mit mode='test' oder smoke_test=True werden ignoriert
            },
        },
        "stats": stats,
        "go_no_go": {
            "go": go_no_go_check["go"],
            "no_go_reasons": go_no_go_check["reasons"],
            "target_reached": stats["phase2_valid_closed_trades"] >= 20,  # Phase-2 Startregel: 20 valide CLOSED Trades
            "winrate_ok": stats["winrate"] >= 60.0 if stats["phase2_valid_closed_trades"] > 0 else None,
            "ready_for_live": (
                go_no_go_check["go"] and
                stats["phase2_valid_closed_trades"] >= 20 and  # Phase-2 Startregel: 20 valide CLOSED Trades
                (stats["winrate"] >= 60.0 if stats["phase2_valid_closed_trades"] > 0 else False)
            ),
            # Legacy fields (for backward compatibility)
            "target_reached_legacy": stats["phase2_valid_closed_trades"] >= 20,
            "winrate_ok_legacy": stats["winrate"] >= 60.0 if stats["phase2_valid_closed_trades"] > 0 else None,
        },
        "orphan_tracking": {
            "open_trades_file_count": open_trades_file_count,
            "open_trades_ram_count": open_trades_ram_count,
            "orphan_trades_count": orphan_trades_count,
        },
        "target": {
            "description": "20 valide CLOSED Trades (Phase-2 Startregel, ignoriert invalid + test)",
            "current": stats["phase2_valid_closed_trades"],
            "target": 20,
            "progress_pct": (stats["phase2_valid_closed_trades"] / 20 * 100) if stats["phase2_valid_closed_trades"] > 0 else 0.0,
            "remaining": max(0, 20 - stats["phase2_valid_closed_trades"]),
        },
    }


@app.get("/phase2/metrics")
async def get_phase2_metrics():
    """
    Get Phase-2 metrics for analysis after reaching 20 valid closed trades.
    
    Returns the key metrics needed to evaluate:
    - Edge bei realistischen Spreads
    - Soft-Stop zu eng/zu weit
    - Exit zu früh (MFE ≫ realized)
    
    Required metrics:
    - expectancy
    - profit_factor
    - max_drawdown
    - avg_mae / worst_mae
    - avg_mfe / best_mfe
    - time_in_trade_avg
    - avg_spread_at_entry + spread_p90
    """
    # Get Phase-2 stats
    phase2_stats = get_phase2_stats()
    valid_closed_count = phase2_stats["phase2_valid_closed_trades"]
    
    # Get risk metrics (includes all the metrics we need)
    rm = get_risk_manager()
    mt = get_metrics_tracker()
    stats = mt.get_statistics()
    
    # Check if we have enough trades
    if valid_closed_count < 20:
        return {
            "ok": True,
            "ready": False,
            "message": f"Not enough valid closed trades yet. Need 20, have {valid_closed_count}",
            "current": valid_closed_count,
            "target": 20,
            "remaining": max(0, 20 - valid_closed_count),
        }
    
    # Return the required metrics
    return {
        "ok": True,
        "ready": True,
        "message": f"Phase-2 metrics ready ({valid_closed_count} valid closed trades)",
        "phase2_stats": {
            "valid_closed_trades": valid_closed_count,
            "winrate": phase2_stats.get("winrate", 0.0),
            "wins": phase2_stats.get("wins", 0),
            "losses": phase2_stats.get("losses", 0),
            "ties": phase2_stats.get("ties", 0),
            "total_pnl": phase2_stats.get("total_pnl", 0.0),
        },
        "metrics": {
            # Core performance metrics
            "expectancy": stats.get("expectancy", 0.0),
            "profit_factor": stats.get("profit_factor", 0.0),
            "max_drawdown": stats.get("max_drawdown", 0.0),
            "max_drawdown_pct": stats.get("max_drawdown_pct", 0.0),
            
            # MAE/MFE (for Soft-Stop validation)
            "avg_mae": stats.get("avg_mae", 0.0),
            "worst_mae": stats.get("worst_mae", 0.0),
            "avg_mfe": stats.get("avg_mfe", 0.0),
            "best_mfe": stats.get("best_mfe", 0.0),
            
            # Time in trade
            "time_in_trade_avg": stats.get("avg_time_in_trade_seconds", 0.0),
            "time_in_trade_p90": stats.get("time_in_trade_p90_seconds", 0.0),
            
            # Spread metrics (for liquidity analysis)
            "avg_spread_at_entry": stats.get("avg_spread_at_entry", 0.0),
            "spread_p90": stats.get("spread_p90", 0.0),
            "spread_max": stats.get("spread_max", 0.0),
            "n_spread_samples": stats.get("n_spread_samples", 0),
        },
        "analysis_notes": {
            "edge_vs_spread": "Compare expectancy vs avg_spread_at_entry to see if edge holds at realistic spreads",
            "soft_stop_validation": "Compare avg_mae vs worst_mae. If worst_mae << SOFT_STOP_ADVERSE_MOVE, stop might be too tight",
            "exit_timing": "Compare avg_mfe vs realized_pnl. If MFE >> realized, exits might be too early",
        },
    }


@app.get("/metrics")
async def get_metrics():
    """
    Performance metrics endpoint.
    
    Returns:
    - Latency rolling stats (p50/p90/p99)
    - Trade counts
    - Confirm request stats
    - Uptime
    """
    try:
        metrics = {
            "mode": get_trading_mode_str(),
            "timestamp_utc": utc_now_iso(),
        }
        
        # Uptime
        if _server_start_time:
            metrics["uptime_seconds"] = round(time.time() - _server_start_time, 2)
        else:
            metrics["uptime_seconds"] = 0.0
        
        # Latency stats from Fast Entry Engine
        if fast_entry_engine and fast_entry_engine.latency_stats:
            latency_stats = fast_entry_engine.latency_stats.get_stats()
            metrics["latency"] = {
                "detect_to_send_ms": {
                    "p50": round(latency_stats["detect_to_send"]["p50"], 3),
                    "p90": round(latency_stats["detect_to_send"]["p90"], 3),
                    "p99": round(latency_stats["detect_to_send"]["p99"], 3),
                    "count": latency_stats["detect_to_send"]["count"],
                },
                "detect_to_ack_ms": {
                    "p50": round(latency_stats["detect_to_ack"]["p50"], 3),
                    "p90": round(latency_stats["detect_to_ack"]["p90"], 3),
                    "p99": round(latency_stats["detect_to_ack"]["p99"], 3),
                    "count": latency_stats["detect_to_ack"]["count"],
                },
            }
        else:
            metrics["latency"] = None
        
        # Position Manager stats
        pm = get_position_manager()
        
        # Calculate total_trades = count(unique OPEN events) from paper_trades.jsonl
        # This counts unique trade_ids that have an OPEN event (status != "closed")
        total_trades_unique_open = 0
        if is_paper_trading() and Path(settings.PAPER_LOG_PATH).exists():
            try:
                open_trade_ids = set()
                with open(settings.PAPER_LOG_PATH, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            trade = json.loads(line)
                            trade_id = trade.get("trade_id")
                            status = trade.get("status")
                            if trade_id and status != "closed":
                                open_trade_ids.add(trade_id)
                        except json.JSONDecodeError:
                            continue
                total_trades_unique_open = len(open_trade_ids)
            except Exception as e:
                logger.warning(f"Failed to calculate total_trades from paper_trades.jsonl: {e}")
        
        if pm:
            pm_stats = pm.get_stats()
            metrics["trades"] = {
                "total_trades": total_trades_unique_open if total_trades_unique_open > 0 else pm_stats.get("total_trades", 0),
                "active_trades": pm_stats.get("pending_trades", 0) + pm_stats.get("confirmed_trades", 0),
                "pending_trades": pm_stats.get("pending_trades", 0),
                "confirmed_trades": pm_stats.get("confirmed_trades", 0),
                "active_trades_count": len(pm.active_trades),  # Count from PositionManager
                "rehydrated_trades_count": _rehydrated_trades_count,
                "rehydrate_errors": _rehydrate_errors,
            }
        else:
            metrics["trades"] = {
                "total_trades": total_trades_unique_open,
                "active_trades": 0,
                "pending_trades": 0,
                "confirmed_trades": 0,
                "active_trades_count": 0,
                "rehydrated_trades_count": _rehydrated_trades_count,
                "rehydrate_errors": _rehydrate_errors,
            }
        
        # Confirm request stats
        metrics["confirms"] = {
            "total_requests": _confirm_requests_total,
            "conflicts_409": _confirm_requests_409,
            "success_rate": round(
                (1.0 - (_confirm_requests_409 / max(_confirm_requests_total, 1))) * 100, 2
            ) if _confirm_requests_total > 0 else 100.0,
        }
        
        # Queue depth / pending tasks (if available)
        # For now, we don't have a queue, but we can track active async tasks
        metrics["queue"] = {
            "pending_tasks": 0,  # Placeholder - could be enhanced with asyncio.all_tasks()
        }
        
        # Signal ID Deduplication metrics
        metrics["signal_dedupe"] = {
            "duplicate_signals_count": _duplicate_signals_count,
            "cache_size": len(_signal_id_cache),
            "cache_ttl_seconds": _signal_id_cache_ttl_seconds,
        }
        
        # Phase 2 Block Counters
        metrics["phase2_blocks"] = {
            "blocked_conf_high": _blocked_conf_high,
            "blocked_conf_low": _blocked_conf_low,
            "blocked_session_ny": _blocked_session_ny,  # Legacy (backward compatibility)
            "blocked_ny_no_botmove": _blocked_ny_no_botmove,  # NY blocked: botMove=false AND mr=false
            "blocked_conf_missing": _blocked_conf_missing,
        }
        
        return metrics
        
    except Exception as e:
        logger.exception(f"Error getting metrics: {e}")
        return {
            "error": str(e),
            "mode": get_trading_mode_str(),
        }

@app.get("/state")
async def get_state():
    """
    Get current system state.
    
    Returns:
    - Current market info
    - Active positions
    - Active trade IDs
    - PnL (dry run)
    """
    try:
        # Get trading mode info
        trading_info = get_trading_mode_info()
        
        state = {
            "mode": get_trading_mode_str(),  # Legacy field
            "trading_mode_requested": trading_info["trading_mode_requested"],
            "trading_mode_effective": trading_info["trading_mode_effective"],
            "allow_live": trading_info["allow_live"],
            "token_set": trading_info["token_set"],
            "kill_switch_enabled": trading_info["kill_switch_enabled"],
            "live_allowed_now": trading_info["live_allowed_now"],
            "timestamp_utc": utc_now_iso(),
        }
        
        # Fast Entry Engine state
        if fast_entry_engine:
            engine_stats = fast_entry_engine.get_stats()
            latency_stats = fast_entry_engine.latency_stats.get_stats()
            state["fast_entry_engine"] = {
                "running": fast_entry_engine.running,
                "stats": engine_stats,
                "latency_stats": latency_stats,
            }
        
        # Position Manager state
        pm = get_position_manager()
        if pm:
            pm_stats = pm.get_stats()
            active_trades = pm.get_active_trades_summary()
            total_pnl = pm.get_total_pnl()
            
            state["positions"] = {
                "active_trades": active_trades,
                "stats": pm_stats,
                "pnl": total_pnl,
            }
            
            # Current market (from latest active trade)
            if active_trades:
                latest_trade = active_trades[0]  # Most recent
                state["current_market"] = {
                    "market_id": latest_trade["market_id"],
                    "token_id": latest_trade["token_id"],
                    "side": latest_trade["side"],
                    "active_trade_id": latest_trade["trade_id"],
                }
            else:
                state["current_market"] = None
        
        # Current slot (for TradingView webhook)
        now = int(time.time())
        slot = current_slot_start(now)
        slug = slug_for_slot(slot)
        
        state["current_slot"] = {
            "slot": slot,
            "slug": slug,
            "timestamp": now,
        }
        
        # Try to fetch current market info
        try:
            market = fetch_market_by_slug(slug)
            if market:
                state["current_market_info"] = {
                    "market_id": market.get("id"),
                    "question": market.get("question"),
                    "slug": slug,
                }
        except Exception as e:
            logger.debug(f"Could not fetch market info: {e}")
        
        return state
        
    except Exception as e:
        logger.exception(f"Error getting state: {e}")
        return {
            "error": str(e),
            "mode": get_trading_mode_str(),
        }

@app.post("/test")
def test():
    return {"ok": True, "test": "simple endpoint works"}

@app.post("/test/create-trade")
async def test_create_trade():
    """Test endpoint: Create a test trade to verify trade_id generation."""
    pm = get_position_manager()
    
    # Create test trade
    market_id = "test_market_1167913"
    token_id = "test_token_82710658332224486667246780380481172258208863214975713792863851174574620922214"
    
    trade = pm.create_trade(
        market_id=market_id,
        token_id=token_id,
        side="UP",
        leg1_size=1.0,
        leg1_price=0.523456,
        leg1_entry_id=f"test_entry_{int(time.time() * 1000)}",
        timeout_seconds=settings.CONFIRM_TTL_SECONDS,  # Use timeout from settings
    )
    
    if trade:
        return {
            "ok": True,
            "trade_id": trade.trade_id,
            "market_id": trade.market_id,
            "status": trade.status.value,
            "side": trade.side,
            "size": trade.total_size,
            "timeout_seconds": trade.confirmation_timeout_seconds,
            "message": "Test trade created successfully",
        }
    else:
        return {
            "ok": False,
            "error": "Trade creation failed",
            "message": "Market may already be locked",
        }

@app.post("/test/cleanup-timeouts")
async def test_cleanup_timeouts():
    """Test endpoint: Manually trigger timeout cleanup."""
    pm = get_position_manager()
    cleaned = pm.cleanup_timeout_trades()
    return {
        "ok": True,
        "cleaned": cleaned,
        "message": f"Cleaned up {cleaned} timed out trades",
    }

@app.post("/test/create-trade-short-timeout")
async def test_create_trade_short_timeout():
    """Test endpoint: Create a test trade with short timeout (10s) for testing cleanup."""
    pm = get_position_manager()
    
    # Create test trade with explicit 10s timeout
    market_id = "test_market_1167913"
    token_id = "test_token_82710658332224486667246780380481172258208863214975713792863851174574620922214"
    
    trade = pm.create_trade(
        market_id=market_id,
        token_id=token_id,
        side="UP",
        leg1_size=1.0,
        leg1_price=0.523456,
        leg1_entry_id=f"test_entry_{int(time.time() * 1000)}",
        timeout_seconds=10,  # Explicit 10s timeout for testing
    )
    
    if trade:
        return {
            "ok": True,
            "trade_id": trade.trade_id,
            "market_id": trade.market_id,
            "status": trade.status.value,
            "side": trade.side,
            "size": trade.total_size,
            "timeout_seconds": trade.confirmation_timeout_seconds,
            "message": "Test trade created with 10s timeout",
        }
    else:
        return {
            "ok": False,
            "error": "Trade creation failed",
            "message": "Market may already be locked",
        }

# ─────────────────────────────────────────────
# SMOKE TEST ENDPOINTS (Paper Trading Only)
# ─────────────────────────────────────────────

class SmokeTradePayload(BaseModel):
    """Payload for smoke trade test."""
    side: str  # "YES" or "NO"
    shares: float = 1.0
    hold_seconds: int = 5

@app.post("/debug/smoke_trade")
async def smoke_trade(payload: SmokeTradePayload):
    """
    Paper Smoke Test: Execute a single trade (open, wait, close).
    
    Only available in PAPER mode.
    
    Body:
        - side: "YES" or "NO"
        - shares: float (default: 1.0)
        - hold_seconds: int (default: 5)
    
    Returns:
        - trade_id
        - entry_price
        - exit_price
        - realized_pnl_raw
        - valid: bool (true if both prices are set)
    """
    if not is_paper_trading():
        raise HTTPException(
            status_code=403,
            detail="Smoke tests are only available in PAPER mode"
        )
    
    try:
        import asyncio
        
        # Normalize side
        side_upper = payload.side.upper().strip()
        if side_upper not in ("YES", "NO"):
            raise HTTPException(
                status_code=400,
                detail=f"side must be 'YES' or 'NO', got: {payload.side}"
            )
        
        # Get current market (current slot)
        now = int(time.time())
        slot = current_slot_start(now)
        slug = slug_for_slot(slot)
        market = fetch_market_by_slug(slug)
        
        # Fallback: Use test tokens if no market found (for smoke testing)
        # Also use test tokens if market exists but token resolution fails
        # ALWAYS use test tokens for smoke tests to avoid orderbook dependency issues
        use_test_tokens = True  # Always use test tokens for smoke tests
        logger.info(f"Smoke test: Using test tokens (bypassing real market/orderbook)")
        
        if use_test_tokens:
            # Use test token IDs (these are known test tokens)
            up_token = "82710658332224486667246780380481172258208863214975713792863851174574620922214"
            down_token = "82710658332224486667246780380481172258208863214975713792863851174574620922215"
            market_id = f"smoke_test_{slot}"
        else:
            # Resolve token IDs from real market
            up_token, down_token = resolve_up_down_tokens(market)
            if not up_token or not down_token:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to resolve token IDs from market"
                )
            market_id = str(market.get("id", f"smoke_{slot}"))
        
        # Choose token based on side
        token_id = up_token if side_upper == "YES" else down_token
        side = "UP" if side_upper == "YES" else "DOWN"
        
        # Step 1: Get entry_price via orderbook (or use fallback for test tokens)
        if use_test_tokens:
            # For test tokens, use fallback price (orderbook might be empty)
            logger.info(f"Smoke test: Using test tokens, entry_price=0.5 (fallback)")
            entry_price = 0.5
            entry_price_data = {
                "entry_price": 0.5,
                "entry_method": "test_fallback",
                "entry_ob_timestamp": utc_now_iso(),
                "best_bid": 0.49,
                "best_ask": 0.51,
                "price_source": "test_fallback",
                "retry_used": False,
            }
        else:
            # Try to fetch from real orderbook
            entry_price_data = _get_entry_price_for_trade(token_id)
            if not entry_price_data or entry_price_data.get("entry_price") is None:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to fetch entry_price from orderbook"
                )
            entry_price = entry_price_data.get("entry_price")
        
        # Step 2: Open trade (entry_price must be set)
        pm = get_position_manager()
        trade = pm.create_trade(
            market_id=market_id,
            token_id=token_id,
            side=side,
            leg1_size=payload.shares,
            leg1_price=entry_price,
            leg1_entry_id=f"smoke_{int(time.time() * 1000)}",
            timeout_seconds=9999,  # Very long timeout (we'll close manually)
        )
        
        if not trade:
            raise HTTPException(
                status_code=500,
                detail="Failed to create trade (market may be locked)"
            )
        
        # Log trade to paper_trades.jsonl (with session_id and trade_id)
        trade_record = {
            "trade_id": trade.trade_id,
            "utc_time": utc_now_iso(),
            "session_id": settings.SESSION_ID,
            "token_id": token_id,
            "market_id": market_id,
            "side": side,
            "size": payload.shares,
            "entry_price": entry_price,
            "price": entry_price,  # Legacy field
            "entry_method": entry_price_data.get("entry_method"),
            "entry_ob_timestamp": entry_price_data.get("entry_ob_timestamp"),
            "entry_best_bid": entry_price_data.get("best_bid"),
            "entry_best_ask": entry_price_data.get("best_ask"),
            "signal": "BULL" if side == "UP" else "BEAR",
            "confidence": 5,  # Default for smoke test
            "rawConf": 5,
            "smoke_test": True,
            "mode": "test",  # Smoke tests are test mode (not Phase-2)
            "signal_id": None,  # Smoke tests don't have signal_id
            "source": "unknown",  # Smoke tests default source
        }
        append_jsonl(settings.PAPER_LOG_PATH, trade_record)
        
        # Step 3: Wait hold_seconds
        await asyncio.sleep(payload.hold_seconds)
        
        # Step 4: Get exit_price via orderbook
        if use_test_tokens:
            # For test tokens, use slightly different exit price to simulate movement
            # Use entry_price + small random variation (for testing)
            import random
            price_variation = random.uniform(-0.02, 0.02)  # ±2c variation
            exit_price = max(0.01, min(0.99, entry_price + price_variation))
            logger.info(f"Smoke test: Using test exit_price={exit_price:.6f} (entry={entry_price:.6f} + variation={price_variation:.6f})")
        else:
            exit_price = _get_exit_price_only(trade)
            if exit_price is None:
                # Fallback: use entry_price if exit_price fetch fails
                exit_price = entry_price
                logger.warning(f"Smoke test: Failed to fetch exit_price, using entry_price as fallback")
        
        # Step 5: Close trade
        exit_result = pm.exit_trade(
            trade_id=trade.trade_id,
            exit_price=exit_price,
            exit_reason="smoke_test",
            exit_request_id=f"smoke_{trade.trade_id}_{int(time.time() * 1000)}",
        )
        
        if not exit_result.get("ok"):
            raise HTTPException(
                status_code=500,
                detail=f"Failed to close trade: {exit_result.get('error', 'unknown')}"
            )
        
        realized_pnl = exit_result.get("realized_pnl", 0.0)
        
        # Update paper_trades.jsonl with close entry
        update_paper_trade_close(
            log_path=settings.PAPER_LOG_PATH,
            trade_id=trade.trade_id,
            realized_pnl=realized_pnl,
            exit_price=exit_price,
            exit_reason="smoke_test",
            exit_time_utc=utc_now_iso(),
        )
        
        # Check if trade is valid (both prices set)
        is_valid = (
            entry_price is not None and
            exit_price is not None and
            entry_price != "None" and
            exit_price != "None" and
            entry_price != "" and
            exit_price != ""
        )
        
        # Get MAE/MFE from trade object (if available)
        mae = None
        mfe = None
        if hasattr(trade, 'mae') and trade.mae is not None:
            mae = trade.mae
        if hasattr(trade, 'mfe') and trade.mfe is not None:
            mfe = trade.mfe
        
        return {
            "ok": True,
            "trade_id": trade.trade_id,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "realized_pnl_raw": realized_pnl,
            "valid": is_valid,
            "side": side,
            "shares": payload.shares,
            "hold_seconds": payload.hold_seconds,
            "mae": mae,
            "mfe": mfe,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Smoke trade error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Smoke trade failed: {str(e)}"
        )

@app.post("/debug/smoke_run")
async def smoke_run(count: int = 5):
    """
    Paper Smoke Test: Execute multiple trades (alternating YES/NO).
    
    Only available in PAPER mode.
    
    Query params:
        - count: int (default: 5) - Number of trades to execute
    
    Returns:
        Summary with:
        - valid_closed: int
        - invalid_closed: int
        - avg_pnl: float
        - avg_mae: float
        - avg_mfe: float
    """
    if not is_paper_trading():
        raise HTTPException(
            status_code=403,
            detail="Smoke tests are only available in PAPER mode"
        )
    
    if count < 1 or count > 20:
        raise HTTPException(
            status_code=400,
            detail="count must be between 1 and 20"
        )
    
    try:
        results = []
        sides = ["YES", "NO"]
        
        for i in range(count):
            side = sides[i % 2]  # Alternate YES/NO
            
            # Execute smoke trade
            payload = SmokeTradePayload(
                side=side,
                shares=1.0,
                hold_seconds=5,
            )
            
            result = await smoke_trade(payload)
            results.append(result)
            
            # Small delay between trades
            if i < count - 1:
                await asyncio.sleep(1)
        
        # Calculate summary
        valid_results = [r for r in results if r.get("valid", False)]
        invalid_results = [r for r in results if not r.get("valid", False)]
        
        # Get MAE/MFE and PnL from closed trades
        mae_values = []
        mfe_values = []
        pnl_values = []
        
        # Extract MAE/MFE and PnL from results
        for result in results:
            pnl = result.get("realized_pnl_raw")
            if pnl is not None:
                pnl_values.append(pnl)
            
            mae = result.get("mae")
            if mae is not None:
                mae_values.append(mae)
            
            mfe = result.get("mfe")
            if mfe is not None:
                mfe_values.append(mfe)
        
        # Calculate averages
        avg_pnl = sum(pnl_values) / len(pnl_values) if pnl_values else 0.0
        avg_mae = sum(mae_values) / len(mae_values) if mae_values else 0.0
        avg_mfe = sum(mfe_values) / len(mfe_values) if mfe_values else 0.0
        
        return {
            "ok": True,
            "total_trades": count,
            "valid_closed": len(valid_results),
            "invalid_closed": len(invalid_results),
            "avg_pnl": round(avg_pnl, 4),
            "avg_mae": round(avg_mae, 4),
            "avg_mfe": round(avg_mfe, 4),
            "results": results,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Smoke run error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Smoke run failed: {str(e)}"
        )

@app.post("/confirm")
async def confirm(payload: ConfirmationPayload):
    """
    TradingView Confirmation Endpoint.
    
    Handles ADD, HEDGE, or EXIT actions for Fast Entry Engine trades.
    
    Requires:
    - trade_id: From Fast Entry Engine Leg 1 entry
    - action: "ADD", "HEDGE", or "EXIT"
    - action_id: Optional, for idempotency (auto-generated if missing)
    - additional_size: Required for ADD action
    
    Note: This endpoint is fully async and non-blocking. State persistence is debounced.
    """
    global _confirm_requests_total, _confirm_requests_409
    _confirm_requests_total += 1
    
    request_id = str(uuid.uuid4())[:8]
    
    try:
        pm = get_position_manager()
        
        # Generate action_id if not provided
        action_id = payload.action_id or f"{payload.trade_id}_{payload.action}_{request_id}"
        
        # Parse action
        action_upper = payload.action.upper().strip()
        if action_upper not in ("ADD", "HEDGE", "EXIT"):
            return {
                "ok": False,
                "error": "INVALID_ACTION",
                "message": f"Action must be ADD, HEDGE, or EXIT, got: {payload.action}",
            }
        
        # Parse additional_size for ADD (support both 'size' and 'additional_size')
        additional_size = None
        if action_upper == "ADD":
            size_value = payload.size or payload.additional_size
            if size_value is None:
                return {
                    "ok": False,
                    "error": "MISSING_SIZE",
                    "message": "ADD action requires 'size' or 'additional_size'",
                }
            additional_size = parse_float(size_value, 0.0)
            if additional_size <= 0:
                return {
                    "ok": False,
                    "error": "INVALID_SIZE",
                    "message": f"size must be > 0, got: {additional_size}",
                }
        
        # Parse optional fields
        reason = payload.reason
        raw_conf = parse_int(payload.rawConf, 0) if payload.rawConf else None
        bot_move = parse_bool(payload.botMove) if payload.botMove is not None else None
        dislocation = parse_bool(payload.dislocation) if payload.dislocation is not None else None
        
        # Import TradeAction
        from agents.application.position_manager import TradeAction
        
        action_enum = TradeAction[action_upper]
        
        # Process confirmation
        result = pm.process_confirmation(
            trade_id=payload.trade_id,
            action=action_enum,
            action_id=action_id,
            additional_size=additional_size,
        )
        
        # Log with optional fields
        log_data = {
            "action": action_upper,
            "size": additional_size if action_upper == "ADD" else 0,
        }
        if payload.trade_id:
            log_data["trade_id"] = payload.trade_id
        if result.get('status'):
            log_data["status"] = result['status']
        if reason:
            log_data["reason"] = reason
        if raw_conf:
            log_data["rawConf"] = raw_conf
        if bot_move is not None:
            log_data["botMove"] = bot_move
        if dislocation is not None:
            log_data["dislocation"] = dislocation
        
        logger.info(f"[{request_id}] CONFIRMATION: {json.dumps(log_data)}")
        
        # Execute action if not already handled
        if result["ok"] and not result.get("already_handled", False):
            if fast_entry_engine:
                if action_upper == "ADD":
                    success = fast_entry_engine.add_size_by_trade_id(
                        trade_id=payload.trade_id,
                        additional_size_usdc=additional_size,
                    )
                    if not success:
                        result["execution_error"] = "Failed to add size"
                
                elif action_upper == "HEDGE":
                    success = fast_entry_engine.hedge_by_trade_id(
                        trade_id=payload.trade_id,
                    )
                    if not success:
                        result["execution_error"] = "Failed to hedge"
                
                elif action_upper == "EXIT":
                    success = fast_entry_engine.exit_by_trade_id(
                        trade_id=payload.trade_id,
                    )
                    if not success:
                        result["execution_error"] = "Failed to exit"
        
        # Return 409 if already handled, 200 otherwise
        if result.get("already_handled", False):
            _confirm_requests_409 += 1
            from fastapi import status
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=result
            )
        
        return result
        
    except HTTPException:
        # Re-raise HTTPException (for 409 Conflict)
        raise
    except Exception as e:
        logger.exception(f"[{request_id}] CONFIRMATION ERROR: {e}")
        return {
            "ok": False,
            "error": str(e),
            "message": f"Confirmation processing failed: {e}",
        }

async def signal_id_cache_cleanup_task():
    """Background task to clean up expired signal_id cache entries."""
    while True:
        try:
            await asyncio.sleep(60)  # Run every minute
            current_time = time.time()
            expired_ids = [
                signal_id for signal_id, timestamp in _signal_id_cache.items()
                if current_time - timestamp > _signal_id_cache_ttl_seconds
            ]
            for signal_id in expired_ids:
                del _signal_id_cache[signal_id]
            if expired_ids:
                logger.debug(f"Signal ID cache cleanup: removed {len(expired_ids)} expired entries")
        except Exception as e:
            logger.error(f"Error in signal_id_cache_cleanup_task: {e}")


def _hash_payload(payload_dict: dict) -> str:
    """Generate hash from payload for fallback signal_id."""
    # Create a stable hash from sorted payload items
    payload_str = json.dumps(payload_dict, sort_keys=True)
    return hashlib.md5(payload_str.encode()).hexdigest()[:16]


def _check_signal_id_duplicate(signal_id: str, signal: str, request_id: str) -> tuple[bool, str]:
    """
    Check if signal_id is a duplicate.
    
    IMPORTANT: signal_id must not collide between BULL & BEAR.
    Cache key = signal_id + signal (e.g., "alert_123-BULL" vs "alert_123-BEAR")
    
    Args:
        signal_id: TradingView signal ID
        signal: Signal type ("BULL" or "BEAR")
        request_id: Request ID for logging
    
    Returns:
        (is_duplicate: bool, decision: str)
    """
    global _duplicate_signals_count, _signal_id_cache
    
    if not signal_id or signal_id == "N/A":
        return False, "no_signal_id"
    
    # Normalize signal to BULL/BEAR
    signal_upper = str(signal).upper().strip()
    if signal_upper not in ("BULL", "BEAR"):
        # If signal is not BULL/BEAR yet, we can't create a proper cache key
        # This should not happen if called after signal normalization, but handle gracefully
        logger.warning(f"[{request_id}] Invalid signal type for dedupe: {signal_upper}, skipping dedupe check")
        return False, "invalid_signal"
    
    # Create composite cache key: signal_id + signal type
    # This prevents collision between BULL and BEAR signals with same signal_id
    # Example: "alert_123-BULL" vs "alert_123-BEAR" are different cache keys
    cache_key = f"{signal_id}-{signal_upper}"
    
    current_time = time.time()
    
    # Check if cache_key exists in cache
    if cache_key in _signal_id_cache:
        cache_age = current_time - _signal_id_cache[cache_key]
        if cache_age < _signal_id_cache_ttl_seconds:
            # Duplicate found within TTL
            _duplicate_signals_count += 1
            logger.info(
                f"[{request_id}] DUPLICATE SIGNAL: signal_id={signal_id}, signal={signal_upper}, cache_key={cache_key} "
                f"(age={cache_age:.1f}s, TTL={_signal_id_cache_ttl_seconds}s) - SKIPPED"
            )
            return True, "duplicate"
        else:
            # Expired entry, remove it
            del _signal_id_cache[cache_key]
    
    # Add to cache (new or refreshed)
    _signal_id_cache[cache_key] = current_time
    logger.info(
        f"[{request_id}] SIGNAL ACCEPTED: signal_id={signal_id}, signal={signal_upper}, cache_key={cache_key} "
        f"(cached, TTL={_signal_id_cache_ttl_seconds}s)"
    )
    return False, "accepted"


@app.post("/webhook")
def webhook(payload: WebhookPayload):
    """Main webhook endpoint for TradingView alerts."""
    request_id = str(uuid.uuid4())[:8]
    
    try:
        global last_slot, _duplicate_signals_count
        
        # ─────────────────────────────────────────────
        # DEDUPLICATION CHECK: Must be FIRST (before any side effects)
        # ─────────────────────────────────────────────
        signal_id = payload.signal_id
        
        # Extract signal early for dedupe check (need BULL/BEAR to prevent collision)
        # Parse signal from payload (minimal parsing, just for dedupe)
        sig_raw = payload.signal or payload.side or ""
        sig_for_dedupe = normalize_signal(sig_raw)
        
        # Deduplication check (only if signal_id is present)
        # IMPORTANT: Cache key = signal_id + signal (BULL/BEAR) to prevent collision
        # This MUST run before any other operations (Risk Manager, Position Open, etc.)
        if signal_id:
            # Only check dedupe if signal is valid (BULL or BEAR)
            if sig_for_dedupe in ("BULL", "BEAR"):
                is_duplicate, decision = _check_signal_id_duplicate(signal_id, sig_for_dedupe, request_id)
                if is_duplicate:
                    logger.info(f"[{request_id}] SIGNAL DEDUPE: signal_id={signal_id}, signal={sig_for_dedupe} - SKIPPED (duplicate) - BEFORE any side effects")
                    return {
                        "status": "skipped",
                        "reason": "duplicate_signal",
                        "signal_id": signal_id,
                        "signal": sig_for_dedupe,
                        "message": f"Signal ID {signal_id} with signal {sig_for_dedupe} already processed within TTL ({_signal_id_cache_ttl_seconds}s)",
                    }
                else:
                    logger.info(f"[{request_id}] SIGNAL DEDUPE: signal_id={signal_id}, signal={sig_for_dedupe} - ACCEPTED")
            else:
                logger.warning(f"[{request_id}] SIGNAL DEDUPE: signal_id={signal_id} but invalid signal={sig_for_dedupe}, skipping dedupe check")
        else:
            logger.info(f"[{request_id}] SIGNAL DEDUPE: no signal_id - ACCEPTED (no dedupe check)")
        
        # Now safe to proceed with payload processing
        data = payload.model_dump()
        
        # Extract fields for logging and persistence
        # These will be persisted in trade record
        signal_id_for_persistence = payload.signal_id  # Can be None
        source_for_persistence = payload.source or "unknown"  # Default "unknown"
        mode = payload.mode or "unknown"
        
        # Fallback: hash payload if signal_id is missing (only for logging)
        signal_id_for_logging = signal_id_for_persistence
        if not signal_id_for_logging:
            payload_hash = _hash_payload(data)
            signal_id_for_logging = f"hash_{payload_hash}"
            logger.debug(
                f"[{request_id}] signal_id missing, using hash fallback: {signal_id_for_logging} "
                f"(for logging only, trade will be processed)"
            )
        
        logger.info(f"[{request_id}] RAW PAYLOAD: {data}")
        is_test_signal = False
        test_prefix = getattr(settings, "TEST_SIGNAL_PREFIX", "test_") or "test_"
        if isinstance(signal_id_for_logging, str) and signal_id_for_logging.startswith(test_prefix):
            is_test_signal = True

        signal_kind = "TEST" if is_test_signal else "LIVE"
        logger.info(
            f"[{request_id}] SIGNAL_ID: {signal_id_for_logging} | SOURCE: {source_for_persistence} | "
            f"MODE: {mode} | KIND: {signal_kind} (TradingView signal tracking)"
        )

        # Robustes Parsing und Normalisierung
        # Note: sig_for_dedupe was already parsed above for dedupe check
        sig = sig_for_dedupe  # Reuse already normalized signal
        
        conf = parse_int(payload.confidence, 0)
        score = parse_float(payload.score, 0.0)
        size = parse_float(payload.size, settings.PAPER_USDC)
        speed_ratio = parse_float(payload.speedRatio, 0.0)
        
        rt = parse_bool(payload.rt)
        sw = parse_bool(payload.sw)
        mr = parse_bool(payload.mr)
        bot_move = parse_bool(payload.botMove)
        dislocation = parse_bool(payload.dislocation)
        
        regime = str(payload.regime or "UNKNOWN").upper().strip()
        if regime not in ("TREND", "RANGE", "NEUTRAL"):
            regime = "UNKNOWN"
        
        # ─────────────────────────────────────────────
        # PHASE 2 GATING: rawConf-based filtering
        # ─────────────────────────────────────────────
        
        # Parse rawConf (Phase 2: primary filter)
        raw_conf = parse_int(payload.rawConf, None)
        
        # Handle missing rawConf (backward compatibility)
        if raw_conf is None:
            global _blocked_conf_missing
            if settings.REQUIRE_RAWCONF:
                _blocked_conf_missing += 1
                logger.info(f"[{request_id}] BLOCKED: rawConf missing (REQUIRE_RAWCONF=True)")
                return {
                    "status": "blocked",
                    "reason": "rawConf_missing",
                    "message": "rawConf is required but missing in payload",
                    "mode": get_trading_mode_str(),
                }
            elif settings.MISSING_RAWCONF_ACTION == "default_to_5":
                raw_conf = 5
                logger.info(f"[{request_id}] rawConf missing, defaulting to 5")
            else:
                _blocked_conf_missing += 1
                logger.info(f"[{request_id}] BLOCKED: rawConf missing (MISSING_RAWCONF_ACTION=block)")
                return {
                    "status": "blocked",
                    "reason": "rawConf_missing",
                    "message": "rawConf is missing and MISSING_RAWCONF_ACTION=block",
                    "mode": get_trading_mode_str(),
                }
        
        # PHASE 2: Block rawConf < MIN_CONFIDENCE (rawConf < 4)
        if raw_conf < settings.MIN_CONFIDENCE:
            global _blocked_conf_low
            _blocked_conf_low += 1
            logger.info(f"[{request_id}] BLOCKED: rawConf={raw_conf} < MIN_CONFIDENCE={settings.MIN_CONFIDENCE}")
            return {
                "status": "blocked",
                "reason": "rawConf_low",
                "rawConf": raw_conf,
                "min_confidence": settings.MIN_CONFIDENCE,
                "message": f"rawConf {raw_conf} is below minimum {settings.MIN_CONFIDENCE}",
                "mode": get_trading_mode_str(),
            }
        
        # PHASE 2: Block rawConf > MAX_CONFIDENCE (rawConf >= 6)
        if raw_conf > settings.MAX_CONFIDENCE:
            global _blocked_conf_high
            _blocked_conf_high += 1
            logger.info(f"[{request_id}] BLOCKED: rawConf={raw_conf} > MAX_CONFIDENCE={settings.MAX_CONFIDENCE}")
            return {
                "status": "blocked",
                "reason": "rawConf_high",
                "rawConf": raw_conf,
                "max_confidence": settings.MAX_CONFIDENCE,
                "message": f"rawConf {raw_conf} exceeds maximum {settings.MAX_CONFIDENCE} (Phase 2: only {settings.MIN_CONFIDENCE}-{settings.MAX_CONFIDENCE} allowed)",
                "mode": get_trading_mode_str(),
            }
        
        # PHASE 2: Session Filter (NY only allowed if botMove OR mr is true)
        # Pine Script logic: if session == NY and botMove == false and mr == false → block
        # Otherwise → allow
        # Verwende Session aus Payload, falls vorhanden, sonst berechne
        session_from_payload = str(payload.session or "").upper().strip()
        if session_from_payload in ("ASIA", "LONDON", "NY", "OFF"):
            session = session_from_payload
        else:
            # Fallback: Berechne Session aus UTC-Zeit
            now_utc = datetime.now(timezone.utc)
            session = calc_session(now_utc.hour)
        
        # Parse botMove and mr flags (already parsed above, but ensure they're available)
        bot_move = parse_bool(payload.botMove)
        mr_flag = parse_bool(payload.mr)
        
        # NY Session Filter: Block NY only if botMove == false AND mr == false
        # IF session == "NY" AND botMove == false AND mr == false THEN block trade
        if session == "NY":
            if not bot_move and not mr_flag:
                # Block: NY session without botMove or mr
                global _blocked_session_ny, _blocked_ny_no_botmove
                _blocked_session_ny += 1  # Legacy counter (backward compatibility)
                _blocked_ny_no_botmove += 1  # New specific counter
                logger.info(
                    f"[{request_id}] BLOCKED: NY session without botMove or mr "
                    f"(botMove={bot_move}, mr={mr_flag})"
                )
                return {
                    "status": "blocked",
                    "reason": "ny_block_no_botmove",
                    "session": session,
                    "botMove": bot_move,
                    "mr": mr_flag,
                    "message": f"NY session blocked: botMove={bot_move} and mr={mr_flag} (NY trades require botMove=true OR mr=true)",
                    "mode": get_trading_mode_str(),
                }
            else:
                # Allow: NY session with botMove=true OR mr=true
                logger.info(
                    f"[{request_id}] ALLOWED: NY session with botMove={bot_move} or mr={mr_flag}"
                )
        
        # PHASE 2: Dislocation is logged but NOT gated (REQUIRE_DISLOCATION=False)
        if settings.REQUIRE_DISLOCATION and not dislocation:
            logger.info(f"[{request_id}] BLOCKED: Dislocation required but not present")
            return {
                "status": "blocked",
                "reason": "dislocation_required",
                "dislocation": dislocation,
                "message": "Dislocation is required but not present",
                "mode": get_trading_mode_str(),
            }
        else:
            # Log dislocation but don't gate
            if dislocation:
                logger.info(f"[{request_id}] Dislocation present (logged, not gated)")
            else:
                logger.info(f"[{request_id}] Dislocation not present (logged, not gated)")
        
        # ─────────────────────────────────────────────
        # SAFETY: Orphan Cleanup Check
        # Block new opens if orphan trades exist (health degraded)
        # ─────────────────────────────────────────────
        if is_paper_trading():
            open_trades_file_count = get_open_trades_file_count()
            pm = get_position_manager()
            from agents.application.position_manager import TradeStatus
            open_trades_ram_count = len([
                t for t in pm.active_trades.values()
                if t.status in (
                    TradeStatus.PENDING,
                    TradeStatus.CONFIRMED,
                    TradeStatus.ADDED,
                    TradeStatus.HEDGED,
                )
                and not t.exited
            ])
            orphan_trades_count = max(0, open_trades_file_count - open_trades_ram_count)
            
            if orphan_trades_count > 0 and settings.ORPHAN_CLEANUP_ENABLED:
                cleaned = cleanup_orphan_paper_trades()
                if cleaned > 0:
                    open_trades_file_count = get_open_trades_file_count()
                    open_trades_ram_count = len([
                        t for t in pm.active_trades.values()
                        if t.status in (
                            TradeStatus.PENDING,
                            TradeStatus.CONFIRMED,
                            TradeStatus.ADDED,
                            TradeStatus.HEDGED,
                        )
                        and not t.exited
                    ])
                    orphan_trades_count = max(0, open_trades_file_count - open_trades_ram_count)

            if orphan_trades_count > 0:
                logger.warning(
                    f"[{request_id}] BLOCKED: Health degraded - {orphan_trades_count} orphan trades detected "
                    f"(file: {open_trades_file_count}, RAM: {open_trades_ram_count}). "
                    f"New opens blocked until cleanup completes."
                )
                return {
                    "status": "blocked",
                    "reason": "health_degraded_orphans",
                    "orphan_trades_count": orphan_trades_count,
                    "open_trades_file_count": open_trades_file_count,
                    "open_trades_ram_count": open_trades_ram_count,
                    "message": f"Health degraded: {orphan_trades_count} orphan trades. New opens blocked until cleanup completes.",
                    "mode": get_trading_mode_str(),
                }

        if sig not in ("BULL", "BEAR"):
            logger.warning(f"[{request_id}] BAD_SIGNAL: {sig}")
            mode_str = get_trading_mode_str()
            return {"ok": True, "ignored": True, "reason": "BAD_SIGNAL", "received": sig, "mode": mode_str}
        
        # Legacy confidence filter (for backward compatibility, but rawConf is primary)
        if conf > 0 and conf < settings.MIN_CONFIDENCE:
            logger.info(f"[{request_id}] IGNORED: LOW_CONFIDENCE {conf} (legacy check)")
            return {
                "ok": True,
                "ignored": True,
                "reason": "LOW_CONFIDENCE",
                "min_confidence": settings.MIN_CONFIDENCE,
                "confidence": conf,
                "mode": "DRY_RUN" if settings.DRY_RUN else "LIVE"
            }
        
        # Note: conf>=4 is now allowed by default (ALLOW_CONF_4=True in settings)
        
        now = int(time.time())
        slot = current_slot_start(now)

        if last_slot == slot:
            logger.info(f"[{request_id}] SLOT ALREADY USED: {slot}")
            return {
                "ok": True,
                "ignored": True,
                "reason": "SLOT_ALREADY_USED",
                "slot": slot,
                "mode": "DRY_RUN" if settings.DRY_RUN else "LIVE"
            }

        last_slot = slot

        slug = slug_for_slot(slot)
        try:
            market = fetch_market_by_slug(slug)
        except APIError:
            # Bei API-Fehler trotzdem weitermachen (graceful degradation)
            market = None

        logger.info(f"[{request_id}] SLOT: {slot}, SLUG: {slug}")
        if market:
            logger.info(f"[{request_id}] MARKET QUESTION: {market.get('question')}")
        else:
            logger.warning(f"[{request_id}] NO MARKET FOUND")

        up_token, down_token = resolve_up_down_tokens(market) if market else (None, None)

        action = None
        chosen_token = None

        if sig == "BULL":
            action = "BUY_UP"
            chosen_token = up_token
        elif sig == "BEAR":
            action = "BUY_DOWN"
            chosen_token = down_token
        else:
            action = "NO_ACTION"

        logger.info(f"[{request_id}] TOKEN DEBUG: action={action} up_token={str(up_token)[:18]} down_token={str(down_token)[:18]} chosen_token={str(chosen_token)[:18]}")

        # Risk Management Checks
        rm = get_risk_manager()
        pm = get_position_manager()
        
        # Calculate position size based on confidence
        calculated_size = rm.calculate_position_size(confidence=conf, base_size=None)
        
        # Check exposure limit
        exposure_check = rm.check_exposure(
            proposed_trade_size=calculated_size,
            active_trades=pm.active_trades,
        )
        
        if not exposure_check.allowed:
            logger.warning(f"[{request_id}] TRADE SKIPPED: {exposure_check.reason}")
            return {
                "ok": True,
                "ignored": True,
                "reason": "max_exposure",
                "exposure_check": {
                    "current_exposure": exposure_check.current_exposure,
                    "proposed_exposure": exposure_check.proposed_exposure,
                    "max_exposure": exposure_check.max_exposure,
                },
                "mode": "DRY_RUN" if settings.DRY_RUN else "LIVE"
            }
        
        # Check direction limit (max 1 position per direction)
        direction_allowed, direction_reason = rm.check_direction_limit(
            side="UP" if sig == "BULL" else "DOWN",
            active_trades=pm.active_trades,
        )
        
        if not direction_allowed:
            logger.warning(f"[{request_id}] TRADE SKIPPED: {direction_reason}")
            return {
                "ok": True,
                "ignored": True,
                "reason": "direction_limit",
                "message": direction_reason,
                "mode": "DRY_RUN" if settings.DRY_RUN else "LIVE"
            }
        
        # Use calculated size (from confidence-based sizing)
        size = calculated_size
        logger.info(
            f"[{request_id}] RISK CHECK OK: size={size:.2f} "
            f"(conf={conf}, exposure={exposure_check.proposed_exposure:.2f}/{exposure_check.max_exposure:.2f})"
        )

        # ====================================================================
        # MARKET QUALITY GATE (before Pattern Gate - more important!)
        # Ensures orderbook is healthy: best_ask exists, spread acceptable
        # ====================================================================
        market_quality_result = None
        if action in ("BUY_UP", "BUY_DOWN") and chosen_token and getattr(settings, "ENABLE_MARKET_QUALITY_GATE", True):
            try:
                from src.market_quality.gate import MarketQualityGate, QualityResult
                from agents.polymarket.polymarket import Polymarket
                
                # Get orderbook for chosen token
                if not hasattr(webhook, '_mq_polymarket'):
                    webhook._mq_polymarket = Polymarket()
                
                mq_orderbook = webhook._mq_polymarket.get_orderbook(chosen_token)
                
                # Initialize gate
                mq_gate = MarketQualityGate(
                    require_best_ask=getattr(settings, "REQUIRE_BEST_ASK", True),
                    min_ask_size=getattr(settings, "MIN_ASK_SIZE", None),
                    max_spread=getattr(settings, "MAX_SPREAD_ENTRY", None)
                )
                
                market_quality_result = mq_gate.check(mq_orderbook, chosen_token)
                
                # Determine mode
                mq_mode = getattr(settings, "MARKET_QUALITY_MODE", "shadow").lower()
                mq_shadow = (mq_mode == "shadow")
                mq_mode_str = "SHADOW" if mq_shadow else "ENFORCE"
                
                # Log market quality check
                spread_str = f", spread={market_quality_result.spread_pct:.2%}" if market_quality_result.spread_pct else ""
                logger.info(
                    f"[{request_id}] MARKET QUALITY ({mq_mode_str}): "
                    f"healthy={market_quality_result.is_healthy}, "
                    f"reason={market_quality_result.reason}, "
                    f"bid={market_quality_result.best_bid}, "
                    f"ask={market_quality_result.best_ask}"
                    f"{spread_str}"
                )
                
                # Block if unhealthy AND in enforce mode
                if not market_quality_result.is_healthy and not mq_shadow:
                    logger.warning(
                        f"[{request_id}] MARKET QUALITY BLOCK: reason={market_quality_result.reason} - "
                        f"Cannot execute trade with unhealthy orderbook"
                    )
                    return JSONResponse(
                        status_code=200,
                        content={
                            "ok": True,
                            "ignored": True,
                            "reason": f"market_quality_{market_quality_result.reason}",
                            "market_quality": {
                                "healthy": False,
                                "reason": market_quality_result.reason,
                                "best_bid": market_quality_result.best_bid,
                                "best_ask": market_quality_result.best_ask,
                            },
                            "mode": "PAPER" if is_paper_trading() else "LIVE"
                        }
                    )
                    
            except Exception as e:
                logger.error(f"[{request_id}] Market quality gate error: {e}")
                # Fail-open: allow trade if gate errors
                market_quality_result = None

        # Pattern Gate Check (before order submission)
        pattern_gate_result = None
        logger.info(f"[{request_id}] TOKEN DEBUG: action={action} slug={slug} up_token={str(up_token)[:18] if up_token else 'None'} down_token={str(down_token)[:18] if down_token else 'None'} chosen_token={str(chosen_token)[:18] if chosen_token else 'None'}")
        logger.info(f"[{request_id}] Pattern Gate Check: action={action}, chosen_token={'present' if chosen_token else 'None'}, ENABLE_PATTERN_GATE={settings.ENABLE_PATTERN_GATE}")
        if action in ("BUY_UP", "BUY_DOWN") and chosen_token and settings.ENABLE_PATTERN_GATE:
            try:
                from src.pattern_gate.gate import PatternGate
                
                # Initialize gate (singleton pattern - use function-level cache)
                if not hasattr(webhook, '_pattern_gate'):
                    webhook._pattern_gate = PatternGate(
                        min_edge=settings.PATTERN_GATE_MIN_EDGE,
                        min_samples=settings.PATTERN_GATE_MIN_SAMPLES,
                        min_confidence=settings.PATTERN_GATE_MIN_CONF,
                        candle_window=120
                    )
                
                gate = webhook._pattern_gate
                
                # Evaluate gate
                pattern_gate_result = gate.evaluate(
                    payload=payload.model_dump() if hasattr(payload, 'model_dump') else payload.__dict__,
                    market=market,
                    chosen_token=chosen_token,
                    action=action
                )
                
                # Log gate decision (vollständig: setupType, p, samples, implied, edge, decision, reason)
                gate_mode = getattr(settings, "PATTERN_GATE_MODE", "shadow").lower()
                legacy_shadow = getattr(settings, "PATTERN_GATE_SHADOW_MODE", None)
                shadow_mode = legacy_shadow if legacy_shadow is not None else (gate_mode == "shadow")
                mode_str = "SHADOW" if shadow_mode else "ENFORCE"
                decision_str = "ALLOW" if pattern_gate_result.should_trade else "BLOCK"
                
                # Log gate decision with None-safe formatting for implied_probability
                implied_str = f"{pattern_gate_result.implied_probability:.4f}" if pattern_gate_result.implied_probability is not None else "None"
                
                logger.info(
                    f"[{request_id}] PATTERN GATE ({mode_str}): "
                    f"setupType={pattern_gate_result.setup_type.value}, "
                    f"p={pattern_gate_result.pattern_probability:.4f}, "
                    f"samples={pattern_gate_result.samples}, "
                    f"implied={implied_str}, "
                    f"edge={pattern_gate_result.edge:.4f}, "
                    f"decision={decision_str}, "
                    f"reason={pattern_gate_result.reason}"
                )
                
                # Block if gate says no
                if not pattern_gate_result.should_trade:
                    return {
                        "ok": True,
                        "ignored": True,
                        "status": "blocked",
                        "reason": "edge_gate",
                        "pattern_gate": {
                            "should_trade": False,
                            "reason": pattern_gate_result.reason,
                            "setup_type": pattern_gate_result.setup_type.value,
                            "pattern_probability": round(pattern_gate_result.pattern_probability, 4),
                            "implied_probability": round(pattern_gate_result.implied_probability, 4) if pattern_gate_result.implied_probability is not None else None,
                            "edge": round(pattern_gate_result.edge, 4),
                            "samples": pattern_gate_result.samples,
                            "confidence": pattern_gate_result.confidence,
                            "regime": pattern_gate_result.regime,
                            "details": pattern_gate_result.details or {},
                        },
                        "mode": get_trading_mode_str(),
                    }
            except Exception as e:
                logger.error(f"[{request_id}] Pattern gate error: {e}", exc_info=True)
                # On error, allow trade (fail open)
                pattern_gate_result = None

        would_order = None
        if action in ("BUY_UP", "BUY_DOWN") and chosen_token:
            now_utc = datetime.now(timezone.utc)
            session = calc_session(now_utc.hour)
            utc_time = utc_now_iso()
            
            # Register trade in metrics tracker
            mt = get_metrics_tracker()
            # Note: We'll register the trade when it's actually executed
            # For now, we just log the order
            
            # Erweiterte Log-Zeile mit allen neuen Feldern
            would_order = {
                # Required fields
                "utc_time": utc_time,
                "session": session,
                "symbol": settings.SYMBOL,
                "timeframe": settings.TIMEFRAME,
                "signal": sig,
                "confidence": conf,
                "score": score,
                "speedRatio": speed_ratio,
                "size": size,
                "sw": sw,
                "rt": rt,
                "mr": mr,
                "botMove": bot_move,
                "regime": regime,
                "dislocation": dislocation,
                
                # Legacy fields (für Rückwärtskompatibilität)
                "side": "BUY",
                "action": action,
                "size_usdc": size,
                "token_id": chosen_token,
                "market_id": market.get("id") if market else None,
                "slug": slug,
                "slot": slot,
                
                # Risk management fields
                "calculated_size": size,
                "exposure_check": {
                    "current_exposure": exposure_check.current_exposure,
                    "proposed_exposure": exposure_check.proposed_exposure,
                    "max_exposure": exposure_check.max_exposure,
                },
                
                # Optional fields
                "request_id": request_id,
                "server_version": settings.APP_VERSION,
                "signal_id": payload.signal_id,  # TradingView signal ID for tracking (persist in trade record)
                "source": payload.source or "unknown",  # Source of signal (persist in trade record, default "unknown")
                "mode": mode,  # Mode (for Phase-2 tagging: "test" vs "live")
                
                # Pattern Gate fields (for edge analysis filtering)
                # edge_valid=True means implied was available and edge could be calculated
                # edge_valid=False means filter this trade from edge statistics
                "pattern_gate_mode": getattr(settings, "PATTERN_GATE_MODE", "shadow") if settings.ENABLE_PATTERN_GATE else None,
                "pattern_setup": pattern_gate_result.setup_type.value if pattern_gate_result else None,
                "pattern_p": pattern_gate_result.pattern_probability if pattern_gate_result else None,
                "pattern_implied": pattern_gate_result.implied_probability if pattern_gate_result else None,
                "pattern_edge": pattern_gate_result.edge if pattern_gate_result else None,
                "pattern_samples": pattern_gate_result.samples if pattern_gate_result else None,
                "edge_valid": (pattern_gate_result is not None and pattern_gate_result.implied_probability is not None),
                "edge_invalid_reason": None if (pattern_gate_result is None or pattern_gate_result.implied_probability is not None) else "implied_unavailable",
                
                # Market Quality fields (for orderbook health analysis)
                "market_quality_healthy": market_quality_result.is_healthy if market_quality_result else None,
                "market_quality_reason": market_quality_result.reason if market_quality_result else None,
                "market_quality_bid": market_quality_result.best_bid if market_quality_result else None,
                "market_quality_ask": market_quality_result.best_ask if market_quality_result else None,
                "market_quality_spread_pct": market_quality_result.spread_pct if market_quality_result else None,
            }

            # HARD INVARIANT: entry_price MUST be set before opening trade
            # Use symmetric _get_entry_price_for_trade() function (same source as exit price)
            # If price fetch fails, DO NOT open trade (skip with reason="no_entry_price")
            # IMPORTANT: entry_price is fetched SYNCHRONOUSLY before trade creation (no async race)
            entry_price_data = None
            entry_price = None
            if is_paper_trading() and market and chosen_token:
                # Fetch entry price from orderbook (symmetric to exit price)
                # This is SYNCHRONOUS - no async race condition possible
                entry_price_data = _get_entry_price_for_trade(chosen_token)
                
                if entry_price_data is None:
                    logger.error(
                        f"[{request_id}] HARD INVARIANT VIOLATION: entry_price_data is None. "
                        f"Trade will NOT be opened. token_id={chosen_token[:16]}... "
                        f"(orderbook fetch failed or empty after retry)"
                    )
                    # Log decision for Phase-2 analysis (even though trade is rejected)
                    log_decision(
                        request_id=request_id,
                        slug=slug,
                        slot=slot,
                        action=action,
                        signal=sig,
                        chosen_token=chosen_token,
                        conf=conf,
                        regime=regime,
                        outcome="rejected",
                        outcome_reason="no_entry_price",
                        market_quality_result=market_quality_result,
                        pattern_gate_result=pattern_gate_result,
                    )
                    return {
                        "ok": True,
                        "ignored": True,
                        "reason": "no_entry_price",
                        "message": "Cannot fetch entry price from orderbook (empty or failed). Trade not opened.",
                        "token_id": chosen_token,
                        "mode": get_trading_mode_str(),
                    }
                
                entry_price = entry_price_data.get("entry_price")
                
                # Validate entry_price is not None
                if entry_price is None:
                    logger.error(
                        f"[{request_id}] HARD INVARIANT VIOLATION: entry_price is None in entry_price_data. "
                        f"Trade will NOT be opened. token_id={chosen_token[:16]}... "
                        f"(price_source={entry_price_data.get('price_source')}, retry_used={entry_price_data.get('retry_used')})"
                    )
                    return {
                        "ok": True,
                        "ignored": True,
                        "reason": "no_entry_price",
                        "message": "Entry price is None in orderbook data. Trade not opened.",
                        "token_id": chosen_token,
                        "price_source": entry_price_data.get("price_source"),
                        "retry_used": entry_price_data.get("retry_used"),
                        "mode": get_trading_mode_str(),
                    }
                
                # Validate entry_price is a valid float
                try:
                    entry_price = float(entry_price)
                    if entry_price <= 0 or entry_price >= 1:
                        logger.error(
                            f"[{request_id}] HARD INVARIANT VIOLATION: entry_price={entry_price} is invalid "
                            f"(must be 0 < price < 1). Trade will NOT be opened. "
                            f"(price_source={entry_price_data.get('price_source')}, retry_used={entry_price_data.get('retry_used')})"
                        )
                        return {
                            "ok": True,
                            "ignored": True,
                            "reason": "no_entry_price",
                            "message": f"Invalid entry price: {entry_price} (must be 0 < price < 1)",
                            "token_id": chosen_token,
                            "entry_price": entry_price,
                            "price_source": entry_price_data.get("price_source"),
                            "retry_used": entry_price_data.get("retry_used"),
                            "mode": get_trading_mode_str(),
                        }
                except (ValueError, TypeError):
                    logger.error(
                        f"[{request_id}] HARD INVARIANT VIOLATION: entry_price={entry_price} is not a valid float. "
                        f"Trade will NOT be opened. "
                        f"(price_source={entry_price_data.get('price_source')}, retry_used={entry_price_data.get('retry_used')})"
                    )
                    return {
                        "ok": True,
                        "ignored": True,
                        "reason": "no_entry_price",
                        "message": f"Entry price is not a valid float: {entry_price}",
                        "token_id": chosen_token,
                        "price_source": entry_price_data.get("price_source"),
                        "retry_used": entry_price_data.get("retry_used"),
                        "mode": get_trading_mode_str(),
                    }
                
                # Log successful price fetch with all details
                logger.info(
                    f"[{request_id}] ENTRY PRICE READY: entry_price={entry_price:.6f}, "
                    f"method={entry_price_data.get('entry_method')}, "
                    f"price_source={entry_price_data.get('price_source')}, "
                    f"retry_used={entry_price_data.get('retry_used')}, "
                    f"best_bid={entry_price_data.get('best_bid')}, "
                    f"best_ask={entry_price_data.get('best_ask')}, "
                    f"token_id={chosen_token[:16]}... "
                    f"(Trade will be created with this price - NO RACE CONDITION)"
                )
            
            # Register Paper Trade in Position Manager (for auto-close)
            # entry_price is guaranteed to be valid at this point (not None, valid float, 0 < price < 1)
            # IMPORTANT: entry_price was fetched SYNCHRONOUSLY before this point - NO RACE CONDITION
            if is_paper_trading() and market and chosen_token and entry_price is not None:
                try:
                    # Log trade creation with entry_price (for debugging)
                    logger.info(
                        f"[{request_id}] CREATING TRADE: entry_price={entry_price:.6f} "
                        f"(guaranteed valid, fetched synchronously, no race condition)"
                    )
                    
                    # Create trade in Position Manager for auto-close tracking
                    # NOTE: timeout_seconds is for CONFIRMATION timeout, NOT for auto-close TTL
                    # Auto-Close TTL is handled separately in risk_monitoring_task
                    # For paper trades, use a very long timeout (9999s) to prevent timeout-based cleanup
                    # The risk_monitoring_task will handle auto-close via TTL instead
                    paper_trade = pm.create_trade(
                        market_id=str(market.get("id", f"paper_{slot}")),
                        token_id=chosen_token,
                        side="UP" if sig == "BULL" else "DOWN",
                        leg1_size=size,
                        leg1_price=entry_price,  # This is guaranteed to be valid (not None)
                        leg1_entry_id=f"paper_{request_id}",
                        timeout_seconds=9999,  # Very long timeout to prevent cleanup (auto-close handles it via TTL)
                    )
                    
                    if paper_trade:
                        # Store trade_id in would_order for later reference
                        would_order["trade_id"] = paper_trade.trade_id
                        logger.info(
                            f"[{request_id}] Paper trade registered: {paper_trade.trade_id}, "
                            f"entry_price={paper_trade.entry_price:.6f} "
                            f"(verified: matches fetched price)"
                        )
                    else:
                        logger.warning(f"[{request_id}] Failed to register paper trade in Position Manager (market may be locked)")
                except Exception as e:
                    logger.error(
                        f"[{request_id}] Error registering paper trade: {e} "
                        f"(entry_price={entry_price} was valid before this point)"
                    )
            
            # HARD INVARIANT: entry_price MUST be set in would_order before writing to persistent storage
            # This ensures entry_price is never None in paper_trades.jsonl
            # Also store entry_method and entry_ob_timestamp for consistency with exit price
            if entry_price is not None and entry_price_data is not None:
                would_order["entry_price"] = entry_price
                would_order["price"] = entry_price  # Legacy field for backward compatibility
                would_order["entry_method"] = entry_price_data.get("entry_method")
                would_order["entry_ob_timestamp"] = entry_price_data.get("entry_ob_timestamp")
                would_order["entry_best_bid"] = entry_price_data.get("best_bid")
                would_order["entry_best_ask"] = entry_price_data.get("best_ask")
                
                # Calculate and store spread_entry (for liquidity analysis)
                best_bid = entry_price_data.get("best_bid")
                best_ask = entry_price_data.get("best_ask")
                spread_entry = None
                if best_bid is not None and best_ask is not None:
                    spread_entry = best_ask - best_bid
                    would_order["spread_entry"] = spread_entry
                    logger.debug(
                        f"[{request_id}] Spread at entry: {spread_entry:.6f} "
                        f"(best_bid={best_bid:.6f}, best_ask={best_ask:.6f})"
                    )
                    # NOTE: Spread check is done by Market Quality Gate (shadow mode).
                    # No additional blocking here - we want to collect data in Phase-2.
            
            # Add SESSION_ID and trade_id to trade record (REQUIRED for all trades)
            if is_paper_trading() and settings.SESSION_ID:
                would_order["session_id"] = settings.SESSION_ID
            else:
                # This should never happen due to the checks above, but add safety check
                logger.error(
                    f"[{request_id}] CRITICAL: entry_price is None when writing to paper_trades.jsonl. "
                    f"Trade will NOT be logged to prevent data corruption."
                )
                return {
                    "ok": True,
                    "ignored": True,
                    "reason": "no_entry_price",
                    "message": "Entry price validation failed. Trade not logged.",
                    "mode": get_trading_mode_str(),
                }
            
            # Ensure trade_id is always set (should already be set from paper_trade.trade_id above)
            if "trade_id" not in would_order or not would_order.get("trade_id"):
                logger.warning(f"[{request_id}] trade_id missing in would_order, generating new one")
                would_order["trade_id"] = f"trade_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
            
            # Ensure session_id is always set (should already be set above)
            if "session_id" not in would_order or not would_order.get("session_id"):
                if settings.SESSION_ID:
                    would_order["session_id"] = settings.SESSION_ID
                    logger.warning(f"[{request_id}] session_id missing in would_order, using settings.SESSION_ID={settings.SESSION_ID}")
            
            # Add phase2_session_id if this is a Phase-2 trade
            # Phase-2 Tagging: source="tradingview" OR mode!="test"
            source = str(would_order.get("source", "")).lower().strip()
            mode = str(would_order.get("mode", "")).lower().strip()
            is_phase2_source = (source == "tradingview") or (mode != "" and mode != "test")
            
            if is_phase2_source and settings.PHASE2_SESSION_ID:
                would_order["phase2_session_id"] = settings.PHASE2_SESSION_ID
                logger.debug(f"[{request_id}] Phase-2 trade detected (source={source}, mode={mode}), added phase2_session_id={settings.PHASE2_SESSION_ID}")
            
            # in Datei loggen (entry_price is guaranteed to be set at this point)
            append_jsonl(settings.PAPER_LOG_PATH, would_order)
            logger.info(f"[{request_id}] PAPER LOGGED TO: {settings.PAPER_LOG_PATH}")
            logger.debug(f"[{request_id}] PAPER ORDER: {would_order}")
            
            # Log decision for Phase-2 analysis (trade opened successfully)
            log_decision(
                request_id=request_id,
                slug=slug,
                slot=slot,
                action=action,
                signal=sig,
                chosen_token=chosen_token,
                conf=conf,
                regime=regime,
                outcome="opened",
                outcome_reason="ok",
                market_quality_result=market_quality_result,
                pattern_gate_result=pattern_gate_result,
            )
        else:
            logger.warning(f"[{request_id}] NO PAPER ORDER (missing token or action)")

        clob_raw = None
        if market:
            try:
                # Manche Antworten haben clobTokenIds schon als dict,
                # manche als String. Wir machen es immer "string safe".
                clob = market.get("clobTokenIds")
                if clob is None:
                    clob_raw = None
                elif isinstance(clob, str):
                    # Bereits ein String, verwenden wir direkt
                    clob_raw = clob
                else:
                    # Dict oder Liste, serialisieren wir
                    clob_raw = json.dumps(clob)
            except Exception as e:
                logger.error(f"[{request_id}] CLOB SERIALIZE ERROR: {repr(e)}")
                clob_raw = str(market.get("clobTokenIds")) if market.get("clobTokenIds") else None

        return {
            "ok": True,
            "signal": sig,
            "score": score,
            "confidence": conf,
            "slot": slot,
            "slug": slug,
            "market_id": market.get("id") if market else None,
            "question": market.get("question") if market else None,
            "clobTokenIds_raw": clob_raw,
            "debug_outcomes": market.get("outcomes") if market else None,
            "debug_tokens": market.get("tokens") if market else None,
            "debug_clobTokenIds": market.get("clobTokenIds") if market else None,
            "action": action,
            "up_token": up_token,
            "down_token": down_token,
            "chosen_token": chosen_token,
            "paper_order": would_order,
            "mode": "DRY_RUN" if settings.DRY_RUN else "LIVE"
        }
    except json.JSONDecodeError as e:
        logger.error(f"[{request_id}] JSON PARSE ERROR: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
    except ValidationError as e:
        logger.error(f"[{request_id}] VALIDATION ERROR: {e}")
        mode_str = "DRY_RUN" if settings.DRY_RUN else "LIVE"
        return {"ok": False, "error": str(e), "mode": mode_str}
    except APIError as e:
        logger.error(f"[{request_id}] API ERROR: {e}")
        mode_str = "DRY_RUN" if settings.DRY_RUN else "LIVE"
        return {"ok": False, "error": str(e), "mode": mode_str}
    except Exception as e:
        logger.exception(f"[{request_id}] WEBHOOK ERROR: {e}")
        # Immer 200 OK zurückgeben, außer bei komplett kaputtem JSON (400)
        mode_str = "DRY_RUN" if settings.DRY_RUN else "LIVE"
        return {"ok": False, "error": str(e), "mode": mode_str}
