"""PolyGuez Momentum — async event loop runner.

Separate from existing Trader.one_best_trade() pipeline.
"""

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from agents.polymarket.gamma import GammaMarketClient
from agents.polymarket.polymarket import Polymarket
from agents.strategies.btc_feed import BTCPriceFeed
from agents.strategies.market_discovery import MarketDiscovery
from agents.strategies.polyguez_strategy import (
    calculate_max_capital_at_risk,
    calculate_position_size,
    check_daily_loss_limit,
    check_emergency_exit,
    compute_cooldown,
    evaluate_entry_signal,
    execute_emergency_exit,
    execute_entry,
    get_llm_confirmation,
    load_rolling_stats,
    save_rolling_stats,
)
from agents.utils.logger import get_logger, log_event
from agents.utils.objects import (
    DashboardSnapshot,
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

        # Existing repo components
        self._polymarket = None  # Lazy init — needs wallet key
        self._gamma = GammaMarketClient()
        self._discovery = MarketDiscovery(self._gamma)

        # New components
        self._btc_feed = BTCPriceFeed(self.config)

        # State
        self._rolling_stats = load_rolling_stats()
        self._position = None  # PositionState or None
        self._current_market = None
        self._current_signal = None
        self._last_llm_verdict = ""
        self._last_llm_reason = ""
        self._last_llm_time = 0.0
        self._killed = False
        self._kill_timestamp = None
        self._usdc_balance = 0.0
        self._gamma_ok = False
        self._clob_ok = False

    # -- Public API for dashboard / CLI ------------------------------------

    @property
    def is_killed(self):
        return self._killed

    async def update_config(self, partial):
        """Update config from dashboard. Takes effect next cycle."""
        async with self._config_lock:
            current = self.config.dict()
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
                remaining = (until - datetime.now(timezone.utc)).total_seconds()
                if remaining > 0:
                    cooldown_active = True
                    cooldown_remaining = remaining
            except (ValueError, TypeError):
                pass

        return DashboardSnapshot(
            mode=self.config.mode,
            btc_feed_connected=self._btc_feed.is_connected,
            clob_connected=self._clob_ok,
            gamma_connected=self._gamma_ok,
            usdc_balance=self._usdc_balance,
            max_capital_at_risk=calculate_max_capital_at_risk(self._usdc_balance, self.config),
            position_size_ceiling=calculate_position_size(self._usdc_balance, self.config),
            daily_pnl=self._rolling_stats.daily_pnl,
            killed=self._killed,
            kill_timestamp=self._kill_timestamp,
            current_market_question=self._current_market.get("question", "") if self._current_market else "",
            current_market_expiry=expiry,
            btc_price=self._btc_feed.get_price(),
            btc_velocity=self._btc_feed.get_velocity(),
            btc_direction="up" if self._btc_feed.get_velocity() > 0 else "down",
            yes_price=self._current_signal.yes_price if self._current_signal else 0.0,
            no_price=self._current_signal.no_price if self._current_signal else 0.0,
            clob_spread=self._current_signal.spread if self._current_signal else 0.0,
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

        # Stop BTC feed
        await self._btc_feed.stop()

    # -- Main loop ---------------------------------------------------------

    async def run(self):
        """Main event loop — runs until killed."""
        log_event(logger, "runner_start", f"PolyGuez starting in {self.config.mode} mode")

        # Init Polymarket client (wallet/CLOB auth)
        if self.config.mode == "live":
            try:
                loop = asyncio.get_event_loop()
                self._polymarket = await loop.run_in_executor(None, Polymarket)
                log_event(logger, "wallet_connected", "Polymarket client initialized")
            except Exception as exc:
                log_event(logger, "wallet_error", f"Failed to init Polymarket: {exc}", level=40)
                if self.config.mode == "live":
                    log_event(logger, "runner_halt", "Cannot run live without wallet")
                    return

        # Start BTC price feed
        await self._btc_feed.start()

        while not self._killed:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log_event(logger, "cycle_error", f"Cycle error: {exc}", level=40)
                await asyncio.sleep(5)

        log_event(logger, "runner_stop", "PolyGuez stopped")
        save_rolling_stats(self._rolling_stats)

    async def _cycle(self):
        """One full market cycle: discover → trade → settle."""
        # Reset daily P&L if new day
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._rolling_stats.daily_pnl_reset_utc != today:
            self._rolling_stats.daily_pnl = 0.0
            self._rolling_stats.daily_pnl_reset_utc = today
            log_event(logger, "daily_reset", "Daily P&L reset")

        # Update USDC balance
        await self._refresh_balance()
        self._rolling_stats.max_capital_at_risk = calculate_max_capital_at_risk(
            self._usdc_balance, self.config
        )

        # Check if balance allows trading
        if self._usdc_balance < self.config.min_capital_floor:
            log_event(logger, "balance_halt", f"Balance ${self._usdc_balance:.2f} < floor ${self.config.min_capital_floor}")
            await asyncio.sleep(30)
            return

        # Discover active 5-min BTC market
        self._current_market = await self._discover_market()
        if not self._current_market:
            await asyncio.sleep(5)
            return

        market_id = str(self._current_market.get("id", ""))
        question = self._current_market.get("question", "")
        expiry_dt = MarketDiscovery.get_market_expiry(self._current_market)
        yes_token, no_token = MarketDiscovery.get_market_token_ids(self._current_market)

        if not yes_token or not no_token:
            log_event(logger, "market_skip", f"No token IDs for market {market_id}")
            await asyncio.sleep(5)
            return

        log_event(logger, "market_active", f"Tracking: {question}", {
            "market_id": market_id,
            "expiry": str(expiry_dt),
        })

        # Wait for BTC feed buffer
        if not self._btc_feed.is_ready():
            log_event(logger, "btc_buffer_filling", "Waiting for BTC price buffer")
            while not self._btc_feed.is_ready() and not self._killed:
                await asyncio.sleep(1)

        # Entry window loop
        entered = await self._entry_window(market_id, yes_token, no_token, expiry_dt)

        # Hold loop (if we entered a position)
        if entered and self._position:
            await self._hold_loop(expiry_dt)

        # Wait for settlement
        if expiry_dt:
            wait = (expiry_dt - datetime.now(timezone.utc)).total_seconds()
            if wait > 0:
                await asyncio.sleep(min(wait + 5, 60))

        # Check settlement
        if self._position:
            await self._settle(market_id)

        # Persist stats
        save_rolling_stats(self._rolling_stats)
        self._current_market = None
        self._current_signal = None
        self._last_llm_verdict = ""
        self._last_llm_reason = ""

    # -- Sub-loops ---------------------------------------------------------

    async def _entry_window(self, market_id, yes_token, no_token, expiry_dt):
        """Evaluate entry signal every ~1s during the entry window."""
        while not self._killed:
            if expiry_dt:
                remaining = (expiry_dt - datetime.now(timezone.utc)).total_seconds()
                elapsed = 300.0 - remaining
                if remaining < 30:
                    # Too close to expiry, skip
                    log_event(logger, "entry_skip", "Too close to expiry, skipping entry")
                    return False
            else:
                elapsed = 0.0

            # Poll CLOB prices
            yes_price, no_price, spread = await self._poll_clob(yes_token, no_token)

            # Evaluate signal
            signal = evaluate_entry_signal(
                btc_velocity=self._btc_feed.get_velocity(),
                btc_price=self._btc_feed.get_price(),
                yes_price=yes_price,
                no_price=no_price,
                spread=spread,
                elapsed_seconds=elapsed,
                usdc_balance=self._usdc_balance,
                config=self.config,
                rolling_stats=self._rolling_stats,
                has_position=self._position is not None,
                open_position_count=1 if self._position else 0,
            )
            self._current_signal = signal

            log_event(logger, "signal_evaluated", f"Signal: {signal.all_conditions_met}", {
                "velocity": round(signal.btc_velocity, 6),
                "edge": round(signal.edge, 4),
                "required_edge": round(signal.required_edge, 4),
                "spread": round(signal.spread, 4),
                "elapsed": round(elapsed, 1),
                "conditions": {
                    "velocity_ok": signal.velocity_ok,
                    "edge_ok": signal.edge_ok,
                    "spread_ok": signal.spread_ok,
                    "no_position": signal.no_position,
                    "cooldown_ok": signal.cooldown_ok,
                    "daily_loss_ok": signal.daily_loss_ok,
                    "balance_ok": signal.balance_ok,
                    "position_limit_ok": signal.position_limit_ok,
                },
            })

            if signal.all_conditions_met:
                return await self._attempt_entry(signal, market_id, yes_token, no_token)

            await asyncio.sleep(self.config.clob_poll_interval)

        return False

    async def _attempt_entry(self, signal, market_id, yes_token, no_token):
        """Deterministic signal fired — run LLM confirmation then execute."""
        log_event(logger, "signal_fired", f"Deterministic signal FIRED: {signal.direction}")

        # LLM confirmation
        verdict, reason, provider, llm_time = await get_llm_confirmation(
            signal, self._rolling_stats, self.config,
        )
        self._last_llm_verdict = verdict
        self._last_llm_reason = reason
        self._last_llm_time = llm_time

        if verdict == "NO-GO":
            record = TradeRecord(
                market_id=market_id,
                side=signal.direction.upper(),
                llm_verdict=verdict,
                llm_reason=reason,
                llm_provider=provider,
                outcome="skipped",
                reason=f"LLM NO-GO: {reason}",
            )
            self._rolling_stats.trades.append(record)
            log_event(logger, "trade_skipped", f"Skipped: LLM NO-GO — {reason}")
            return False

        # Determine position size
        size = calculate_position_size(self._usdc_balance, self.config)
        if verdict == "REDUCE-SIZE":
            size = round(size * 0.5, 2)
            log_event(logger, "size_reduced", f"LLM REDUCE-SIZE → ${size:.2f}")

        # Pick token
        token_id = yes_token if signal.direction == "up" else no_token
        side = "YES" if signal.direction == "up" else "NO"
        entry_price = signal.yes_price if side == "YES" else signal.no_price

        # Execute
        result = await execute_entry(self._polymarket, token_id, size, self.config.mode)

        if result["status"] == "error":
            record = TradeRecord(
                market_id=market_id,
                side=side,
                llm_verdict=verdict,
                llm_reason=reason,
                llm_provider=provider,
                outcome="skipped",
                reason=f"Execution error: {result.get('error', '')}",
            )
            self._rolling_stats.trades.append(record)
            log_event(logger, "entry_failed", f"Entry failed: {result.get('error', '')}")
            return False

        self._position = PositionState(
            side=side,
            entry_price=entry_price,
            entry_time=datetime.now(timezone.utc).isoformat(),
            market_id=market_id,
            token_id=token_id,
            size_usdc=size,
        )

        log_event(logger, "position_entered", f"Entered {side} @ {entry_price:.4f}, size=${size:.2f}", {
            "market_id": market_id,
            "token_id": token_id,
            "mode": self.config.mode,
        })
        return True

    async def _hold_loop(self, expiry_dt):
        """Monitor position for emergency exit until expiry."""
        entry_direction = "up" if self._position.side == "YES" else "down"

        while not self._killed and self._position:
            if expiry_dt:
                remaining = (expiry_dt - datetime.now(timezone.utc)).total_seconds()
                if remaining < 5:
                    break  # Let it settle

            velocity = self._btc_feed.get_velocity()
            if check_emergency_exit(velocity, entry_direction, self.config):
                result = await execute_emergency_exit(
                    self._polymarket, self._position, self.config.mode,
                )
                # Record as emergency exit
                pnl = -self._position.size_usdc * 0.5  # Estimate — actual depends on fill
                record = TradeRecord(
                    market_id=self._position.market_id,
                    side=self._position.side,
                    entry_price=self._position.entry_price,
                    pnl=pnl,
                    outcome="emergency-exit",
                    reason="Velocity reversal exceeded threshold",
                )
                self._rolling_stats.trades.append(record)
                self._rolling_stats.daily_pnl += pnl
                self._position = None
                self._apply_cooldown()
                return

            await asyncio.sleep(self.config.clob_poll_interval)

    async def _settle(self, market_id):
        """Check settlement outcome and record P&L."""
        if not self._position:
            return

        # Poll Gamma for settlement
        loop = asyncio.get_event_loop()
        settled_market = await loop.run_in_executor(
            None, self._discovery.get_market_by_id, market_id,
        )

        outcome_str = ""
        pnl = 0.0
        if settled_market and settled_market.get("closed"):
            # Determine outcome from resolved prices
            outcome_prices = settled_market.get("outcomePrices", "")
            if isinstance(outcome_prices, str):
                try:
                    outcome_prices = json.loads(outcome_prices)
                except (json.JSONDecodeError, TypeError):
                    outcome_prices = []

            if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                yes_settled = float(outcome_prices[0])
                no_settled = float(outcome_prices[1])
                settled_price = yes_settled if self._position.side == "YES" else no_settled

                if settled_price > 0.5:
                    # Our side won
                    pnl = (1.0 - self._position.entry_price) * self._position.size_usdc
                    outcome_str = "win"
                else:
                    pnl = -self._position.entry_price * self._position.size_usdc
                    outcome_str = "loss"
            else:
                # Can't determine — treat as loss to be safe
                pnl = -self._position.entry_price * self._position.size_usdc
                outcome_str = "loss"
        else:
            # Not yet settled — estimate from current data
            log_event(logger, "settlement_pending", f"Market {market_id} not yet settled, will estimate")
            pnl = -self._position.entry_price * self._position.size_usdc
            outcome_str = "loss"

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
            exit_price=1.0 if outcome_str == "win" else 0.0,
            pnl=pnl,
            duration_seconds=duration,
            signal_strength=abs(self._current_signal.btc_velocity) if self._current_signal else 0.0,
            llm_verdict=self._last_llm_verdict,
            llm_reason=self._last_llm_reason,
            outcome=outcome_str,
        )
        self._rolling_stats.trades.append(record)
        self._rolling_stats.daily_pnl += pnl

        log_event(logger, "trade_settled", f"{outcome_str.upper()}: P&L=${pnl:.4f}", {
            "market_id": market_id,
            "side": self._position.side,
            "entry_price": self._position.entry_price,
            "pnl": pnl,
            "win_rate": self._rolling_stats.win_rate,
            "daily_pnl": self._rolling_stats.daily_pnl,
        })

        self._position = None
        self._apply_cooldown()

    # -- Helpers -----------------------------------------------------------

    async def _discover_market(self):
        """Find active 5-min BTC market via Gamma API."""
        loop = asyncio.get_event_loop()
        try:
            market = await loop.run_in_executor(
                None, self._discovery.find_active_btc_5min_market, self.config,
            )
            self._gamma_ok = True
            return market
        except Exception as exc:
            self._gamma_ok = False
            log_event(logger, "gamma_error", f"Market discovery failed: {exc}", level=40)
            return None

    async def _poll_clob(self, yes_token, no_token):
        """Poll CLOB for current YES/NO prices. Returns (yes_price, no_price, spread)."""
        loop = asyncio.get_event_loop()
        try:
            if self._polymarket:
                yes_price = await loop.run_in_executor(
                    None, self._polymarket.get_orderbook_price, yes_token,
                )
                no_price = await loop.run_in_executor(
                    None, self._polymarket.get_orderbook_price, no_token,
                )
            else:
                # In dry-run/paper without wallet, use Gamma API
                yes_price = 0.50
                no_price = 0.50
                market_data = self._current_market
                if market_data:
                    prices = market_data.get("outcomePrices", "")
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
            return (0.0, 0.0, 1.0)  # spread=1.0 will fail the spread check → safe

    async def _refresh_balance(self):
        """Update USDC balance."""
        if self._polymarket:
            loop = asyncio.get_event_loop()
            try:
                self._usdc_balance = await loop.run_in_executor(
                    None, self._polymarket.get_usdc_balance,
                )
            except Exception as exc:
                log_event(logger, "balance_error", f"Balance fetch failed: {exc}", level=40)
        elif self.config.mode in ("dry-run", "paper"):
            if self._usdc_balance == 0.0:
                self._usdc_balance = 100.0  # Simulated starting balance

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
        "binance_ws_url": os.getenv("BINANCE_WS_URL", config.binance_ws_url),
        "coinbase_ws_url": os.getenv("COINBASE_WS_URL", config.coinbase_ws_url),
        "dashboard_secret": os.getenv("DASHBOARD_SECRET", ""),
    }
    config = config.copy(update=env_overrides)

    runner = PolyGuezRunner(config=config)
    asyncio.run(runner.run())
    return runner
