"""PolyGuez Momentum — async event loop runner.

Separate from existing Trader.one_best_trade() pipeline.
"""

import asyncio
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
import websockets
from dotenv import load_dotenv

from agents.polymarket.gamma import GammaMarketClient
from agents.polymarket.polymarket import Polymarket
from agents.strategies.btc_feed import PriceFeedManager
from agents.strategies.market_discovery import MarketDiscovery
from agents.strategies.polyguez_strategy import (
    calculate_max_capital_at_risk,
    calculate_position_size,
    check_daily_loss_limit,
    get_daily_loss_size_multiplier,
    check_emergency_exit,
    compute_clob_depth,
    compute_cooldown,
    evaluate_entry_signal,
    execute_emergency_exit,
    execute_entry,
    get_llm_confirmation,
    load_rolling_stats,
    save_rolling_stats,
    settle_with_retry,
)
from agents.utils.logger import get_logger, log_event
from agents.utils.supabase_logger import (
    log_signal,
    log_trade,
    log_shadow_trade,
    settle_shadow_trades,
    _log_executor,
    _send_telegram_alert,
)
from agents.utils.vol_tracker import RealizedVolTracker, implied_vol as compute_implied_vol
from agents.utils.objects import (
    DashboardSnapshot,
    PendingSettlement,
    PolyGuezConfig,
    PositionState,
    RollingStats,
    SignalState,
    TradeRecord,
)

load_dotenv()
logger = get_logger("polyguez.runner")

# Estimated cycle length for cooldown timing
CYCLE_SECONDS = 300


class PolyGuezRunner:
    """Main async event loop for PolyGuez Momentum strategy."""

    def __init__(self, config=None):
        self.config = config or PolyGuezConfig()
        self._config_lock = asyncio.Lock()

        # LATENCY-TASK-5: live-mode LLM fallback enforcement. "go" means
        # "fire the trade anyway when the LLM times out" — safe in
        # dry-run (we just record what would have happened) but unsafe
        # in live mode, where it bypasses the guardrail we pay the LLM
        # latency tax for. Force the safer default and log loudly if an
        # operator has tried to configure "go".
        if self.config.mode == "live" and self.config.llm_timeout_fallback == "go":
            logger.critical(
                "LATENCY-TASK-5: llm_timeout_fallback='go' is unsafe in live mode; "
                "forcing 'no-go' for this run. Set reduce-size in config if you want a middle path."
            )
            self.config.llm_timeout_fallback = "no-go"

        # Existing repo components
        self._polymarket = None  # Lazy init — needs wallet key
        self._gamma = GammaMarketClient()
        self._discovery = MarketDiscovery(self._gamma)

        # New components
        self._btc_feed = PriceFeedManager(self.config)
        self._vol_tracker = RealizedVolTracker()

        # State
        self._rolling_stats = load_rolling_stats()
        self._position = None  # PositionState or None
        self._current_market = None
        self._current_signal = None
        self._current_depth = 0.0  # FIX 2
        self._last_llm_verdict = ""
        self._last_llm_reason = ""
        self._last_llm_provider = ""
        self._last_llm_time = 0.0
        self._killed = False
        self._kill_timestamp = None
        # COR-03: in-process idempotency guard for _settle() / emergency-exit.
        # Populated when we finalize a trade (win/loss/emergency-exit) for a
        # market so that a redundant settle-call in the same process is a
        # no-op. Cross-restart protection is separately provided by the
        # unconditional save_rolling_stats() at the end of _settle().
        self._settled_market_ids: set = set()
        self._loop_heartbeat_ts = 0.0  # monotonic seconds; updated each main-loop tick for health check
        self._usdc_balance = 0.0
        self._gamma_ok = False
        self._discovery_misses = 0  # cycles where _discover_market() returned None
        self._clob_ok = False
        self._price_to_beat = None
        self._p2b_source = "none"
        self._p2b_consecutive_failures = 0
        self._p2b_cross_check_passed = None
        self._p2b_cross_check_divergence = None
        # LATENCY-TASK-2: distance (seconds) between the Chainlink sample
        # used as P2B and the market's eventStartTime, or None if the
        # cycle was skipped for P2B quality. Logged to signal_log per cycle.
        self._p2b_offset_seconds: Optional[float] = None

        # Provider context cache (refreshed by background task)
        self._provider_context_cache = {"fetched_at": 0.0, "data": ""}
        self._provider_cache_task = None

        # CLOB WebSocket state
        self._clob_ws = None
        self._clob_ws_task = None
        self._clob_ws_yes = 0.0
        self._clob_ws_no = 0.0
        self._clob_ws_last_msg = 0.0
        self._clob_ws_tokens = (None, None)  # (yes_token, no_token)
        self._clob_ws_connected = False
        self._clob_ws_reconnect_count = 0
        self._clob_ws_ping_task = None
        # COR-06: CLOB WS stale-price guard. Set False on disconnect /
        # reconnect start so the main cycle refuses to read the stale zero
        # prices during the reconnect window. Flipped True on the first
        # successful book/price message with both YES and NO populated.
        self._clob_ws_prices_valid: bool = False
        self._clob_http_session = None
        self._heartbeat_task = None
        # LATENCY-TASK-4: monotonic timestamp of the last successful CLOB
        # heartbeat post. Zero means "never sent successfully". Consumed
        # by _entry_window to refuse entries when the session is about
        # to be cancelled by Polymarket's 10s heartbeat timeout.
        self._last_heartbeat_sent_ts: float = 0.0
        # LATENCY-TASK-4: startup grace window for the heartbeat gate.
        # The heartbeat task tick-ones ~5s after runner start; the first
        # few _entry_window evaluations shouldn't fail on "never sent"
        # before the task has had a chance to post.
        self._runner_start_ts: float = time.time()
        # LATENCY-TASK-4: True/False after _heartbeat_loop detects whether
        # py_clob_client supports post_heartbeat. None = not yet determined.
        # Exposed on self so _entry_window can bypass the heartbeat gate when
        # the installed client version doesn't support it (e.g. v0.17.5).
        self._heartbeat_supported: Optional[bool] = None
        # LATENCY-TASK-3: depth TTL cache. _fetch_depth is called every
        # 100ms tick inside _entry_window. CLOB depth changes on the order
        # of seconds, so a 4s cache is safe and eliminates ~9 of every 10
        # get_order_book HTTP calls.
        self._depth_cache: dict = {}  # token_id → {"depth": float, "ts": float}
        # Market discovery result cache. A given 5-min BTC market is valid for
        # up to 300s, so re-querying Gamma on every cycle is wasteful. Cache
        # for 60s — short enough to catch the window boundary, long enough to
        # skip ~12 Gamma calls per market window on normal cycles.
        self._market_cache: dict = {"market": None, "ts": 0.0}

        # Hot-path timing (set per entry, read at settle)
        self._last_entry_llm_ms = 0.0
        self._last_entry_order_ms = 0.0
        self._last_entry_total_ms = 0.0
        # MODEL-02: fee + fill-type fields captured at entry time from the
        # CLOB executor response, persisted into trade_log at settlement.
        self._last_entry_fee_paid: float = 0.0
        self._last_entry_taker_maker: Optional[str] = "simulated"
        self._last_entry_fill_price: float = 0.0

    # -- Public API for dashboard / CLI ------------------------------------

    @property
    def is_killed(self):
        return self._killed

    async def update_config(self, partial):
        """Update config from dashboard. Takes effect next cycle."""
        async with self._config_lock:
            current = self.config.model_dump()
            current.update(partial)
            self.config = PolyGuezConfig(**current)
            # Update BTC feed config reference
            self._btc_feed._config = self.config
            log_event(logger, "config_updated", "Config updated from dashboard", partial)

    def get_snapshot(self):
        """Build a DashboardSnapshot of current state."""
        expiry = None
        expiry_seconds = 0.0
        elapsed = 0.0
        if self._current_market:
            exp_dt = MarketDiscovery.get_market_expiry(self._current_market)
            if exp_dt:
                expiry = exp_dt.isoformat()
                expiry_seconds = max(0, (exp_dt - datetime.now(timezone.utc)).total_seconds())
                # ISSUE-4 fix: use signal's elapsed_seconds when available (computed fresh each cycle)
                # instead of deriving from expiry which assumes exactly 300s total market duration
                if self._current_signal and self._current_signal.elapsed_seconds > 0:
                    elapsed = self._current_signal.elapsed_seconds
                else:
                    end_total = 300.0
                    elapsed = max(0, end_total - expiry_seconds)

        unrealized = 0.0
        if self._position:
            current_price = (
                self._current_signal.yes_price
                if self._position.side == "YES"
                else self._current_signal.no_price
            ) if self._current_signal else 0.0
            unrealized = (current_price - self._position.entry_price) * self._position.size_usdc

        cooldown_active = False
        cooldown_remaining = 0.0
        if self._rolling_stats.cooldown_until:
            try:
                until = datetime.fromisoformat(self._rolling_stats.cooldown_until)
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                remaining = (until - datetime.now(timezone.utc)).total_seconds()
                if remaining > 0:
                    cooldown_active = True
                    cooldown_remaining = remaining
            except (ValueError, TypeError):
                pass

        chainlink_price, _cl_age = self._btc_feed.get_chainlink_price()
        chainlink_vs_ptb = chainlink_price - self._price_to_beat if chainlink_price and self._price_to_beat is not None else 0.0

        return DashboardSnapshot(
            mode=self.config.mode,
            btc_feed_connected=self._btc_feed.is_connected,
            clob_connected=self._clob_ok,
            gamma_connected=self._gamma_ok,
            usdc_balance=self._usdc_balance,
            max_capital_at_risk=calculate_max_capital_at_risk(self._usdc_balance, self.config),
            position_size_ceiling=calculate_max_capital_at_risk(self._usdc_balance, self.config),
            daily_pnl=self._rolling_stats.daily_pnl,
            killed=self._killed,
            kill_timestamp=self._kill_timestamp,
            current_market_question=self._current_market.get("question", "") if self._current_market else "",
            current_market_expiry=expiry,
            btc_price=self._btc_feed.get_price() or 0.0,
            chainlink_price=chainlink_price,
            chainlink_source=self._btc_feed.chainlink_source,  # FIX 4
            binance_chainlink_gap=self._btc_feed.get_binance_chainlink_gap(),
            gap_direction=self._btc_feed.get_gap_direction(),
            price_to_beat=self._price_to_beat or 0.0,
            chainlink_vs_price_to_beat=chainlink_vs_ptb,
            btc_velocity=self._btc_feed.get_velocity(),
            btc_direction="up" if self._btc_feed.get_velocity() > 0 else "down",
            yes_price=self._current_signal.yes_price if self._current_signal else 0.0,
            no_price=self._current_signal.no_price if self._current_signal else 0.0,
            clob_spread=self._current_signal.spread if self._current_signal else 0.0,
            clob_depth=self._current_depth,  # FIX 2
            entry_window_elapsed=elapsed,
            signal=self._current_signal,
            llm_verdict=self._last_llm_verdict,
            llm_reason=self._last_llm_reason,
            llm_response_time=self._last_llm_time,
            position=self._position,
            unrealized_pnl=unrealized,
            time_to_expiry=expiry_seconds,
            rolling_stats=self._rolling_stats,
            cooldown_active=cooldown_active,
            cooldown_remaining_seconds=cooldown_remaining,
            p2b_source=self._p2b_source,
            p2b_parse_success=self._price_to_beat is not None,
            p2b_cross_check_passed=self._p2b_cross_check_passed,
            p2b_cross_check_divergence=self._p2b_cross_check_divergence,
            strike_delta=self._current_signal.strike_delta if self._current_signal else 0.0,
            terminal_probability=self._current_signal.terminal_probability if self._current_signal else 0.0,
            terminal_edge=self._current_signal.terminal_edge if self._current_signal else 0.0,
            p2b_consecutive_failures=self._p2b_consecutive_failures,
            config=self.config,
        )

    async def kill(self):
        """Kill switch — halt everything."""
        self._killed = True
        self._kill_timestamp = datetime.now(timezone.utc).isoformat()
        log_event(logger, "kill_switch", "KILLED BY OPERATOR")

        # Emergency exit if holding a position
        if self._position and self._polymarket:
            await execute_emergency_exit(self._polymarket, self._position, self.config.mode)
            self._position = None

        # Stop provider cache task
        if self._provider_cache_task:
            self._provider_cache_task.cancel()
            try: await self._provider_cache_task
            except asyncio.CancelledError: pass

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try: await self._heartbeat_task
            except asyncio.CancelledError: pass

        # Stop CLOB WS
        if self._clob_ws_ping_task:
            self._clob_ws_ping_task.cancel()
            self._clob_ws_ping_task = None
        if self._clob_ws_task:
            self._clob_ws_task.cancel()
            try: await self._clob_ws_task
            except asyncio.CancelledError: pass
        if self._clob_ws:
            try: await self._clob_ws.close()
            except: pass

        # Stop CLOB HTTP session
        if self._clob_http_session:
            await self._clob_http_session.close()
            self._clob_http_session = None

        # Stop BTC feed
        await self._btc_feed.stop()

    async def _provider_cache_loop(self):
        """Background task: refresh provider context every 30s."""
        from agents.strategies.data_providers import fetch_all_providers
        while not self._killed:
            try:
                market_ctx = {}
                if self._current_signal:
                    market_ctx = {
                        "direction": self._current_signal.direction,
                        "velocity": self._current_signal.btc_velocity,
                        "elapsed_seconds": self._current_signal.elapsed_seconds,
                        "binance_chainlink_gap": self._current_signal.binance_chainlink_gap,
                    }
                results = await fetch_all_providers(
                    self.config.data_providers, market_ctx,
                    timeout=self.config.data_provider_timeout,
                )
                if results:
                    import json as _json
                    self._provider_context_cache = {
                        "fetched_at": time.time(),
                        "data": _json.dumps(results, default=str)[:2000],
                    }
            except Exception as exc:
                log_event(logger, "provider_cache_error",
                    f"Provider cache refresh failed: {exc}", level=30)
            await asyncio.sleep(30)

    async def _heartbeat_loop(self):
        """Send CLOB heartbeat every 5s to keep maker orders alive.
        Polymarket cancels all open orders after 10s without a heartbeat.
        Degrades gracefully if post_heartbeat is not available in the installed client version."""
        heartbeat_id = ""
        _heartbeat_supported = None  # None = unknown, True/False after first check
        while not self._killed:
            try:
                if self._polymarket and self._polymarket.client:
                    if _heartbeat_supported is None:
                        _heartbeat_supported = hasattr(self._polymarket.client, 'post_heartbeat')
                        self._heartbeat_supported = _heartbeat_supported
                        if not _heartbeat_supported:
                            log_event(logger, "heartbeat_warn",
                                "post_heartbeat not available in this py-clob-client version — heartbeat disabled. Upgrade to v0.22+ to enable.", level=30)
                    if _heartbeat_supported:
                        loop = asyncio.get_event_loop()
                        resp = await loop.run_in_executor(
                            None,
                            self._polymarket.client.post_heartbeat,
                            heartbeat_id,
                        )
                        if isinstance(resp, dict):
                            heartbeat_id = resp.get("heartbeat_id", heartbeat_id)
                        # LATENCY-TASK-4: record the successful post so
                        # _entry_window can see how long ago the last
                        # heartbeat went out.
                        self._last_heartbeat_sent_ts = time.time()
            except Exception as e:
                log_event(logger, "heartbeat_error",
                    f"Heartbeat failed: {e}", level=30)
            await asyncio.sleep(5)

    def _spawn(self, coro, name: str) -> asyncio.Task:
        """COR-04: asyncio.create_task + fatal-crash done-callback.

        Wraps every long-lived background task (provider cache, CLOB WS,
        heartbeat, CLOB WS ping, etc.) so an unhandled exception flips
        `self._killed = True` and emits a Telegram alert instead of
        silently stopping the task while `/health` still reports green.
        """
        task = asyncio.create_task(coro, name=name)

        def _on_done(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            try:
                exc = t.exception()
            except asyncio.CancelledError:
                return
            if exc is None:
                return
            try:
                log_event(
                    logger,
                    "background_task_fatal",
                    f"Background task '{name}' crashed: {type(exc).__name__}: {exc}",
                    level=50,
                )
            except Exception:
                pass
            try:
                _send_telegram_alert(
                    f"[PolyGuez] background task '{name}' crashed: {exc!r}. "
                    f"Bot is halting (`_killed=True`)."
                )
            except Exception:
                pass
            self._killed = True

        task.add_done_callback(_on_done)
        return task

    # -- Main loop ---------------------------------------------------------

    async def run(self):
        """Main event loop — runs until killed."""
        log_event(logger, "runner_start", f"PolyGuez starting in {self.config.mode} mode")
        if self.config.dashboard_secret:
            log_event(logger, "dashboard_secret", f"Dashboard secret: {self.config.dashboard_secret[:8]}... (use ?secret=<full_token> to access)")

        # Validate mode
        valid_modes = {"dry-run", "paper", "live"}
        if self.config.mode not in valid_modes:
            log_event(logger, "invalid_mode", f"CRITICAL: mode='{self.config.mode}' not in {valid_modes} — aborting", level=50)
            return

        # Startup capability check
        _caps = {
            "Supabase": "ok" if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY") else "disabled",
            "LLM": "ok" if any(os.environ.get(k) for k in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")) else "disabled",
        }
        log_event(logger, "startup_capabilities", f"Capabilities: {_caps}")

        # Warn if session_tag doesn't match the dashboard views default
        _dashboard_tag = "V5"  # Must match session_tag_current default in migrations
        if self.config.session_tag != _dashboard_tag:
            log_event(logger, "session_tag_mismatch",
                f"WARNING: config.session_tag='{self.config.session_tag}' does not match "
                f"dashboard views filter ('{_dashboard_tag}'). Dashboard will not show "
                f"this session's data. Set SESSION_TAG={_dashboard_tag} or run "
                f"set_active_session('{self.config.session_tag}') in Supabase.",
                level=40)

        if self.config.mode == "live":
            if _caps["LLM"] == "disabled" and self.config.llm_enabled:
                log_event(logger, "live_no_llm", "CRITICAL: Live mode with llm_enabled=True but no LLM API key — aborting", level=50)
                return
            if self.config.llm_timeout_fallback == "go":
                log_event(logger, "live_timeout_fallback_go", "WARNING: llm_timeout_fallback='go' in live mode — LLM timeouts will approve trades", level=40)

        # Install signal handlers for graceful shutdown
        import signal as _signal
        loop = asyncio.get_event_loop()
        for sig in (_signal.SIGTERM, _signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(self.kill()))

        # Init Polymarket client in ALL modes for read operations (balance, CLOB prices).
        # Trade execution guards in execute_entry/execute_emergency_exit remain mode-gated.
        try:
            loop = asyncio.get_event_loop()
            self._polymarket = await loop.run_in_executor(None, Polymarket)
            log_event(logger, "wallet_connected",
                f"Polymarket client initialized (mode={self.config.mode}, "
                f"rpc={self._polymarket.polygon_rpc})")
        except Exception as exc:
            log_event(logger, "wallet_error",
                f"Failed to init Polymarket: {type(exc).__name__}: {exc}",
                level=40)
            self._polymarket = None
            if self.config.mode == "live":
                log_event(logger, "runner_halt", "Cannot run live without wallet")
                return
            else:
                log_event(logger, "wallet_fallback",
                    "Continuing without wallet — CLOB prices will use Gamma outcomePrices, "
                    "balance will be simulated $100")

        # Live mode: on-chain wallet reconciliation is mandatory (audit 3.2).
        # A failed balance read in live mode cannot fall through — we would
        # start with an unknown on-chain state and phantom balance, exactly
        # the scenario the audit warned against. Refuse to start instead.
        if self.config.mode == "live" and self._polymarket:
            loop = asyncio.get_event_loop()
            try:
                balance = await loop.run_in_executor(None, self._polymarket.get_usdc_balance)
            except Exception as exc:
                log_event(
                    logger,
                    "startup_balance_halt",
                    f"LIVE mode: on-chain USDC balance read failed — halting. Error: {exc}",
                    level=40,
                )
                self._killed = True
                return
            log_event(logger, "startup_balance", f"Wallet USDC balance: ${balance:.2f}")
            self._usdc_balance = float(balance)
            if balance < self.config.bet_size_low_balance_normal:
                log_event(
                    logger,
                    "startup_low_balance_halt",
                    f"LIVE mode: balance ${balance:.2f} below minimum bet size "
                    f"${self.config.bet_size_low_balance_normal} — halting.",
                    level=40,
                )
                self._killed = True
                return
        elif self.config.mode == "live" and not self._polymarket:
            log_event(
                logger,
                "startup_no_wallet_live_halt",
                "LIVE mode requested but Polymarket client not initialized — halting.",
                level=40,
            )
            self._killed = True
            return

        # Start BTC price feed
        await self._btc_feed.start()

        # Start provider context cache refresh loop
        if self.config.data_providers:
            self._provider_cache_task = self._spawn(self._provider_cache_loop(), "provider_cache_loop")

        # Start CLOB WebSocket feed (if enabled)
        if self.config.clob_ws_enabled:
            self._clob_ws_task = self._spawn(self._clob_ws_loop(), "clob_ws_loop")
            log_event(logger, "clob_ws_task_created", "[CLOB/WS] Task created")
        else:
            log_event(logger, "clob_ws_disabled", "[CLOB/WS] Disabled — using REST polling")

        # Start heartbeat loop to keep maker orders alive
        self._heartbeat_task = self._spawn(self._heartbeat_loop(), "heartbeat_loop")
        log_event(logger, "heartbeat_started", "Heartbeat loop started (5s interval)")

        # CLOB REST session
        self._clob_http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=4.0),
            headers={"User-Agent": "PolyGuez/1.0"},
        )

        # Position recovery: if last trade is pending, reconstruct position and settle
        await self._recover_pending_position()
        # Multi-position crash recovery: if the crash left more than one pending
        # trade in rolling_stats (e.g. traded A then B, crashed while B still
        # pending), `_recover_pending_position` above only rebuilds `self._position`
        # for the most recent one. Resolve any OTHER pending trades (via Gamma)
        # before the first cycle starts, rather than letting them sit pending
        # until cycle 1 runs `_resolve_pending_settlements`.
        await self._resolve_pending_settlements()

        while not self._killed:
            self._loop_heartbeat_ts = time.time()
            try:
                await asyncio.wait_for(self._cycle(), timeout=360.0)
            except asyncio.TimeoutError:
                log_event(logger, "cycle_hung", "Cycle timed out after 360s — forcing recovery", level=40)
                self._current_market = None
                self._position = None
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log_event(logger, "cycle_error", f"Cycle error: {exc}", level=40)
                await asyncio.sleep(5)

        log_event(logger, "runner_stop", "PolyGuez stopped")
        save_rolling_stats(self._rolling_stats)

    async def _cycle(self):
        """One full market cycle: discover → trade → settle."""
        # Resolve any pending settlements from prior cycles
        await self._resolve_pending_settlements()

        # Reset daily P&L if new day
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._rolling_stats.daily_pnl_reset_utc != today:
            self._rolling_stats.daily_pnl = 0.0
            self._rolling_stats.daily_notional = 0.0
            self._rolling_stats.daily_pnl_reset_utc = today
            log_event(logger, "daily_reset", "Daily P&L reset")

        # Update USDC balance
        await self._refresh_balance()
        self._rolling_stats.max_capital_at_risk = calculate_max_capital_at_risk(
            self._usdc_balance, self.config
        )

        # Check if balance allows trading (must cover smallest possible bet)
        min_bet = self.config.bet_size_low_balance_normal
        if self._usdc_balance < min_bet:
            log_event(logger, "balance_halt", f"Balance ${self._usdc_balance:.2f} < min bet ${min_bet}")
            await asyncio.sleep(30)
            return

        # Discover active 5-min BTC market
        self._current_market = await self._discover_market()
        if not self._current_market:
            self._discovery_misses += 1
            await asyncio.sleep(5)
            return

        market_id = str(self._current_market.get("id", ""))
        question = self._current_market.get("question", "")
        expiry_dt = MarketDiscovery.get_market_expiry(self._current_market)
        yes_token, no_token = MarketDiscovery.get_market_token_ids(self._current_market)

        log_event(logger, "token_ids", f"Extracted token IDs: yes={yes_token}, no={no_token}", {
            "raw_clobTokenIds": self._current_market.get("clobTokenIds"),
            "raw_outcomes": self._current_market.get("outcomes"),
        })

        if not yes_token or not no_token:
            log_event(logger, "market_skip", f"No token IDs for market {market_id}")
            await asyncio.sleep(5)
            return

        log_event(logger, "market_active", f"Tracking: {question}", {
            "market_id": market_id,
            "expiry": str(expiry_dt),
        })

        # P2B = Chainlink price at eventStartTime
        # LATENCY-TASK-2: The buffer-anchored path is the only trustworthy
        # source of P2B. The old code fell back to "current Chainlink" when
        # the buffer had nothing near eventStartTime — that produced a
        # strike that wasn't anchored to event start and silently degraded
        # edge quality. We now skip the cycle instead, and also halt after
        # `p2b_consecutive_failure_halt` in a row (same halt path as the
        # existing "no Chainlink at all" branch).
        event_start_dt = MarketDiscovery.get_event_start_time(self._current_market)
        self._p2b_offset_seconds = None  # LATENCY-TASK-2 observability
        if event_start_dt:
            event_start_ts = event_start_dt.timestamp()
            cl_price, cl_ts, cl_offset = self._btc_feed.get_chainlink_price_at(event_start_ts)
            max_offset = self.config.max_p2b_chainlink_offset_seconds

            if cl_price is not None and cl_price > 0 and cl_offset is not None and cl_offset <= max_offset:
                self._price_to_beat = cl_price
                self._p2b_source = "chainlink_buffer"
                self._p2b_consecutive_failures = 0
                self._p2b_offset_seconds = round(cl_offset, 2)
                log_event(logger, "price_to_beat",
                    f"P2B from Chainlink buffer: ${cl_price:.2f} (offset: {cl_offset:.1f}s from eventStartTime)",
                    {"source": "chainlink_buffer",
                     "offset_seconds": round(cl_offset, 2),
                     "max_offset": max_offset})

                # Cross-check buffer P2B against current Chainlink.
                # Tolerance is still flat USD today; sigma-scaling is a
                # candidate follow-up (see LATENCY-TASK-2 notes in PR).
                current_cl, _ = self._btc_feed.get_chainlink_price()
                if current_cl and current_cl > 0:
                    divergence = abs(self._price_to_beat - current_cl)
                    tolerance = 50.0 if cl_offset < 5.0 else 150.0
                    self._p2b_cross_check_passed = divergence <= tolerance
                    self._p2b_cross_check_divergence = round(divergence, 2)
                    log_event(logger, "p2b_cross_check",
                        f"Cross-check: passed={self._p2b_cross_check_passed}, divergence=${divergence:.2f}, tolerance=${tolerance:.0f} (buffer offset={cl_offset:.1f}s)")
                else:
                    self._p2b_cross_check_passed = True
                    self._p2b_cross_check_divergence = 0.0
            else:
                # LATENCY-TASK-2: refuse to fabricate P2B from "current"
                # Chainlink. Log why and skip the cycle. Halts after N in
                # a row, same policy as the "no Chainlink at all" branch.
                if cl_price is None or cl_price <= 0:
                    reason = "no_buffer_sample"
                    offset_str = "n/a"
                else:
                    reason = "offset_too_large"
                    offset_str = f"{cl_offset:.1f}s"
                log_event(logger, "p2b_offset_too_large",
                    f"P2B Chainlink offset={offset_str} > threshold={max_offset:.1f}s "
                    f"(reason={reason}); skipping cycle",
                    {"reason": reason,
                     "offset_seconds": round(cl_offset, 2) if cl_offset is not None else None,
                     "threshold_seconds": max_offset},
                    level=30)
                self._p2b_consecutive_failures += 1
                self._rolling_stats.p2b_skips += 1
                self._current_market = None
                if self._p2b_consecutive_failures >= self.config.p2b_consecutive_failure_halt:
                    self._killed = True
                    self._kill_timestamp = datetime.now(timezone.utc).isoformat()
                return
        else:
            log_event(logger, "p2b_no_start_time", "No eventStartTime in market dict", level=30)
            self._p2b_consecutive_failures += 1
            self._current_market = None
            return

        # Wait for BTC feed buffer
        if not self._btc_feed.is_ready():
            log_event(logger, "btc_buffer_filling", "Waiting for BTC price buffer")
            while not self._btc_feed.is_ready() and not self._killed:
                await asyncio.sleep(1)

        # Entry window loop
        entered = await self._entry_window(market_id, yes_token, no_token, expiry_dt)

        # Hold loop (if we entered a position)
        if entered and self._position:
            await self._hold_loop(expiry_dt, yes_token, no_token)

        # Wait for settlement — short wait for Gamma to mark market as closed
        if expiry_dt:
            wait = (expiry_dt - datetime.now(timezone.utc)).total_seconds()
            if wait > 0:
                log_event(logger, "settlement_wait", f"Waiting {min(wait + 5, 30):.0f}s for market to settle")
                await asyncio.sleep(min(wait + 5, 30))
            else:
                # Market already expired, brief wait for settlement data
                await asyncio.sleep(3)

        # ── BTC-feed-based shadow settlement (authoritative for BTC up/down markets) ──
        # Runs every cycle at market close, regardless of whether we held a real
        # position. Uses the same Chainlink feed that drives entry decisions, so
        # settlement is independent of Polymarket resolution timing (which lags
        # and was the root cause of 2961 V5 shadow trades sitting unsettled).
        if self._price_to_beat is not None and self._price_to_beat > 0:
            try:
                cl_close = None
                cl_close_offset = None
                if expiry_dt is not None:
                    expiry_ts = expiry_dt.timestamp()
                    cl_close, _cl_ts, cl_close_offset = self._btc_feed.get_chainlink_price_at(expiry_ts)
                if cl_close is None or cl_close <= 0:
                    # Fall back to most recent chainlink tick (we've just waited past expiry)
                    fallback_price, _age = self._btc_feed.get_chainlink_price()
                    if fallback_price and fallback_price > 0:
                        cl_close = fallback_price
                        cl_close_offset = None
                if cl_close and cl_close > 0:
                    settle_shadow_trades(
                        market_id,
                        btc_close_price=cl_close,
                        strike=self._price_to_beat,
                        # LATENCY-TASK-7: offset between the Chainlink
                        # tick used as settlement price and expiry.
                        # None = fell back to live chainlink (unknown
                        # offset); preserved so the downstream filter
                        # can distinguish both cases.
                        cl_close_offset_seconds=cl_close_offset,
                    )
                    offset_str = f"offset={cl_close_offset:.1f}s" if cl_close_offset is not None else "offset=live"
                    log_event(logger, "shadow_settled_btc_feed",
                        f"[SHADOW] BTC-feed settlement fired: close=${cl_close:.2f} strike=${self._price_to_beat:.2f} ({offset_str})")
                else:
                    log_event(logger, "shadow_settle_btc_unavailable",
                        "[SHADOW] BTC feed unavailable at expiry — will rely on Polymarket fallback",
                        level=30)
            except Exception as exc:
                log_event(logger, "shadow_settle_btc_error", f"BTC-feed shadow settlement failed: {exc}", level=30)

        # Check settlement
        if self._position:
            await self._settle(market_id)
        else:
            # Polymarket-resolution fallback: covers cases where BTC feed was
            # unavailable above. If BTC-feed settlement already ran, this finds
            # zero unsettled shadows and is a no-op.
            try:
                settled_mkt = await settle_with_retry(self._discovery, market_id, self.config)
                if settled_mkt and settled_mkt.get("closed"):
                    outcome_prices_raw = settled_mkt.get("outcomePrices", "")
                    if isinstance(outcome_prices_raw, str):
                        try:
                            outcome_prices_raw = json.loads(outcome_prices_raw)
                        except (json.JSONDecodeError, TypeError):
                            outcome_prices_raw = []
                    if isinstance(outcome_prices_raw, list) and len(outcome_prices_raw) >= 2:
                        settle_shadow_trades(market_id, outcome_prices_raw)
                        log_event(logger, "shadow_settled_no_position",
                            f"[SHADOW] Polymarket-fallback settlement for market {market_id} (no real position)")
            except Exception as exc:
                log_event(logger, "shadow_settle_error", f"Shadow settlement failed: {exc}")

        # Persist stats and reset for next cycle
        save_rolling_stats(self._rolling_stats)
        old_question = self._current_market.get("question", "") if self._current_market else ""
        self._current_market = None
        self._current_signal = None
        self._current_depth = 0.0
        self._last_llm_verdict = ""
        self._last_llm_reason = ""
        self._last_llm_provider = ""
        self._price_to_beat = None
        self._p2b_source = "none"
        self._p2b_cross_check_passed = None
        self._p2b_cross_check_divergence = None
        self._p2b_offset_seconds = None  # LATENCY-TASK-2 reset
        log_event(logger, "cycle_complete", f"Market cycle complete: {old_question}. Looking for next market...")

    # -- Sub-loops ---------------------------------------------------------

    async def _entry_window(self, market_id, yes_token, no_token, expiry_dt):
        """Evaluate entry signal every ~1s during the entry window."""
        window_start = time.time()

        # Subscribe CLOB WS to new market tokens
        await self._subscribe_clob_ws(yes_token, no_token)

        while not self._killed:
            if expiry_dt:
                remaining = (expiry_dt - datetime.now(timezone.utc)).total_seconds()
                elapsed = max(0.0, 300.0 - remaining)
                if remaining < 30:
                    log_event(logger, "entry_skip", f"Too close to expiry ({remaining:.0f}s remaining), skipping entry")
                    return False
                if remaining <= 0:
                    log_event(logger, "market_expired", f"Market {market_id} has expired")
                    return False
            else:
                # No expiry info — use wall-clock timeout (6 minutes max)
                elapsed = time.time() - window_start
                if elapsed > 360:
                    log_event(logger, "entry_timeout", f"Entry window timed out after {elapsed:.0f}s (no expiry data)")
                    return False

            # Poll CLOB prices
            yes_price, no_price, spread = await self._poll_clob(yes_token, no_token)

            # Track complete-set edge for Phase 2 verification
            # bid_yes ≈ yes_price (CLOB mid approximation from WS/REST)
            # bid_no  ≈ no_price
            _cs_edge = round(1.0 - (yes_price + no_price), 4) if yes_price > 0 and no_price > 0 else None

            # Null-guard: get_price() returns None when buffer is empty
            btc_price_raw = self._btc_feed.get_price()
            if btc_price_raw is None or btc_price_raw == 0:
                log_event(logger, "price_feed_stale", "BTC price is None/0 — skipping signal evaluation", level=40)
                self._current_signal = SignalState(price_feed_ok=False)
                await asyncio.sleep(self.config.clob_poll_interval)
                continue

            # Feed BTC price into volatility tracker
            self._vol_tracker.update(btc_price_raw)

            cl_price, cl_age = self._btc_feed.get_chainlink_price()

            # Null-guard: get_velocity() returns None when buffer is empty
            btc_velocity = self._btc_feed.get_velocity()
            if btc_velocity is None:
                await asyncio.sleep(self.config.clob_poll_interval)
                continue

            # LATENCY-TASK-3: granular feed freshness gate. Ages past the
            # per-source thresholds flip price_feed_ok to False via the
            # combined flag below, and the specific reasons get logged to
            # signal_log so we can answer "which feed was stale?" after
            # the fact. RTDS is optional — only flagged when it has ever
            # delivered a sample (age >= 0) but is now stale.
            _binance_age = self._btc_feed.binance_msg_age
            _rtds_age = self._btc_feed.rtds_msg_age
            _feed_lag_reasons = []
            if _binance_age < 0 or _binance_age > self.config.max_binance_age_seconds:
                _feed_lag_reasons.append("binance_stale")
            if _rtds_age >= 0 and _rtds_age > self.config.max_rtds_age_seconds:
                _feed_lag_reasons.append("rtds_stale")
            if (
                cl_price is None
                or cl_age is None
                or cl_age < 0
                or cl_age > self.config.max_chainlink_age_seconds
            ):
                _feed_lag_reasons.append("chainlink_stale")
            _feed_lag_ok = not _feed_lag_reasons
            _feed_lag_ms = round(max(
                _binance_age if _binance_age >= 0 else 0.0,
                _rtds_age if _rtds_age >= 0 else 0.0,
            ) * 1000.0, 1)
            _price_feed_healthy = self._btc_feed.price_feed_ok and _feed_lag_ok

            # Evaluate signal first with depth=-1 (skip gate) to get delta direction
            signal = evaluate_entry_signal(
                btc_velocity=btc_velocity,
                btc_price=btc_price_raw,
                yes_price=yes_price,
                no_price=no_price,
                spread=spread,
                elapsed_seconds=elapsed,
                usdc_balance=self._usdc_balance,
                config=self.config,
                rolling_stats=self._rolling_stats,
                has_position=self._position is not None,
                open_position_count=1 if self._position else 0,
                chainlink_price=cl_price,
                chainlink_age=cl_age,
                binance_chainlink_gap=self._btc_feed.get_binance_chainlink_gap(),
                clob_depth=-1.0,  # Sentinel: skip depth gate in first pass
                price_to_beat=self._price_to_beat,
                price_feed_ok=_price_feed_healthy,
            )

            # Fetch depth using signal's delta-based direction (not velocity direction)
            target_token = yes_token if signal.direction == "up" else no_token
            depth = await self._fetch_depth(target_token)
            self._current_depth = depth

            # Update depth_ok on the signal using real depth
            signal.depth_ok = True if depth < 0 else depth >= self.config.min_clob_depth

            # LATENCY-TASK-2: mirror this cycle's P2B quality onto the
            # signal so evaluate_entry_signal's all_conditions_met check
            # can block when the strike wasn't cleanly anchored. In
            # practice this is belt-and-suspenders — _cycle already skips
            # when P2B derivation fails — but it keeps the invariant
            # explicit inside evaluate_entry_signal and makes the
            # block reason visible in signal_log.
            signal.p2b_ok = (
                self._p2b_source == "chainlink_buffer"
                and (self._p2b_cross_check_passed is not False)
            )

            # LATENCY-TASK-4: CLOB WS freshness + heartbeat health.
            # clob_msg_age measures seconds since the last CLOB WS
            # message; above clob_ws_stale_threshold we consider the
            # quotes we just evaluated against untrustworthy. The
            # heartbeat gate blocks entries when Polymarket is about to
            # cancel our maker orders for inactivity (~10s timeout).
            _now = time.time()
            if self._clob_ws_last_msg > 0:
                _clob_msg_age = _now - self._clob_ws_last_msg
            else:
                _clob_msg_age = -1.0  # never received
            signal.clob_fresh_ok = (
                self.config.clob_ws_enabled is False
                or (_clob_msg_age >= 0 and _clob_msg_age <= self.config.clob_ws_stale_threshold)
            )
            if self._last_heartbeat_sent_ts > 0:
                _heartbeat_age = _now - self._last_heartbeat_sent_ts
            else:
                _heartbeat_age = -1.0
            # Heartbeat never sent = treat as stale ONLY if we're past the
            # startup grace period (first 15s of runner life). That grace
            # avoids gating the first-cycle scan on a task that hasn't
            # tick-one'd yet.
            # If the installed py_clob_client version doesn't support
            # post_heartbeat (e.g. v0.17.5), bypass the gate entirely — the
            # server won't cancel maker orders that were never registered via
            # a heartbeat-capable session.
            if self._heartbeat_supported is False:
                signal.heartbeat_ok = True
            elif self._last_heartbeat_sent_ts <= 0 and (_now - self._runner_start_ts) < 15.0:
                signal.heartbeat_ok = True
            else:
                signal.heartbeat_ok = (
                    _heartbeat_age >= 0
                    and _heartbeat_age <= self.config.heartbeat_stale_threshold
                )
            # Downstream _clob_ok drives the dashboard connection dot;
            # keep it coherent with the hard gate so operators see the
            # same view as the runner.
            if not signal.heartbeat_ok:
                self._clob_ok = False

            self._current_signal = signal

            _size_multiplier = get_daily_loss_size_multiplier(self._rolling_stats, self.config, self._usdc_balance)
            bet_size = calculate_position_size(self._usdc_balance, self.config, edge=signal.edge, depth=depth, size_multiplier=_size_multiplier)
            is_strong = signal.edge >= self.config.strong_edge_threshold and depth >= self.config.strong_depth_threshold
            sig_msg = f"Signal: {signal.all_conditions_met}"
            if signal.all_conditions_met:
                sig_msg += f" → bet=${bet_size:.1f} ({'strong' if is_strong else 'normal'})"
            log_event(logger, "signal_evaluated", sig_msg, {
                "velocity": round(signal.btc_velocity, 6),
                "velocity_source": self._btc_feed.velocity_source,
                "btc_price": round(btc_price_raw, 2),
                "cl_price": round(cl_price, 2),
                "cl_age": round(cl_age, 1),
                "rtds_age": round(self._btc_feed.rtds_msg_age, 1),
                "binance_age": round(self._btc_feed.binance_msg_age, 1),
                "edge": round(signal.edge, 4),
                "required_edge": round(signal.required_edge, 4),
                "spread": round(signal.spread, 4),
                "oracle_gap": round(signal.binance_chainlink_gap, 2),
                "depth": round(depth, 1),
                "elapsed": round(elapsed, 1),
                "bet_size": bet_size,
                "bet_tier": "strong" if is_strong else "normal",
                "conditions": {
                    "price_feed_ok": signal.price_feed_ok,
                    "velocity_ok": signal.velocity_ok,
                    "oracle_gap_ok": signal.oracle_gap_ok,
                    "clob_mispricing_ok": signal.clob_mispricing_ok,
                    "edge_ok": signal.edge_ok,
                    "spread_ok": signal.spread_ok,
                    "depth_ok": signal.depth_ok,
                    "clob_consensus_ok": signal.clob_consensus_ok,
                    "no_position": signal.no_position,
                    "cooldown_ok": signal.cooldown_ok,
                    "daily_loss_ok": signal.daily_loss_ok,
                    "balance_ok": signal.balance_ok,
                    "position_limit_ok": signal.position_limit_ok,
                },
            })

            trade_fired = False
            if signal.all_conditions_met:
                trade_fired = await self._attempt_entry(signal, market_id, yes_token, no_token)

            # Supabase signal log (fire-and-forget)
            _v2_conds = [
                signal.price_feed_ok,
                signal.terminal_edge_ok, signal.delta_magnitude_ok, signal.edge_ok,
                signal.spread_ok, signal.depth_ok, signal.clob_consensus_ok, signal.no_position,
                signal.cooldown_ok, signal.daily_loss_ok, signal.balance_ok,
                signal.position_limit_ok,
                getattr(signal, 'time_of_day_ok', True),
                getattr(signal, 'entry_price_ok', True),
                getattr(signal, 'direction_ok', True),
            ]
            # ── Vol & CLOB indicators for signal_log ──
            _sigma = self._vol_tracker.sigma()
            # Always use YES price for BS digital-call inversion
            # (formula prices P(S>K); NO side = 1 - P(S>K))
            _token_price = signal.yes_price
            _iv = compute_implied_vol(
                token_price=_token_price,
                spot=cl_price,
                strike=signal.p2b_value,
                seconds_remaining=(300 - elapsed),
                sigma_hint=_sigma,
            ) if _sigma is not None else None
            _clob_spread = getattr(signal, "clob_spread_raw", None)
            _depth_at_ask = getattr(signal, "depth_at_ask_raw", None)

            # Throttle signal logging — configurable interval (default 2.5s)
            _log_interval = getattr(self.config, 'signal_log_interval', 2.5)
            _log_this_signal = (int(elapsed * 10) % int(_log_interval * 10) == 0) or signal.all_conditions_met or trade_fired
            if _log_this_signal:
                # Build blocking conditions string for this signal.
                # LATENCY-TASK-3: prefer granular feed-lag reasons
                # (binance_stale / rtds_stale / chainlink_stale) over the
                # single coarse "price_feed" reason when a specific feed
                # tripped a threshold.
                _blocking = []
                if _feed_lag_reasons:
                    _blocking.extend(_feed_lag_reasons)
                elif not signal.price_feed_ok:
                    _blocking.append("price_feed")
                if not getattr(signal, 'chainlink_fresh_ok', True) and "chainlink_stale" not in _blocking:
                    _blocking.append("chainlink_stale")
                if not getattr(signal, 'p2b_ok', True): _blocking.append("p2b_stale")  # LATENCY-TASK-2
                if not getattr(signal, 'clob_fresh_ok', True): _blocking.append("clob_stale")  # LATENCY-TASK-4
                if not getattr(signal, 'heartbeat_ok', True): _blocking.append("heartbeat_stale")  # LATENCY-TASK-4
                if not signal.terminal_edge_ok: _blocking.append("terminal_edge")
                if not signal.delta_magnitude_ok: _blocking.append("delta_magnitude")
                if not signal.edge_ok: _blocking.append("edge")
                if not signal.spread_ok: _blocking.append("spread")
                if not signal.depth_ok: _blocking.append("depth")
                if not signal.clob_consensus_ok: _blocking.append("clob_consensus")
                if not signal.no_position: _blocking.append("has_position")
                if not signal.cooldown_ok: _blocking.append("cooldown")
                if not signal.daily_loss_ok: _blocking.append("daily_loss")
                if not signal.balance_ok: _blocking.append("balance")
                if not signal.position_limit_ok: _blocking.append("position_limit")
                if not getattr(signal, 'time_of_day_ok', True): _blocking.append("time_of_day")
                if not getattr(signal, 'entry_price_ok', True): _blocking.append("entry_price")
                if not getattr(signal, 'direction_ok', True): _blocking.append("direction")

                log_signal({
                    "signal_id": signal.signal_id,
                    "market_id": market_id,
                    "market_question": self._current_market.get("question", "") if self._current_market else "",
                    "elapsed_seconds": round(elapsed, 1),
                    "btc_price": self._btc_feed.get_price() or 0.0,
                    "chainlink_price": cl_price,
                    "chainlink_age_seconds": round(cl_age, 1),
                    # LATENCY-TASK-3: worst-case BTC-feed lag in ms for
                    # post-hoc PnL-vs-latency analysis. Max of the two
                    # primary BTC feeds (Binance WS, RTDS). Chainlink
                    # age has its own column above.
                    "feed_lag_ms": _feed_lag_ms,
                    # LATENCY-TASK-4: CLOB WS message age in ms at the
                    # moment this signal was evaluated. Negative age
                    # encodes "never received" and is logged as None.
                    "clob_msg_age_ms": (
                        round(_clob_msg_age * 1000.0, 1) if _clob_msg_age >= 0 else None
                    ),
                    # LATENCY-TASK-1: whether MarketDiscovery's alignment
                    # predicate accepted the current market. Always True
                    # under the new path because misaligned candidates
                    # never reach this point — logging it anyway gives
                    # a dead-man's switch if the invariant ever regresses.
                    "alignment_ok": bool(self._current_market.get("_alignment_ok", True)) if self._current_market else None,
                    # LATENCY-TASK-2: P2B anchoring quality.
                    "p2b_ok": bool(getattr(signal, "p2b_ok", True)),
                    "p2b_offset_seconds": self._p2b_offset_seconds,
                    "blocking_conditions": ",".join(_blocking) if _blocking else "",
                    "in_trade": self._position is not None,
                    "strike_delta": signal.strike_delta,
                    "terminal_probability": signal.terminal_probability,
                    "terminal_edge": signal.terminal_edge,
                    # LATENCY-TASK-6: the effective fair-value edge
                    # threshold this signal was judged against, so we
                    # can answer "was the gate set high enough at that
                    # point in the window?" without re-deriving from
                    # elapsed_seconds + config.
                    "required_edge": getattr(signal, "required_edge", None),
                    # Fee-adjusted edge (log-only per audit Phase 1.1). Gate
                    # still uses terminal_edge until k-recal Phase 4 lands.
                    "net_edge": getattr(signal, "net_edge", None),
                    "entry_side": signal.direction,
                    "yes_price": signal.yes_price,
                    "no_price": signal.no_price,
                    # MODEL-04: explicit "this was the quote at signal-eval
                    # time" so post-live slippage analysis can cleanly
                    # compute realized slippage as
                    #   fill_price (trade_log) - signal_eval_yes_price
                    # without ambiguity about which yes_price is which.
                    "signal_eval_yes_price": signal.yes_price,
                    "signal_eval_no_price": signal.no_price,
                    "spread": signal.spread,
                    "conditions_met": sum(_v2_conds),
                    "all_conditions_met": signal.all_conditions_met,
                    "trade_fired": trade_fired,
                    "sigma_realized": round(_sigma, 4) if _sigma is not None else None,
                    "implied_vol": round(_iv, 4) if _iv is not None else None,
                    "clob_spread": round(_clob_spread, 4) if _clob_spread is not None else None,
                    "depth_at_ask": round(_depth_at_ask, 2) if _depth_at_ask is not None else None,
                    "bid_yes": round(yes_price, 4) if yes_price > 0 else None,
                    "bid_no": round(no_price, 4) if no_price > 0 else None,
                    "complete_set_edge": _cs_edge,
                    "mode": self.config.mode,
                }, session_tag=self.config.session_tag)

            # Shadow trade: log what WOULD have happened when core edge exists
            # but other conditions block. Gives outcome data without trading.
            if (
                not trade_fired
                and signal.terminal_edge_ok
                and signal.edge_ok
                and not signal.all_conditions_met
            ):
                blocking = []
                if not signal.price_feed_ok: blocking.append("price_feed")
                if hasattr(signal, 'chainlink_fresh_ok') and not signal.chainlink_fresh_ok: blocking.append("chainlink_stale")
                if not signal.velocity_ok: blocking.append("velocity_ok")
                if not signal.oracle_gap_ok: blocking.append("oracle_gap_ok")
                if not signal.delta_magnitude_ok: blocking.append("delta_magnitude_ok")
                if not signal.spread_ok: blocking.append("spread_ok")
                if not signal.depth_ok: blocking.append("depth_ok")
                if not signal.clob_consensus_ok: blocking.append("clob_consensus_ok")
                if not signal.no_position: blocking.append("has_position")
                if not signal.cooldown_ok: blocking.append("cooldown")
                if not signal.daily_loss_ok: blocking.append("daily_loss")
                if not signal.balance_ok: blocking.append("balance")
                if not signal.position_limit_ok: blocking.append("position_limit")
                if hasattr(signal, 'time_of_day_ok') and not signal.time_of_day_ok: blocking.append("time_of_day")
                if hasattr(signal, 'entry_price_ok') and not signal.entry_price_ok: blocking.append("entry_price")
                if hasattr(signal, 'direction_ok') and not signal.direction_ok: blocking.append("direction_blocked")

                shadow_entry_price = signal.yes_price if signal.direction == "up" else signal.no_price
                shadow_size = calculate_position_size(self._usdc_balance, self.config, edge=signal.edge, depth=self._current_depth)
                log_shadow_trade({
                    "market_id": market_id,
                    "market_question": self._current_market.get("question", "") if self._current_market else "",
                    "direction": signal.direction,
                    "entry_price": shadow_entry_price,
                    "size_usdc": shadow_size,
                    "edge": round(signal.edge, 4),
                    "terminal_edge": round(signal.terminal_edge, 4),
                    "terminal_probability": round(signal.terminal_probability, 4),
                    "strike_delta": round(signal.strike_delta, 2),
                    "chainlink_price": round(cl_price, 2),
                    "btc_price": round(btc_price_raw, 2),
                    "elapsed_seconds": round(elapsed, 1),
                    "conditions_met": sum(_v2_conds),
                    "conditions_total": len(_v2_conds),
                    "blocking_conditions": ",".join(blocking),
                }, session_tag=self.config.session_tag)

            if trade_fired:
                return True

            await asyncio.sleep(self.config.clob_poll_interval)

        return False

    async def _attempt_entry(self, signal, market_id, yes_token, no_token):
        """Deterministic signal fired — run LLM confirmation then execute."""
        log_event(logger, "signal_fired", f"Deterministic signal FIRED: {signal.direction}")

        # Build CLOB depth summary for LLM context — skip the HTTP call
        # entirely when LLM is disabled since the string is never consumed.
        if self.config.llm_enabled:
            clob_depth = await self._get_clob_depth(
                yes_token if signal.direction == "up" else no_token,
            )
        else:
            clob_depth = ""

        # LLM confirmation — provider context from background cache (not fetched inline)
        _cache = self._provider_context_cache
        _cache_age = time.time() - _cache["fetched_at"] if _cache["fetched_at"] else float("inf")
        _provider_ctx = _cache["data"] if _cache_age <= 60.0 else ""
        _t_llm_start = asyncio.get_running_loop().time()
        verdict, reason, provider, llm_time = await get_llm_confirmation(
            signal, self._rolling_stats, self.config,
            price_to_beat=self._price_to_beat,
            gap_direction=self._btc_feed.get_gap_direction(),
            clob_depth_summary=clob_depth,
            provider_context=_provider_ctx,
        )
        self._last_llm_verdict = verdict
        self._last_llm_reason = reason
        self._last_llm_provider = provider
        self._last_llm_time = llm_time
        _llm_ms = (asyncio.get_running_loop().time() - _t_llm_start) * 1000

        if verdict == "REDUCE-SIZE":
            log_event(logger, "llm_reduce_size", f"LLM REDUCE-SIZE — halving bet: {reason}")

        if verdict == "NO-GO":
            log_event(logger, "trade_skipped", f"Skipped: LLM NO-GO — {reason}")
            return False

        # LATENCY-TASK-5: hard LLM latency cutoff. When the operator has
        # configured max_llm_ms, an LLM call that breached it is treated
        # as a timeout regardless of what the call returned — the
        # downstream order submission would be firing on a verdict that
        # was computed against a market snapshot this stale. Also logs a
        # shadow trade so the outcome is still captured for analysis.
        _max_llm_ms = self.config.max_llm_ms
        if _max_llm_ms is not None and _llm_ms > _max_llm_ms:
            log_event(logger, "hot_path_stale",
                f"LLM latency {_llm_ms:.0f}ms > max_llm_ms={_max_llm_ms:.0f}ms — treating as timeout (no trade)",
                {"llm_ms": round(_llm_ms, 1), "max_llm_ms": _max_llm_ms,
                 "verdict_raw": verdict, "signal_id": signal.signal_id},
                level=40)
            # Shadow-log so we still get outcome data for this would-be trade.
            try:
                _shadow_entry_price = signal.yes_price if signal.direction == "up" else signal.no_price
                _shadow_size = calculate_position_size(
                    self._usdc_balance, self.config,
                    edge=signal.edge, depth=getattr(self, "_current_depth", 0.0),
                )
                log_shadow_trade({
                    "market_id": market_id,
                    "market_question": self._current_market.get("question", "") if self._current_market else "",
                    "direction": signal.direction,
                    "entry_price": _shadow_entry_price,
                    "size_usdc": _shadow_size,
                    "edge": round(signal.edge, 4),
                    "terminal_edge": round(signal.terminal_edge, 4),
                    "terminal_probability": round(signal.terminal_probability, 4),
                    "strike_delta": round(signal.strike_delta, 2),
                    "chainlink_price": round(signal.chainlink_price, 2),
                    "btc_price": round(signal.btc_price, 2),
                    "elapsed_seconds": round(signal.elapsed_seconds, 1),
                    "conditions_met": 0,
                    "conditions_total": 0,
                    "blocking_conditions": "hot_path_stale",
                }, session_tag=self.config.session_tag)
            except Exception:
                pass
            return False

        # Determine position size (fixed tiers)
        depth = getattr(self, '_current_depth', 0.0)
        size = calculate_position_size(self._usdc_balance, self.config, edge=signal.edge, depth=depth)
        is_strong = signal.edge >= self.config.strong_edge_threshold and depth >= self.config.strong_depth_threshold
        log_event(logger, "bet_sizing", f"bet=${size:.1f} ({'strong' if is_strong else 'normal'})")
        if verdict == "REDUCE-SIZE":
            size = round(size * 0.5, 2)
            log_event(logger, "size_reduced", f"LLM REDUCE-SIZE → ${size:.2f}")

        # Pick token
        token_id = yes_token if signal.direction == "up" else no_token
        side = "YES" if signal.direction == "up" else "NO"
        entry_price = signal.yes_price if side == "YES" else signal.no_price

        # Check daily notional limit
        if self.config.max_daily_notional is not None:
            if self._rolling_stats.daily_notional + size > self.config.max_daily_notional:
                log_event(logger, "daily_notional_limit", f"Daily notional ${self._rolling_stats.daily_notional:.2f} + ${size:.2f} would exceed limit ${self.config.max_daily_notional:.2f}")
                return False

        # Execute — pass seconds_remaining so maker timeout adapts to expiry
        # and net_edge so execute_entry can gate FOK fallback in live mode.
        _seconds_remaining = max(1.0, 300.0 - signal.elapsed_seconds)
        _t_order_start = asyncio.get_running_loop().time()
        result = await execute_entry(
            self._polymarket, token_id, size, self.config.mode,
            config=self.config,
            seconds_remaining=_seconds_remaining,
            net_edge=getattr(signal, "net_edge", 0.0),
        )
        _order_ms = (asyncio.get_running_loop().time() - _t_order_start) * 1000
        _total_ms = _llm_ms + _order_ms
        # LATENCY-TASK-5: classify every entry into a coarse bucket so
        # downstream analysis can join PnL against latency without
        # bucketing by hand. Buckets mirror the task spec.
        if _total_ms < 200:
            _latency_bucket = "<200"
        elif _total_ms < 500:
            _latency_bucket = "200-500"
        elif _total_ms < 1000:
            _latency_bucket = "500-1000"
        else:
            _latency_bucket = ">1000"
        _hot_path_stale = _total_ms > self.config.max_total_hot_path_ms
        log_event(logger, "hot_path_timing",
            f"LLM={_llm_ms:.0f}ms order={_order_ms:.0f}ms total={_total_ms:.0f}ms bucket={_latency_bucket}"
            + (" [HOT_PATH_STALE]" if _hot_path_stale else ""),
            level=40 if _hot_path_stale else 20)

        # Store timing for log_trade at settlement
        self._last_entry_llm_ms = _llm_ms
        self._last_entry_order_ms = _order_ms
        self._last_entry_total_ms = _total_ms
        self._last_entry_latency_bucket = _latency_bucket
        self._last_entry_hot_path_stale = _hot_path_stale
        # MODEL-02: capture fee data from the CLOB executor response.
        # In dry-run the response contains fee_paid=0.0 and taker_maker="simulated".
        # In live mode the response reflects the actual maker/taker outcome.
        try:
            _raw_fee = result.get("fee_paid")
            self._last_entry_fee_paid = float(_raw_fee) if _raw_fee is not None else 0.0
        except (TypeError, ValueError):
            self._last_entry_fee_paid = 0.0
        self._last_entry_taker_maker = result.get("taker_maker") or "simulated"
        try:
            _raw_price = result.get("price")
            self._last_entry_fill_price = float(_raw_price) if _raw_price is not None else float(entry_price or 0.0)
        except (TypeError, ValueError):
            self._last_entry_fill_price = float(entry_price or 0.0)

        if result["status"] == "error":
            log_event(logger, "entry_failed", f"Entry failed: {result.get('error', '')}")
            return False

        self._position = PositionState(
            side=side,
            entry_price=entry_price,
            entry_time=datetime.now(timezone.utc).isoformat(),
            market_id=market_id,
            token_id=token_id,
            size_usdc=size,
            price_to_beat=self._price_to_beat,
        )

        self._rolling_stats.daily_notional += size

        log_event(logger, "position_entered", f"Entered {side} @ {entry_price:.4f}, size=${size:.2f}", {
            "market_id": market_id,
            "token_id": token_id,
            "mode": self.config.mode,
        })
        return True

    async def _hold_loop(self, expiry_dt, yes_token=None, no_token=None):
        """Monitor position for emergency exit until expiry."""
        entry_direction = "up" if self._position.side == "YES" else "down"

        while not self._killed and self._position:
            if expiry_dt:
                remaining = (expiry_dt - datetime.now(timezone.utc)).total_seconds()
                if remaining < 5:
                    break  # Let it settle

            # Keep CLOB prices live for dashboard
            if yes_token and no_token:
                yes_price, no_price, spread = await self._poll_clob(yes_token, no_token)
                if self._current_signal and yes_price > 0 and no_price > 0:
                    self._current_signal.yes_price = yes_price
                    self._current_signal.no_price = no_price
                    self._current_signal.spread = spread

            velocity = self._btc_feed.get_velocity()
            if check_emergency_exit(
                velocity, entry_direction, self.config,
                chainlink_price=self._btc_feed.get_chainlink_price()[0],
                price_to_beat=self._position.price_to_beat,
            ):
                result = await execute_emergency_exit(
                    self._polymarket, self._position, self.config.mode,
                )
                # Record as emergency exit
                # Fetch CLOB mid price for accurate emergency exit PnL
                try:
                    loop = asyncio.get_event_loop()
                    book = await loop.run_in_executor(None, self._polymarket.client.get_order_book, self._position.token_id)
                    log_event(logger, "emergency_exit_token_id_used", f"Used token_id={self._position.token_id} for exit order book")
                    best_bid = float(book.get("bids", [{}])[0].get("price", 0))
                    best_ask = float(book.get("asks", [{}])[0].get("price", 0))
                    mid_price = (best_bid + best_ask) / 2.0 if best_bid and best_ask else 0.0
                    if mid_price > 0:
                        pnl = round(self._position.size_usdc * (mid_price / self._position.entry_price - 1.0), 4)
                    else:
                        pnl = -self._position.size_usdc
                except Exception:
                    pnl = -self._position.size_usdc
                record = TradeRecord(
                    market_id=self._position.market_id,
                    side=self._position.side,
                    entry_price=self._position.entry_price,
                    size_usdc=self._position.size_usdc,
                    pnl=pnl,
                    outcome="emergency-exit",
                    reason="Velocity reversal exceeded threshold",
                    llm_verdict=self._last_llm_verdict,
                    llm_reason=self._last_llm_reason,
                    llm_provider=self._last_llm_provider,
                )
                self._rolling_stats.trades.append(record)
                # COR-05: `daily_pnl += pnl` + `simulated_balance = ...`
                # used to be on separate lines here (pnl recorded, balance
                # updated only on the dry-run path after the log_trade flush).
                # `apply_pnl` now ties them into one call placed AFTER the
                # log_trade/flush below, so a crash between them can't leave
                # the invariant broken. See the call below near save_rolling_stats.

                # Supabase trade log (fire-and-forget)
                entry_time = self._position.entry_time or ""
                duration = 0.0
                if entry_time:
                    try:
                        duration = (datetime.now(timezone.utc) - datetime.fromisoformat(entry_time)).total_seconds()
                    except (ValueError, TypeError):
                        pass
                # COR-01: emergency-exit path — same ordering as _settle.
                # Submit Supabase log BEFORE clearing self._position so a
                # crash in this window does not lose the exit record.
                emergency_market_id = self._position.market_id
                if emergency_market_id in self._settled_market_ids:
                    logger.warning(
                        f"[EMERGENCY-EXIT] market_id={emergency_market_id} already "
                        "settled in this process — skipping duplicate."
                    )
                    self._position = None
                    return
                log_trade({
                    "signal_id": getattr(self._current_signal, 'signal_id', '') if self._current_signal else '',
                    "market_id": emergency_market_id,
                    "market_question": self._current_market.get("question", "") if self._current_market else "",
                    "side": "up" if self._position.side == "YES" else "down",
                    "entry_price": self._position.entry_price,
                    "exit_price": 0.0,
                    "size_usdc": self._position.size_usdc,
                    "pnl": pnl,
                    "llm_verdict": self._last_llm_verdict,
                    "llm_reason": self._last_llm_reason,
                    "llm_provider": self._last_llm_provider,
                    "outcome": "emergency-exit",
                    "llm_response_ms": round(self._last_entry_llm_ms, 1),
                    "order_submit_ms": round(self._last_entry_order_ms, 1),
                    "total_latency_ms": round(self._last_entry_total_ms, 1),
                    # LATENCY-TASK-5: coarse bucket + hot-path-stale flag so
                    # post-hoc PnL vs. latency joins are cheap in SQL.
                    "latency_bucket": getattr(self, "_last_entry_latency_bucket", None),
                    "hot_path_stale": getattr(self, "_last_entry_hot_path_stale", False),
                    "mode": self.config.mode,
                    "terminal_edge": getattr(self._current_signal, 'terminal_edge', None) if self._current_signal else None,
                    "net_edge": getattr(self._current_signal, 'net_edge', None) if self._current_signal else None,
                    # MODEL-02: real fee + fill-type from execute_entry.
                    "fee_paid": self._last_entry_fee_paid,
                    "taker_maker": self._last_entry_taker_maker,
                    "fill_price": self._last_entry_fill_price,
                }, session_tag=self.config.session_tag)
                # Flush barrier (same pattern as _settle): best-effort, 5s max.
                try:
                    _log_executor.submit(lambda: None).result(timeout=5.0)
                except Exception:
                    pass
                # COR-05: atomic PnL + balance update (replaces the old
                # two-liner). `apply_pnl` updates daily_pnl always and
                # simulated_balance only in dry-run — same net effect as
                # the previous code, but one assignment instead of two.
                self._rolling_stats.apply_pnl(pnl, self.config.mode)
                # COR-03: persist unconditionally before mutating position.
                save_rolling_stats(self._rolling_stats)
                self._settled_market_ids.add(emergency_market_id)
                self._position = None
                self._apply_cooldown()
                return

            await asyncio.sleep(self.config.clob_poll_interval)

    async def _settle(self, market_id):
        """FIX 3: Settlement with retry instead of defaulting to loss."""
        if not self._position:
            return

        settled_market = await settle_with_retry(
            self._discovery, market_id, self.config,
        )

        outcome_str = ""
        pnl = 0.0

        if settled_market and settled_market.get("closed"):
            outcome_prices = settled_market.get("outcomePrices", "")
            if isinstance(outcome_prices, str):
                try:
                    outcome_prices = json.loads(outcome_prices)
                except (json.JSONDecodeError, TypeError):
                    outcome_prices = []

            if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                yes_settled = float(outcome_prices[0])
                no_settled = float(outcome_prices[1])
                # Verify prices are actually resolved (near 0 or 1), not pre-resolution
                if not any(abs(float(p) - 0.5) > 0.40 for p in outcome_prices):
                    log_event(logger, "settlement_pre_resolution",
                        f"Market {market_id} closed but prices not resolved: {outcome_prices}")
                    outcome_str = "pending"
                    pnl = 0.0
                else:
                    settled_price = yes_settled if self._position.side == "YES" else no_settled

                    if settled_price > 0.5:
                        pnl = round(self._position.size_usdc * (1.0 / self._position.entry_price - 1.0), 4)
                        outcome_str = "win"
                    else:
                        pnl = -self._position.size_usdc
                        outcome_str = "loss"

                    # Settle shadow trades for this market too
                    settle_shadow_trades(market_id, outcome_prices)
            else:
                outcome_str = "pending"
                pnl = 0.0
                log_event(logger, "settlement_ambiguous",
                    f"Market {market_id} closed but outcomePrices not parseable: {outcome_prices}")
        else:
            # FIX 3: Mark as pending instead of defaulting to loss
            log_event(logger, "settlement_pending",
                f"Market {market_id} still unsettled after retries — recording as pending")
            outcome_str = "pending"
            pnl = 0.0

        pnl = round(pnl, 4)
        entry_time = self._position.entry_time
        try:
            duration = (datetime.now(timezone.utc) - datetime.fromisoformat(entry_time)).total_seconds()
        except (ValueError, TypeError):
            duration = 0.0

        record = TradeRecord(
            market_id=market_id,
            market_question=self._current_market.get("question", "") if self._current_market else "",
            side=self._position.side,
            entry_price=self._position.entry_price,
            size_usdc=self._position.size_usdc,
            exit_price=1.0 if outcome_str == "win" else (0.0 if outcome_str == "loss" else None),
            pnl=pnl if outcome_str != "pending" else None,
            duration_seconds=duration,
            signal_strength=abs(self._current_signal.btc_velocity) if self._current_signal else 0.0,
            llm_verdict=self._last_llm_verdict,
            llm_reason=self._last_llm_reason,
            llm_provider=self._last_llm_provider,
            outcome=outcome_str,
        )
        # COR-03: in-process idempotency. If we already finalized this market
        # in this process, any further settle call is a no-op. On a genuine
        # duplicate the caller's self._position should be cleared too so the
        # cycle doesn't loop on a phantom position.
        if market_id in self._settled_market_ids and outcome_str != "pending":
            logger.warning(
                f"[SETTLE] market_id={market_id} already settled in this process — "
                "skipping duplicate. Clearing position."
            )
            self._position = None
            return

        self._rolling_stats.trades.append(record)
        if outcome_str != "pending":
            # COR-05: atomic PnL + balance update. Updates daily_pnl always
            # and simulated_balance only in dry-run; a crash between those
            # two assignments used to leave the invariant broken across
            # restarts.
            self._rolling_stats.apply_pnl(pnl, self.config.mode)
            if self.config.mode == "dry-run":
                log_event(logger, "simulated_balance_update",
                    f"Dry-run balance: ${self._rolling_stats.simulated_balance:.2f} (P&L: {pnl:+.4f})")

        log_event(logger, "trade_settled", f"{outcome_str.upper()}: P&L=${pnl:.4f}", {
            "market_id": market_id,
            "side": self._position.side,
            "entry_price": self._position.entry_price,
            "pnl": pnl,
            "win_rate": self._rolling_stats.win_rate,
            "daily_pnl": self._rolling_stats.daily_pnl,
        })

        # COR-01: submit the Supabase trade-log row BEFORE clearing
        # self._position. Previously the ordering was
        # `self._position = None → log_trade` and a crash in that window
        # lost the record (bot reports settled, Supabase has no row).
        # We also drain the executor queue synchronously so the write is
        # at least queued on a worker before we mutate further state.
        if outcome_str in ("win", "loss"):
            log_trade({
                "signal_id": getattr(self._current_signal, 'signal_id', '') if self._current_signal else '',
                "market_id": market_id,
                "market_question": self._current_market.get("question", "") if self._current_market else "",
                "side": "up" if self._position.side == "YES" else "down",
                "entry_price": self._position.entry_price,
                "exit_price": record.exit_price or 0.0,
                "size_usdc": self._position.size_usdc,
                "pnl": pnl,
                "llm_verdict": self._last_llm_verdict,
                "llm_reason": self._last_llm_reason,
                "llm_provider": self._last_llm_provider,
                "outcome": outcome_str,
                "llm_response_ms": round(self._last_entry_llm_ms, 1),
                "order_submit_ms": round(self._last_entry_order_ms, 1),
                "total_latency_ms": round(self._last_entry_total_ms, 1),
                # LATENCY-TASK-5: coarse bucket + hot-path-stale flag so
                # post-hoc PnL vs. latency joins are cheap in SQL.
                "latency_bucket": getattr(self, "_last_entry_latency_bucket", None),
                "hot_path_stale": getattr(self, "_last_entry_hot_path_stale", False),
                "mode": self.config.mode,
                "terminal_edge": getattr(self._current_signal, 'terminal_edge', None) if self._current_signal else None,
                "net_edge": getattr(self._current_signal, 'net_edge', None) if self._current_signal else None,
                # MODEL-02: real fee + fill-type from execute_entry.
                "fee_paid": self._last_entry_fee_paid,
                "taker_maker": self._last_entry_taker_maker,
                "fill_price": self._last_entry_fill_price,
            }, session_tag=self.config.session_tag)
            # Flush barrier: ensure the submitted insert has been picked up
            # by a worker before we move on. Best-effort; never let a slow
            # Supabase backend stall the main loop indefinitely.
            try:
                _log_executor.submit(lambda: None).result(timeout=5.0)
            except Exception:
                pass

        if outcome_str == "pending":
            pending_count = len([t for t in self._rolling_stats.trades if t.outcome == "pending"])
            log_event(logger, "pending_settlement_queued",
                f"Market {market_id} queued for re-settlement ({pending_count} pending)")

        # COR-03: persist rolling_stats UNCONDITIONALLY after every settle
        # call. Previously this only ran on the pending outcome path,
        # leaving a double-settle window for win/loss outcomes: a crash
        # between the pnl update and the next save would leave the trade
        # still flagged pending on disk, and recovery would settle it again.
        save_rolling_stats(self._rolling_stats)

        if outcome_str != "pending":
            self._settled_market_ids.add(market_id)

        # COR-01: position cleared LAST, after log is queued AND rolling_stats
        # is persisted. A crash at this point has already written both sources
        # of truth; the worst that happens is the caller sees no position on
        # the next iteration, which is the desired end-state anyway.
        self._position = None
        if outcome_str != "pending":
            self._apply_cooldown()

    async def _recover_pending_position(self):
        """On restart, detect most recent pending trade and attempt immediate settlement."""
        pending_trades = [t for t in self._rolling_stats.trades if t.outcome == "pending"]
        if not pending_trades:
            return
        # Take the most recent pending trade
        last_pending = pending_trades[-1]
        log_event(logger, "position_recovery",
            f"Recovering pending position: {last_pending.market_id} "
            f"side={last_pending.side} entry={last_pending.entry_price} size=${last_pending.size_usdc}")
        # Reconstruct position so _settle() can work
        self._position = PositionState(
            side=last_pending.side,
            entry_price=last_pending.entry_price,
            entry_time=last_pending.timestamp,
            market_id=last_pending.market_id,
            size_usdc=last_pending.size_usdc,
        )
        # Remove the pending trade record — _settle() will create a fresh one
        self._rolling_stats.trades.remove(last_pending)
        # Attempt settlement
        await self._settle(last_pending.market_id)
        log_event(logger, "position_recovery_done",
            f"Recovery complete — position={'active' if self._position else 'cleared'}")

    async def _resolve_pending_settlements(self):
        """Scan rolling_stats.trades for outcome=='pending', re-query Gamma, update in-place."""
        pending_trades = [t for t in self._rolling_stats.trades if t.outcome == "pending"]
        if not pending_trades:
            return
        
        # Evict stale pending settlements (older than 2 hours)
        now = datetime.now(timezone.utc)
        stale = []
        for trade in self._rolling_stats.trades:
            if trade.outcome == "pending":
                try:
                    ts = datetime.fromisoformat(trade.timestamp)
                    if (now - ts).total_seconds() > 7200:
                        stale.append(trade)
                except (ValueError, TypeError):
                    pass
        for trade in stale:
            trade.outcome = "expired"
            trade.reason = "pending > 2h — evicted"
            evicted_size = float(trade.size_usdc or 0.0)
            log_event(logger, "pending_evicted", f"Evicted stale pending: {trade.market_id}")
            # COR-02: on eviction, either refund capital (dry-run) or halt
            # (live). Previously we just marked outcome=expired, leaving the
            # entry's deducted size_usdc unaccounted for. In dry-run this
            # silently drained the simulated balance (root cause of the 2026-
            # 04-16 $2.59 incident). In live mode the on-chain state is
            # unknown, so refunding blind is unsafe; we halt and require
            # operator reconciliation.
            if self.config.mode == "dry-run":
                self._rolling_stats.simulated_balance = round(
                    self._rolling_stats.simulated_balance + evicted_size, 4
                )
                log_event(
                    logger,
                    "pending_eviction_refund",
                    f"[EVICT] Refunded ${evicted_size:.2f} to simulated_balance "
                    f"for expired {trade.market_id} "
                    f"(balance now ${self._rolling_stats.simulated_balance:.2f})",
                )
            elif self.config.mode == "live":
                self._killed = True
                log_event(
                    logger,
                    "pending_eviction_live_halt",
                    f"LIVE HALT: position {trade.market_id} pending >2h with unknown "
                    f"on-chain outcome; manual reconciliation required before restart.",
                    level=40,
                )
                try:
                    _send_telegram_alert(
                        f"LIVE HALT: PolyGuez position {trade.market_id} pending >2h "
                        f"with unknown outcome. Manual reconciliation required before restart."
                    )
                except Exception as _alert_exc:
                    log_event(
                        logger,
                        "pending_eviction_alert_failed",
                        f"Telegram alert on live-eviction failed: {_alert_exc}",
                    )
        
        # BUG-3 fix: rebuild pending list after eviction so evicted trades aren't re-queried
        pending_trades = [t for t in self._rolling_stats.trades if t.outcome == "pending"]
        if not pending_trades:
            if stale:
                save_rolling_stats(self._rolling_stats)
            return

        resolved_count = 0
        for trade in pending_trades:
            try:
                loop = asyncio.get_event_loop()
                market = await loop.run_in_executor(None, self._discovery.get_market_by_id, trade.market_id)
                if not market or not market.get("closed"):
                    continue
                outcome_prices = market.get("outcomePrices", "")
                if isinstance(outcome_prices, str):
                    try:
                        outcome_prices = json.loads(outcome_prices)
                    except (json.JSONDecodeError, TypeError):
                        continue
                if not isinstance(outcome_prices, list) or len(outcome_prices) < 2:
                    continue
                yes_settled = float(outcome_prices[0])
                no_settled = float(outcome_prices[1])
                settled_price = yes_settled if trade.side == "YES" else no_settled
                if settled_price > 0.5:
                    pnl = round(trade.size_usdc * (1.0 / trade.entry_price - 1.0), 4)
                    trade.outcome = "win"
                    trade.exit_price = 1.0
                else:
                    pnl = -trade.size_usdc
                    trade.outcome = "loss"
                    trade.exit_price = 0.0
                trade.pnl = pnl
                trade.reason = "resolved-from-pending"
                # COR-05: atomic PnL + balance update on pending-settlement
                # resolution — same fix as the _settle and emergency-exit
                # paths above.
                self._rolling_stats.apply_pnl(pnl, self.config.mode)
                log_event(logger, "pending_resolved",
                    f"Pending settlement resolved: {trade.market_id} → {trade.outcome} PnL=${pnl:+.4f}")
                resolved_count += 1
            except Exception as exc:
                log_event(logger, "pending_resolve_error",
                    f"Error resolving {trade.market_id}: {exc}", level=30)
        if resolved_count > 0:
            remaining = len([t for t in self._rolling_stats.trades if t.outcome == "pending"])
            save_rolling_stats(self._rolling_stats)
            log_event(logger, "pending_resolved_batch",
                f"Resolved {resolved_count} pending settlements, {remaining} remaining")

    # -- CLOB WebSocket ----------------------------------------------------

    _CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    async def _clob_ws_loop(self):
        """Persistent CLOB WS connection. Reconnects on failure."""
        log_event(logger, "clob_ws_started", "[CLOB/WS] Loop started")
        _ws_headers = {
            "Origin": "https://polymarket.com",
            "User-Agent": "Mozilla/5.0",
        }
        while not self._killed:
            try:
                self._clob_ws = await asyncio.wait_for(
                    websockets.connect(
                        self._CLOB_WS_URL,
                        ping_interval=10, ping_timeout=20,
                        extra_headers=_ws_headers,
                    ),
                    timeout=10.0,
                )
                self._clob_ws_connected = True
                # COR-06: the just-reconnected socket hasn't delivered a
                # book message yet, so prices are stale. The flag flips back
                # to True in `_handle_clob_ws_msg` once both YES and NO
                # prices are populated.
                self._clob_ws_prices_valid = False
                log_event(logger, "clob_ws_connected", "[CLOB/WS] Connected")

                # Start application-level ping keep-alive
                if self._clob_ws_ping_task:
                    self._clob_ws_ping_task.cancel()
                self._clob_ws_ping_task = self._spawn(self._clob_ws_ping_loop(), "clob_ws_ping_loop")

                # Re-subscribe if we already have tokens
                yes_tok, no_tok = self._clob_ws_tokens
                if yes_tok and no_tok:
                    sub = json.dumps({
                        "auth": {},
                        "id": "1",
                        "type": "subscribe",
                        "channel": "market",
                        "markets": [yes_tok, no_tok],
                    })
                    await self._clob_ws.send(sub)
                    log_event(logger, "clob_ws_resubscribed",
                              f"[CLOB/WS] Re-subscribed: yes={yes_tok[:16]}..., no={no_tok[:16]}...")

                async for raw in self._clob_ws:
                    if self._killed:
                        break
                    self._clob_ws_last_msg = time.time()
                    # Reset backoff after first successful message
                    if self._clob_ws_reconnect_count > 0:
                        log_event(logger, "clob_ws_stable", f"[CLOB/WS] Stable — resetting backoff (was {self._clob_ws_reconnect_count})")
                        self._clob_ws_reconnect_count = 0
                    try:
                        msg = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    self._handle_clob_ws_msg(msg)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._clob_ws_connected = False
                # COR-06: invalidate cached prices on disconnect so the
                # main cycle refuses to consume stale zero/old values
                # until the socket is back and has delivered a fresh book.
                self._clob_ws_prices_valid = False
                log_event(logger, "clob_ws_error",
                          f"[CLOB/WS] Error: {type(exc).__name__}: {exc}", level=30)
            # Cancel ping task on disconnect
            if self._clob_ws_ping_task:
                self._clob_ws_ping_task.cancel()
                self._clob_ws_ping_task = None
            # Exponential backoff on reconnect (cap 30s)
            self._clob_ws_connected = False
            self._clob_ws_prices_valid = False
            delay = min(2 ** self._clob_ws_reconnect_count, 30)
            self._clob_ws_reconnect_count += 1
            log_event(logger, "clob_ws_backoff", f"[CLOB/WS] Reconnecting in {delay}s (attempt {self._clob_ws_reconnect_count})")
            await asyncio.sleep(delay)

    def _handle_clob_ws_msg(self, msg):
        """Parse CLOB WS messages and update cached prices."""
        msg_type = msg.get("type", "")
        yes_tok, no_tok = self._clob_ws_tokens

        if msg_type == "book":
            # Full orderbook snapshot — extract best bid/ask mid
            market = msg.get("market", "")
            bids = msg.get("bids", [])
            asks = msg.get("asks", [])
            mid = 0.0
            if bids and asks:
                best_bid = float(bids[0].get("price", 0))
                best_ask = float(asks[0].get("price", 0))
                if best_bid > 0 and best_ask > 0:
                    mid = (best_bid + best_ask) / 2.0
            elif msg.get("mid"):
                mid = float(msg["mid"])
            if mid > 0:
                if market == yes_tok:
                    self._clob_ws_yes = mid
                elif market == no_tok:
                    self._clob_ws_no = mid
                if self._clob_ws_yes > 0 and self._clob_ws_no > 0:
                    # COR-06: we now have a fresh book for BOTH legs, so
                    # main-cycle reads are safe again.
                    if not self._clob_ws_prices_valid:
                        log_event(logger, "clob_ws_prices_valid",
                                  "[CLOB/WS] First fresh book post-connect — prices now valid")
                    self._clob_ws_prices_valid = True
                    log_event(logger, "clob_ws_book",
                              f"[CLOB/WS] UP={self._clob_ws_yes:.4f} DOWN={self._clob_ws_no:.4f}")

        elif msg_type in ("price_change", "last_trade_price"):
            market = msg.get("market", "") or msg.get("asset_id", "")
            price = 0.0
            # Try various price field names
            for key in ("price", "mid", "last_trade_price", "new_price"):
                if key in msg:
                    try:
                        price = float(msg[key])
                        break
                    except (ValueError, TypeError):
                        continue
            if price > 0:
                if market == yes_tok:
                    self._clob_ws_yes = price
                elif market == no_tok:
                    self._clob_ws_no = price
                if self._clob_ws_yes > 0 and self._clob_ws_no > 0:
                    if not self._clob_ws_prices_valid:
                        log_event(logger, "clob_ws_prices_valid",
                                  "[CLOB/WS] First fresh price post-connect — prices now valid")
                    self._clob_ws_prices_valid = True
                    log_event(logger, "clob_ws_price",
                              f"[CLOB/WS] UP={self._clob_ws_yes:.4f} DOWN={self._clob_ws_no:.4f}")

    async def _clob_ws_ping_loop(self):
        """Application-level ping to keep the CLOB WS connection alive."""
        try:
            while self._clob_ws_connected and not self._killed:
                await asyncio.sleep(10)
                try:
                    if self._clob_ws:
                        await self._clob_ws.ping()
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    async def _subscribe_clob_ws(self, yes_token, no_token):
        """Subscribe to new market tokens on the CLOB WS."""
        if not self.config.clob_ws_enabled:
            self._clob_ws_tokens = (yes_token, no_token)
            return

        if (yes_token, no_token) == self._clob_ws_tokens:
            return  # Already subscribed to these tokens

        # Reset cached prices for new market
        self._clob_ws_yes = 0.0
        self._clob_ws_no = 0.0
        self._clob_ws_tokens = (yes_token, no_token)

        if self._clob_ws and self._clob_ws_connected:
            try:
                sub = json.dumps({
                    "auth": {},
                    "id": "1",
                    "type": "subscribe",
                    "channel": "market",
                    "markets": [yes_token, no_token],
                })
                await self._clob_ws.send(sub)
                log_event(logger, "clob_ws_subscribed",
                          f"[CLOB/WS] Subscribed: yes={yes_token[:16]}..., no={no_token[:16]}...")
            except Exception as exc:
                log_event(logger, "clob_ws_subscribe_error",
                          f"[CLOB/WS] Subscribe failed: {exc}", level=30)
        else:
            log_event(logger, "clob_ws_pending",
                      "[CLOB/WS] Not connected, will subscribe on reconnect")

    # -- Helpers -----------------------------------------------------------

    async def _discover_market(self):
        """Find active 5-min BTC market via Gamma API.

        Results are cached for 60s. A market is valid for a full 300s window
        so this eliminates ~12 Gamma calls per window under normal conditions.
        Cache is invalidated when the market changes (different market_id).
        """
        cached = self._market_cache
        if cached["market"] and (time.time() - cached["ts"]) < 60.0:
            return cached["market"]
        try:
            market = await self._discovery.find_active_btc_5min_market_async(self.config)
            if market:
                self._gamma_ok = True
                self._market_cache = {"market": market, "ts": time.time()}
                log_event(logger, "market_found", f"Found: {market.get('question', 'unknown')}")
            else:
                self._gamma_ok = True  # API worked, just no market right now
                self._market_cache = {"market": None, "ts": 0.0}  # don't cache None
                log_event(logger, "market_none", "No active BTC 5-min market found in current/adjacent windows")
            return market
        except Exception as exc:
            self._gamma_ok = False
            log_event(logger, "gamma_error",
                f"Market discovery failed: {type(exc).__name__}: {exc}",
                level=40)
            return None

    async def _poll_clob(self, yes_token, no_token):
        """Get CLOB prices: prefer WS cache, fall back to REST, then Gamma."""
        # COR-06: ws_fresh now additionally requires `_clob_ws_prices_valid`.
        # Between a disconnect and the first post-reconnect book message,
        # the cached yes/no prices may be stale (or the disconnect set them
        # to zero) — the flag guarantees we only trust the cache once a
        # fresh book has arrived. Functionally equivalent to the existing
        # "`> 0`" checks for the common case, plus explicit protection
        # against any future code path that leaves stale non-zero prices.
        ws_fresh = (
            self._clob_ws_connected
            and self._clob_ws_prices_valid
            and self._clob_ws_last_msg > 0
            and time.time() - self._clob_ws_last_msg < 30.0
            and self._clob_ws_yes > 0
            and self._clob_ws_no > 0
        )
        if ws_fresh:
            yes_price = self._clob_ws_yes
            no_price = self._clob_ws_no
            spread = abs(1.0 - yes_price - no_price)
            self._clob_ok = True
            return (yes_price, no_price, spread)

        # WS stale or not connected — fall back to REST
        if self._clob_ws_connected and self._clob_ws_last_msg > 0:
            age = time.time() - self._clob_ws_last_msg
            if age > 30.0:
                log_event(logger, "clob_ws_stale", f"CLOB WS data is {age:.0f}s old — falling back to REST")
        elif self._clob_ws_connected and not self._clob_ws_prices_valid:
            log_event(logger, "clob_ws_stale_skip",
                f"[CLOB/WS] connected but prices not yet valid post-reconnect — falling back to REST")

        return await self._poll_clob_rest(yes_token, no_token)

    async def _poll_clob_rest(self, yes_token, no_token):
        """REST fallback for CLOB prices — single combined midpoints call."""
        try:
            # Try combined midpoints endpoint (1 call instead of 2)
            if self._clob_http_session:
                result = await self._try_midpoints_combined(yes_token, no_token)
                if result:
                    return result

            # Fallback: individual midpoint calls via py_clob_client
            if self._polymarket:
                loop = asyncio.get_event_loop()
                yes_future = loop.run_in_executor(None, self._get_clob_price_with_log, yes_token, "UP")
                no_future = loop.run_in_executor(None, self._get_clob_price_with_log, no_token, "DOWN")
                yes_price, no_price = await asyncio.gather(yes_future, no_future)
                log_event(logger, "clob_rest_individual",
                          f"[CLOB/REST] Individual: UP={yes_price:.4f} DOWN={no_price:.4f}")
                spread = abs(1.0 - yes_price - no_price)
                self._clob_ok = True
                return (yes_price, no_price, spread)

            # Last fallback: Gamma outcomePrices
            yes_price = 0.50
            no_price = 0.50
            market_data = self._current_market
            if market_data:
                prices = market_data.get("outcomePrices", "")
                log_event(logger, "clob_fallback", f"No wallet, using outcomePrices: {prices}")
                if isinstance(prices, str):
                    try:
                        prices = json.loads(prices)
                    except (json.JSONDecodeError, TypeError):
                        prices = []
                if isinstance(prices, list) and len(prices) >= 2:
                    yes_price = float(prices[0])
                    no_price = float(prices[1])

            spread = abs(1.0 - yes_price - no_price)
            self._clob_ok = True
            return (yes_price, no_price, spread)
        except Exception as exc:
            self._clob_ok = False
            log_event(logger, "clob_error", f"CLOB poll failed: {exc}", level=40)
            return (0.0, 0.0, 1.0)

    async def _try_midpoints_combined(self, yes_token, no_token):
        """Fetch midpoints for both tokens in parallel via /midpoint endpoint."""
        base = "https://clob.polymarket.com/midpoint"
        try:
            async def _fetch_one(token_id, label):
                url = f"{base}?token_id={token_id}"
                async with self._clob_http_session.get(url) as resp:
                    if resp.status != 200:
                        log_event(logger, "clob_rest_http",
                                  f"[CLOB/REST] midpoint HTTP {resp.status} for {label} {token_id[:16]}...", level=30)
                        return 0.0
                    data = await resp.json(content_type=None)
                    log_event(logger, "clob_rest_raw",
                              f"[CLOB/REST] midpoint {label} raw: {data}", level=10)
                    if isinstance(data, dict):
                        val = data.get("mid") or data.get("price") or data.get("midpoint")
                        return float(val) if val is not None else 0.0
                    elif isinstance(data, (str, int, float)):
                        return float(data)
                    return 0.0

            yes_price, no_price = await asyncio.gather(
                _fetch_one(yes_token, "UP"),
                _fetch_one(no_token, "DOWN"),
            )
            if yes_price > 0 and no_price > 0:
                log_event(logger, "clob_rest_prices",
                          f"[CLOB/REST] UP={yes_price:.4f} DOWN={no_price:.4f}")
                spread = abs(1.0 - yes_price - no_price)
                self._clob_ok = True
                return (yes_price, no_price, spread)
            log_event(logger, "clob_rest_bad",
                      f"[CLOB/REST] Partial midpoint: UP={yes_price} DOWN={no_price}", level=30)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log_event(logger, "clob_rest_error",
                      f"[CLOB/REST] midpoint failed: {e}", level=30)
        return None

    @staticmethod
    def _parse_midpoints(data, yes_token, no_token):
        """Parse midpoints response — handles multiple known formats."""
        yes_price = 0.0
        no_price = 0.0
        try:
            for token, label in [(yes_token, "yes"), (no_token, "no")]:
                raw = data.get(token)
                if raw is None:
                    continue
                if isinstance(raw, dict):
                    val = raw.get("mid") or raw.get("price") or raw.get("midpoint")
                    price = float(val) if val is not None else 0.0
                elif isinstance(raw, (str, int, float)):
                    price = float(raw)
                else:
                    price = 0.0
                if label == "yes":
                    yes_price = price
                else:
                    no_price = price
        except (ValueError, TypeError, KeyError):
            pass
        return yes_price, no_price

    def _get_clob_price_with_log(self, token_id, label):
        """Fetch CLOB midpoint price for a token and log the raw response."""
        try:
            raw_mid = self._polymarket.client.get_midpoint(token_id)
            log_event(logger, "clob_raw", f"CLOB {label} raw response: {raw_mid} (type={type(raw_mid).__name__})")
            if isinstance(raw_mid, dict):
                # Try common keys: 'mid', 'price', 'midpoint'
                price = float(raw_mid.get('mid') or raw_mid.get('price') or raw_mid.get('midpoint') or 0)
            else:
                price = float(raw_mid)
            return price
        except Exception as exc:
            log_event(logger, "clob_price_error", f"CLOB {label} midpoint failed: {exc}")
            return 0.0

    async def _fetch_depth(self, token_id):
        """FIX 2: Fetch CLOB depth for deterministic gate.

        Returns -1.0 when depth cannot be measured (no wallet, API error)
        so the signal evaluator can skip the depth gate instead of blocking.
        Results are cached for 4s — CLOB depth changes on the order of
        seconds so this eliminates ~9 of every 10 get_order_book calls
        during the 100ms-tick entry window.
        """
        if not self._polymarket:
            return -1.0
        cached = self._depth_cache.get(token_id)
        if cached and (time.time() - cached["ts"]) < 4.0:
            return cached["depth"]
        loop = asyncio.get_event_loop()
        book = None
        try:
            book = await loop.run_in_executor(
                None, self._polymarket.client.get_order_book, token_id,
            )
            depth = compute_clob_depth(book, "buy")
            self._depth_cache[token_id] = {"depth": depth, "ts": time.time()}
            log_event(logger, "clob_depth_fetched", f"Depth for {token_id[:16]}...: {depth:.1f}")
            return depth
        except Exception as exc:
            book_info = f"type={type(book).__name__}, attrs={[a for a in dir(book) if not a.startswith('_')]}" if book else "None"
            log_event(logger, "clob_depth_error", f"Depth fetch failed: {exc} | book: {book_info}", level=30)
            return -1.0

    async def _get_clob_depth(self, token_id):
        """Get CLOB depth summary: top-of-book + depth within $0.05 per side."""
        if not self._polymarket:
            return ""
        loop = asyncio.get_event_loop()
        try:
            book = await loop.run_in_executor(
                None, self._polymarket.client.get_order_book, token_id,
            )
            # Support both OrderBookSummary (attribute) and dict access
            bids = book.bids if hasattr(book, 'bids') else book.get("bids", [])
            asks = book.asks if hasattr(book, 'asks') else book.get("asks", [])

            def _price(entry):
                return float(entry.price if hasattr(entry, 'price') else entry["price"])

            def _size(entry):
                return float(entry.size if hasattr(entry, 'size') else entry["size"])

            best_bid = _price(bids[0]) if bids else 0.0
            best_bid_size = _size(bids[0]) if bids else 0.0
            best_ask = _price(asks[0]) if asks else 0.0
            best_ask_size = _size(asks[0]) if asks else 0.0

            bid_depth = sum(_size(b) for b in bids if best_bid - _price(b) <= 0.05)
            ask_depth = sum(_size(a) for a in asks if _price(a) - best_ask <= 0.05)

            return (
                f"Best bid: {best_bid:.4f} (size {best_bid_size:.1f}) | "
                f"Best ask: {best_ask:.4f} (size {best_ask_size:.1f})\n"
                f"Bid depth (within $0.05): {bid_depth:.1f} | "
                f"Ask depth (within $0.05): {ask_depth:.1f}"
            )
        except Exception as exc:
            log_event(logger, "clob_depth_error", f"Depth summary failed: {exc} | book type={type(book).__name__}, attrs={dir(book)[:10]}", level=30)
            return ""

    async def _refresh_balance(self):
        """Update USDC balance — simulated in dry-run, real in paper/live."""
        if self.config.mode == "dry-run":
            self._usdc_balance = self._rolling_stats.simulated_balance
            log_event(logger, "balance_simulated", f"Dry-run: simulated balance ${self._usdc_balance:.2f}")
            return
        if self._polymarket:
            loop = asyncio.get_event_loop()
            try:
                real_balance = await loop.run_in_executor(
                    None, self._polymarket.get_usdc_balance,
                )
                self._usdc_balance = real_balance
                log_event(logger, "balance_real", f"Real USDC balance: ${real_balance:.2f}")
                return
            except Exception as exc:
                log_event(logger, "balance_error",
                    f"Balance fetch failed: {type(exc).__name__}: {exc}",
                    level=40)
        if self._usdc_balance <= 0.0:
            self._usdc_balance = 100.0
            log_event(logger, "balance_simulated", "Using simulated $100 balance")

    def _apply_cooldown(self):
        """Set cooldown_until based on adaptive cooldown logic."""
        cycles = compute_cooldown(self._rolling_stats, self.config)
        if cycles > 0:
            until = datetime.now(timezone.utc) + timedelta(seconds=cycles * CYCLE_SECONDS)
            self._rolling_stats.cooldown_until = until.isoformat()
            log_event(logger, "cooldown_set", f"Cooldown: {cycles} cycle(s) until {until.isoformat()}")
        else:
            self._rolling_stats.cooldown_until = None


# -- Entrypoint ------------------------------------------------------------


def start_runner(mode="dry-run", live=False):
    """Entry point for CLI. Builds config and starts the async loop."""
    if live:
        mode = "live"
    elif mode not in ("dry-run", "paper"):
        mode = "dry-run"

    config = PolyGuezConfig(mode=mode)

    # Load overrides from env
    env_overrides = {
        "rtds_ws_url": os.getenv("POLYMARKET_RTDS_URL", config.rtds_ws_url),
        "binance_ws_url": os.getenv("BINANCE_WS_URL", config.binance_ws_url),
        "coinbase_ws_url": os.getenv("COINBASE_WS_URL", config.coinbase_ws_url),
        "dashboard_secret": os.getenv("DASHBOARD_SECRET", "") or config.dashboard_secret,
    }
    config = config.model_copy(update=env_overrides)

    from agents.utils.supabase_logger import supabase_startup_check
    supabase_startup_check()

    runner = PolyGuezRunner(config=config)
    asyncio.run(runner.run())
    return runner
