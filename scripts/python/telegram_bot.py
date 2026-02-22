"""
Polymarket Telegram Bot

Connects the PolymarketAgent to Telegram so you can control your
Polymarket account by sending messages to your bot.

Includes auto-trading: xAI analyzes markets and executes trades automatically.

Setup:
  1. Talk to @BotFather on Telegram and create a bot. Copy the token.
  2. Set TELEGRAM_BOT_TOKEN in your .env file.
  3. Optionally set TELEGRAM_ALLOWED_USERS to a comma-separated list of
     Telegram user IDs to restrict access (recommended for security).
  4. Run: python scripts/python/telegram_bot.py
"""

import os
import sys
import json
import logging
import traceback

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logger = logging.getLogger(__name__)

# Max Telegram message length
TG_MAX_LEN = 4096


def get_allowed_users() -> set:
    """Parse TELEGRAM_ALLOWED_USERS env var into a set of user IDs."""
    raw = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    if not raw.strip():
        return set()
    return {int(uid.strip()) for uid in raw.split(",") if uid.strip()}


ALLOWED_USERS = get_allowed_users()


def is_authorized(user_id: int) -> bool:
    """Check if the user is authorized. If no allowlist is set, allow everyone."""
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


def split_message(text: str) -> list:
    """Split a long message into chunks that fit Telegram's limit."""
    if len(text) <= TG_MAX_LEN:
        return [text]

    chunks = []
    while text:
        if len(text) <= TG_MAX_LEN:
            chunks.append(text)
            break
        # Find a newline near the limit to split cleanly
        split_at = text.rfind("\n", 0, TG_MAX_LEN)
        if split_at == -1:
            split_at = TG_MAX_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


class TelegramPolymarketBot:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN not set. "
                "Create a bot with @BotFather and add the token to .env"
            )

        # Lazy init: agent is created on first use, not at startup
        self._agent = None
        self._agent_error = None

        # Auto-trader instance (lazy init)
        self._auto_trader = None

        # Per-user pending orders (user_id -> order dict)
        self._pending_orders = {}

        # Chat ID for auto-trade notifications
        self._notify_chat_id = None
        self._app = None

    @property
    def agent(self):
        """Lazily initialize the PolymarketAgent on first access."""
        if self._agent is None:
            try:
                from scripts.python.agent import PolymarketAgent
                logger.info("Initializing Polymarket Agent...")
                self._agent = PolymarketAgent()
                self._agent_error = None
                logger.info("Agent ready.")
            except Exception as e:
                self._agent_error = str(e)
                logger.error(f"Failed to init agent: {e}")
                logger.error(traceback.format_exc())
        return self._agent

    @property
    def auto_trader(self):
        """Lazily initialize the AutoTrader on first access."""
        if self._auto_trader is None and self.agent is not None:
            try:
                from scripts.python.auto_trader import AutoTrader
                self._auto_trader = AutoTrader(self.agent)
                # Set notification callback
                self._auto_trader.set_notify_callback(self._send_autotrade_notification)
                logger.info("AutoTrader initialized.")
            except Exception as e:
                logger.error(f"Failed to init AutoTrader: {e}")
                logger.error(traceback.format_exc())
        return self._auto_trader

    async def _send_autotrade_notification(self, message: str):
        """Send auto-trade notification to the registered chat."""
        if self._app and self._notify_chat_id:
            try:
                for chunk in split_message(message):
                    await self._app.bot.send_message(
                        chat_id=self._notify_chat_id,
                        text=chunk,
                    )
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")

    def _agent_ready(self) -> bool:
        """Check if agent can be used, return False with error message if not."""
        return self.agent is not None

    def _agent_error_msg(self) -> str:
        return (
            f"Agent not available: {self._agent_error}\n\n"
            "Make sure your .env has:\n"
            "  XAI_API_KEY (or OPENAI_API_KEY)\n"
            "  POLYMARKET_WALLET_ADDRESS\n\n"
            "Then restart the bot."
        )

    async def _send(self, update: Update, text: str):
        """Send a message, splitting if too long."""
        chat = update.effective_chat
        for chunk in split_message(text):
            await chat.send_message(chunk)

    async def _send_with_confirm(self, update: Update, text: str):
        """Send a message with Yes/No inline buttons for order confirmation."""
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Confirm", callback_data="confirm_order"),
                    InlineKeyboardButton("Cancel", callback_data="cancel_order"),
                ]
            ]
        )
        await update.effective_chat.send_message(text, reply_markup=keyboard)

    # ---- Handlers ----

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_authorized(update.effective_user.id):
            await update.message.reply_text("Unauthorized.")
            return

        # Register chat ID for auto-trade notifications
        self._notify_chat_id = update.effective_chat.id

        status = "ready" if self._agent_ready() else "starting (some features may be unavailable)"
        await update.message.reply_text(
            f"🤖 Polymarket Agent {status}.\n"
            "Send me commands in natural language.\n\n"
            "Quick commands:\n"
            "/help - All commands\n"
            "/balance - USDC balance\n"
            "/positions - Your positions\n"
            "/orders - Open orders\n"
            "/markets [n] - Top markets\n"
            "/events [n] - Top events\n"
            "/cancel <id|all> - Cancel orders\n\n"
            "🤖 Auto-Trading:\n"
            "/autotrade - Start auto-trading (dry run)\n"
            "/autotrade_live - Start LIVE auto-trading\n"
            "/stop_autotrade - Stop auto-trading\n"
            "/trade_status - Auto-trader status\n"
            "/trade_now - Run one cycle immediately"
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_authorized(update.effective_user.id):
            return

        help_text = (
            "POLYMARKET BOT\n\n"
            "📊 Slash commands:\n"
            "  /balance - Check USDC balance\n"
            "  /positions [limit] - View positions & P/L\n"
            "  /orders - View open orders\n"
            "  /markets [limit] - List active markets\n"
            "  /events [limit] - List active events\n"
            "  /cancel <order_id> - Cancel an order\n"
            "  /cancel all - Cancel all orders\n\n"
            "🤖 Auto-Trading v2:\n"
            "  /autotrade - Start auto-trading (dry run)\n"
            "  /autotrade_live - Start LIVE auto-trading\n"
            "  /stop_autotrade - Stop auto-trading\n"
            "  /trade_status - Status + performance\n"
            "  /trade_now - Run one cycle (dry)\n"
            "  /trade_now_live - Run one LIVE cycle\n\n"
            "📊 Performance & Config:\n"
            "  /stats - Win rate, P&L, Sharpe ratio\n"
            "  /strategies - Strategy ranking (auto-learning)\n"
            "  /speed fast|normal - Set cycle speed\n"
            "  /stoploss 30 - Set stop-loss (-30%)\n"
            "  /takeprofit 15 - Set take-profit (+15%)\n\n"
            "💬 Or just type in natural language:\n"
            '  "search markets about AI"\n'
            '  "info on market 12345"\n'
            '  "buy 10 of <token_id> at 0.65"\n'
            '  "sell 5 of <token_id> at 0.80"\n'
            '  "forecast: will X happen?"\n'
            '  "what\'s my balance"\n'
            '  "show my positions"\n'
        )
        await self._send(update, help_text)

    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_authorized(update.effective_user.id):
            return
        if not self._agent_ready():
            await self._send(update, self._agent_error_msg())
            return

        result = self.agent._handle_get_balance({})
        await self._send(update, result)

    async def cmd_markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_authorized(update.effective_user.id):
            return
        if not self._agent_ready():
            await self._send(update, self._agent_error_msg())
            return

        await update.message.reply_text("Fetching markets...")
        args = context.args
        limit = int(args[0]) if args else 5
        result = self.agent._handle_get_markets({"limit": limit})
        await self._send(update, result)

    async def cmd_events(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_authorized(update.effective_user.id):
            return
        if not self._agent_ready():
            await self._send(update, self._agent_error_msg())
            return

        await update.message.reply_text("Fetching events...")
        args = context.args
        limit = int(args[0]) if args else 5
        result = self.agent._handle_get_events({"limit": limit})
        await self._send(update, result)

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_authorized(update.effective_user.id):
            return
        if not self._agent_ready():
            await self._send(update, self._agent_error_msg())
            return

        await update.message.reply_text("Fetching positions...")
        args = context.args
        limit = int(args[0]) if args else 20
        result = self.agent._handle_get_positions({"limit": limit})
        await self._send(update, result)

    async def cmd_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_authorized(update.effective_user.id):
            return
        if not self._agent_ready():
            await self._send(update, self._agent_error_msg())
            return

        await update.message.reply_text("Fetching open orders...")
        result = self.agent._handle_get_open_orders({})
        await self._send(update, result)

    async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_authorized(update.effective_user.id):
            return
        if not self._agent_ready():
            await self._send(update, self._agent_error_msg())
            return

        args = context.args
        if not args:
            await update.message.reply_text(
                "Usage:\n"
                "  /cancel <order_id>  - Cancel a specific order\n"
                "  /cancel all         - Cancel all open orders"
            )
            return

        if args[0].lower() == "all":
            result = self.agent._handle_cancel_all_orders({})
        else:
            result = self.agent._handle_cancel_order({"order_id": args[0]})
        await self._send(update, result)

    # ---- Auto-Trade Handlers ----

    async def cmd_autotrade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start auto-trading in DRY RUN mode."""
        if not is_authorized(update.effective_user.id):
            return
        if not self._agent_ready():
            await self._send(update, self._agent_error_msg())
            return

        self._notify_chat_id = update.effective_chat.id

        trader = self.auto_trader
        if trader is None:
            await self._send(update, "❌ Failed to initialize auto-trader.")
            return

        trader.set_dry_run(True)
        result = await trader.start()
        # Don't send again - start() already notifies via callback

    async def cmd_autotrade_live(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start auto-trading in LIVE mode (real money!)."""
        if not is_authorized(update.effective_user.id):
            return
        if not self._agent_ready():
            await self._send(update, self._agent_error_msg())
            return

        if not self.agent.polymarket:
            await self._send(
                update,
                "❌ Cannot start live trading: wallet not connected.\n"
                "Set POLYGON_WALLET_PRIVATE_KEY in .env and restart.",
            )
            return

        self._notify_chat_id = update.effective_chat.id

        trader = self.auto_trader
        if trader is None:
            await self._send(update, "❌ Failed to initialize auto-trader.")
            return

        # Start LIVE immediately — no confirmation needed
        trader.set_dry_run(False)
        await self._send(
            update,
            f"🚀 LIVE auto-trading starting!\n"
            f"  💰 Max/trade: ${trader.max_trade_amount}\n"
            f"  ⚡ Fast: every {trader.fast_interval_sec}s | 🔄 Deep: every {trader.fast_interval_sec * trader.deep_interval_cycles}s"
        )
        await trader.start()

    async def cmd_stop_autotrade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stop auto-trading."""
        if not is_authorized(update.effective_user.id):
            return

        trader = self.auto_trader
        if trader is None or not trader.running:
            await self._send(update, "Auto-trader is not running.")
            return

        result = await trader.stop()
        # stop() already notifies via callback

    async def cmd_trade_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show auto-trader status."""
        if not is_authorized(update.effective_user.id):
            return

        trader = self.auto_trader
        if trader is None:
            await self._send(update, "Auto-trader not initialized. Send /autotrade to start.")
            return

        await self._send(update, await trader.get_status())

    async def cmd_trade_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Run one auto-trade cycle immediately (dry run)."""
        if not is_authorized(update.effective_user.id):
            return
        if not self._agent_ready():
            await self._send(update, self._agent_error_msg())
            return

        self._notify_chat_id = update.effective_chat.id

        trader = self.auto_trader
        if trader is None:
            await self._send(update, "❌ Failed to initialize auto-trader.")
            return

        trader.set_dry_run(True)
        await update.message.reply_text("🔄 Running analysis cycle (dry run)...")
        await trader.run_cycle()

    async def cmd_trade_now_live(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Run one LIVE auto-trade cycle immediately."""
        if not is_authorized(update.effective_user.id):
            return
        if not self._agent_ready():
            await self._send(update, self._agent_error_msg())
            return

        if not self.agent.polymarket:
            await self._send(
                update,
                "❌ Cannot trade live: wallet not connected.",
            )
            return

        self._notify_chat_id = update.effective_chat.id

        trader = self.auto_trader
        if trader is None:
            await self._send(update, "❌ Failed to initialize auto-trader.")
            return

        # Confirmation
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⚠️ Yes, execute LIVE",
                        callback_data="confirm_live_cycle",
                    ),
                    InlineKeyboardButton("Cancel", callback_data="cancel_live_cycle"),
                ]
            ]
        )
        await update.effective_chat.send_message(
            "⚠️ This will analyze markets and execute REAL trades.\n"
            f"  Max per trade: ${trader.max_trade_amount}\n"
            f"  Max trades: {trader.max_trades_per_cycle}\n\n"
            "Proceed?",
            reply_markup=keyboard,
        )

    # ─── New v2 commands: stats, strategies, speed, stoploss, takeprofit ───

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show trading performance statistics from SQLite."""
        if not is_authorized(update.effective_user.id):
            return
        trader = self.auto_trader
        if trader and trader.trade_db:
            summary = trader.trade_db.get_stats_summary()
            await self._send(update, summary)
        else:
            await self._send(update, "📊 Sem dados de trading ainda. Inicie o auto-trader primeiro.")

    async def cmd_strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show strategy performance ranking."""
        if not is_authorized(update.effective_user.id):
            return
        trader = self.auto_trader
        if trader and trader.trade_db:
            report = trader.trade_db.get_strategy_report_for_llm()
            weights = trader.trade_db.get_strategy_weights()
            lines = [report, "", "📊 WEIGHTS (auto-learning):"]
            for s, w in sorted(weights.items(), key=lambda x: x[1], reverse=True):
                bar_len = int(w * 10)
                bar = "█" * bar_len + "░" * (10 - bar_len)
                lines.append(f"  {s}: [{bar}] {w:.2f}x")
            await self._send(update, "\n".join(lines))
        else:
            await self._send(update, "📊 Sem dados. Inicie o auto-trader primeiro.")

    async def cmd_speed(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set trading speed: /speed fast or /speed normal."""
        if not is_authorized(update.effective_user.id):
            return
        trader = self.auto_trader
        if not trader:
            await self._send(update, "❌ Auto-trader não inicializado.")
            return
        args = context.args
        if args and args[0].lower() in ("fast", "normal"):
            result = trader.set_speed(args[0].lower())
            await self._send(update, result)
        else:
            mode = getattr(trader, 'speed_mode', 'fast')
            await self._send(update, (
                f"Modo atual: {mode}\n"
                f"  ⚡ Fast: {trader.fast_interval_sec}s entre ciclos\n"
                f"  🔄 Deep: a cada {trader.deep_interval_cycles} fast cycles\n\n"
                f"Use: /speed fast ou /speed normal"
            ))

    async def cmd_stoploss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set stop-loss: /stoploss 30 (for -30%)."""
        if not is_authorized(update.effective_user.id):
            return
        trader = self.auto_trader
        if not trader:
            await self._send(update, "❌ Auto-trader não inicializado.")
            return
        args = context.args
        if args:
            try:
                pct = float(args[0])
                result = trader.set_stop_loss(pct)
                await self._send(update, result)
            except ValueError:
                await self._send(update, "Use: /stoploss 30 (para -30%)")
        else:
            await self._send(update, f"📉 Stop-loss atual: -{trader.position_manager.stop_loss_pct}%\nUse: /stoploss 30")

    async def cmd_takeprofit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set take-profit: /takeprofit 15 (for +15%)."""
        if not is_authorized(update.effective_user.id):
            return
        trader = self.auto_trader
        if not trader:
            await self._send(update, "❌ Auto-trader não inicializado.")
            return
        args = context.args
        if args:
            try:
                pct = float(args[0])
                result = trader.set_take_profit(pct)
                await self._send(update, result)
            except ValueError:
                await self._send(update, "Use: /takeprofit 15 (para +15%)")
        else:
            await self._send(update, f"📈 Take-profit atual: +{trader.position_manager.take_profit_pct}%\nUse: /takeprofit 15")

    async def _start_auto_goal(self, update: Update, start_amount: float,
                               goal_amount: float, interval_min: int):
        """Start goal-based auto-trading with confirmation."""
        self._notify_chat_id = update.effective_chat.id

        trader = self.auto_trader
        if trader is None:
            await self._send(update, "❌ Falha ao inicializar auto-trader.")
            return

        # Store goal params for confirmation callback
        user_id = update.effective_user.id
        self._pending_goals = getattr(self, "_pending_goals", {})
        self._pending_goals[user_id] = {
            "start_amount": start_amount,
            "goal_amount": goal_amount,
            "interval_min": interval_min,
        }

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"🚀 Sim, começar LIVE!",
                        callback_data="confirm_goal_live",
                    ),
                    InlineKeyboardButton(
                        "🧪 Simulação primeiro",
                        callback_data="confirm_goal_dry",
                    ),
                ],
                [
                    InlineKeyboardButton("❌ Cancelar", callback_data="cancel_goal"),
                ],
            ]
        )
        await update.effective_chat.send_message(
            f"🚀 TRADING COM META\n\n"
            f"💰 Valor por trade: ${start_amount:.2f}\n"
            f"🎯 Meta: ${goal_amount:.2f}\n"
            f"⏱ Intervalo: a cada {interval_min} min\n\n"
            f"A IA vai analisar mercados e fazer trades de ${start_amount:.2f} "
            f"até seu portfólio atingir ${goal_amount:.2f}.\n\n"
            f"Como quer começar?",
            reply_markup=keyboard,
        )

    # ---- Message & Callback Handlers ----

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all free-text messages via the LLM command parser."""
        user_id = update.effective_user.id
        if not is_authorized(user_id):
            await update.message.reply_text("Unauthorized.")
            return

        if not self._agent_ready():
            await self._send(update, self._agent_error_msg())
            return

        text = update.message.text.strip()
        if not text:
            return

        # Register chat for notifications
        self._notify_chat_id = update.effective_chat.id

        # If there's a pending order for this user and they typed yes/no
        if user_id in self._pending_orders:
            if text.lower() in ("yes", "y", "confirm"):
                order = self._pending_orders.pop(user_id)
                result = self._execute_order(order)
                await self._send(update, result)
            else:
                self._pending_orders.pop(user_id, None)
                await update.message.reply_text("Order cancelled.")
            return

        await update.message.reply_text("🔄 Processando...")

        try:
            command = self.agent.parse_command(text)
            tool = command.get("tool", "")

            # smart_bet: execute automatically without confirmation
            if tool == "smart_bet":
                result = self.agent.execute(command)
                if self.agent.has_pending_order():
                    # Auto-execute the order
                    order = self.agent._pending_order
                    self.agent._pending_order = None
                    await self._send(update, result + "\n\n⏳ Executando automaticamente...")
                    exec_result = self._execute_order(order)
                    await self._send(update, exec_result)
                else:
                    await self._send(update, result)

            # For buy/sell, use Telegram confirmation buttons
            elif tool in ("buy", "sell"):
                result = self.agent.execute(command)
                if self.agent.has_pending_order():
                    self._pending_orders[user_id] = self.agent._pending_order
                    self.agent._pending_order = None
                    await self._send_with_confirm(update, result)
                else:
                    await self._send(update, result)

            # auto_goal: intercept and start goal-based trading
            elif tool == "auto_goal":
                result = self.agent.execute(command)
                try:
                    goal_data = json.loads(result)
                    if goal_data.get("__auto_goal__"):
                        await self._start_auto_goal(
                            update,
                            goal_data["start_amount"],
                            goal_data["goal_amount"],
                            goal_data.get("interval_min", 15),
                        )
                        return
                except (json.JSONDecodeError, KeyError):
                    pass
                await self._send(update, result)

            else:
                result = self.agent.execute(command)
                await self._send(update, result)

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            logger.error(traceback.format_exc())
            await update.message.reply_text(f"❌ Erro: {e}")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button presses for order confirmation & auto-trade."""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        if not is_authorized(user_id):
            await query.edit_message_text("Unauthorized.")
            return

        action = query.data

        # --- Manual order confirmation ---
        if action == "confirm_order":
            order = self._pending_orders.pop(user_id, None)
            if order is None:
                await query.edit_message_text("No pending order found.")
                return
            result = self._execute_order(order)
            await query.edit_message_text(result)

        elif action == "cancel_order":
            self._pending_orders.pop(user_id, None)
            await query.edit_message_text("Order cancelled.")

        # --- Auto-trade live confirmation ---
        elif action == "confirm_live_autotrade":
            trader = self.auto_trader
            if trader:
                trader.set_dry_run(False)
                await query.edit_message_text("⚠️ LIVE auto-trading starting...")
                await trader.start()
            else:
                await query.edit_message_text("❌ Auto-trader not available.")

        elif action == "cancel_live_autotrade":
            await query.edit_message_text("Live auto-trading cancelled.")

        elif action == "confirm_live_cycle":
            trader = self.auto_trader
            if trader:
                trader.set_dry_run(False)
                await query.edit_message_text("⚠️ Running LIVE trade cycle...")
                await trader.run_cycle()
                trader.set_dry_run(True)  # Reset to dry run after single cycle
            else:
                await query.edit_message_text("❌ Auto-trader not available.")

        elif action == "cancel_live_cycle":
            await query.edit_message_text("Ciclo live cancelado.")

        # --- Goal-based trading confirmation ---
        elif action in ("confirm_goal_live", "confirm_goal_dry"):
            is_live = action == "confirm_goal_live"
            pending_goals = getattr(self, "_pending_goals", {})
            goal = pending_goals.pop(user_id, None)
            if goal:
                trader = self.auto_trader
                if trader:
                    mode_label = "LIVE" if is_live else "SIMULAÇÃO"
                    await query.edit_message_text(
                        f"🚀 Iniciando {mode_label} com meta ${goal['goal_amount']:.2f}...\n"
                        f"Aguarde o primeiro ciclo..."
                    )
                    # Schedule as background task to not block the callback
                    import asyncio
                    asyncio.create_task(self._run_goal_trader(
                        trader, goal, dry_run=not is_live
                    ))
                else:
                    await query.edit_message_text("❌ Auto-trader não disponível.")
            else:
                await query.edit_message_text("❌ Nenhuma meta pendente.")

        elif action == "cancel_goal":
            pending_goals = getattr(self, "_pending_goals", {})
            pending_goals.pop(user_id, None)
            await query.edit_message_text("❌ Trading com meta cancelado.")

    async def _run_goal_trader(self, trader, goal: dict, dry_run: bool):
        """Run goal-based trader as a background task."""
        try:
            logger.info(f"Starting goal trader: ${goal['start_amount']} -> ${goal['goal_amount']} (dry_run={dry_run})")
            result = await trader.start_with_goal(
                start_amount=goal["start_amount"],
                goal_amount=goal["goal_amount"],
                interval_min=goal["interval_min"],
                dry_run=dry_run,
            )
            # If start_with_goal returns a string (e.g. "goal already met"), send it
            if result and isinstance(result, str) and self._notify_chat_id and self._app:
                try:
                    await self._app.bot.send_message(
                        chat_id=self._notify_chat_id,
                        text=result,
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Goal trader error: {e}")
            logger.error(traceback.format_exc())
            if self._notify_chat_id and self._app:
                try:
                    await self._app.bot.send_message(
                        chat_id=self._notify_chat_id,
                        text=f"❌ Erro no auto-trader: {e}",
                    )
                except Exception:
                    pass

    def _execute_order(self, order: dict) -> str:
        """Execute an order using aggressive pricing for instant fill.

        Uses execute_aggressive_order which reads the orderbook and places
        the order at the best available price to guarantee immediate fill.
        """
        try:
            amount = float(order["amount"])
            side = order["side"]
            token_id = order["token_id"]

            result = self.agent.polymarket.execute_aggressive_order(
                token_id=token_id,
                side=side,
                amount=amount,
            )
            return (
                f"✅ {side} ${amount:.2f} executado imediatamente!\n"
                f"Resultado: {result}"
            )
        except Exception as e:
            return f"❌ Erro ao executar {order.get('side', '').lower()}: {e}"

    def run(self):
        """Start the Telegram bot (long polling)."""
        app = Application.builder().token(self.token).build()
        self._app = app

        # Slash commands
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("balance", self.cmd_balance))
        app.add_handler(CommandHandler("markets", self.cmd_markets))
        app.add_handler(CommandHandler("events", self.cmd_events))
        app.add_handler(CommandHandler("positions", self.cmd_positions))
        app.add_handler(CommandHandler("orders", self.cmd_orders))
        app.add_handler(CommandHandler("cancel", self.cmd_cancel))

        # Auto-trade commands
        app.add_handler(CommandHandler("autotrade", self.cmd_autotrade))
        app.add_handler(CommandHandler("autotrade_live", self.cmd_autotrade_live))
        app.add_handler(CommandHandler("stop_autotrade", self.cmd_stop_autotrade))
        app.add_handler(CommandHandler("trade_status", self.cmd_trade_status))
        app.add_handler(CommandHandler("trade_now", self.cmd_trade_now))
        app.add_handler(CommandHandler("trade_now_live", self.cmd_trade_now_live))

        # v2 commands: stats, strategies, speed, stoploss, takeprofit
        app.add_handler(CommandHandler("stats", self.cmd_stats))
        app.add_handler(CommandHandler("strategies", self.cmd_strategies))
        app.add_handler(CommandHandler("speed", self.cmd_speed))
        app.add_handler(CommandHandler("stoploss", self.cmd_stoploss))
        app.add_handler(CommandHandler("takeprofit", self.cmd_takeprofit))

        # Inline button callbacks
        app.add_handler(CallbackQueryHandler(self.handle_callback))

        # Free-text messages (catch-all, must be last)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        logger.info("Telegram bot starting...")
        print("Telegram bot is running. Send messages to your bot.")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    bot = TelegramPolymarketBot()
    bot.run()


if __name__ == "__main__":
    main()
