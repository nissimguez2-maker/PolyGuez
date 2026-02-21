"""
Auto Trader Module v2 — Continuous Trading Engine with Auto-Learning

Architecture:
  - FAST CYCLE (30s): Position manager + crypto spikes + parity arb → direct execution
  - DEEP CYCLE (5min): All 6 strategies + LLM analysis → intelligent trades
  - AUTO-LEARNING: SQLite tracks every trade, adjusts strategy weights over time

Modes:
  1. Continuous auto-trading with dual-speed cycles
  2. Goal-based trading (trade until portfolio hits target)
  3. Turbo mode (30s cycles only, no LLM, pure strategy signals)

Flow:
  1. FAST: Check positions → stop-loss/take-profit → crypto spikes → parity arb
  2. DEEP: Full market scan → strategy engine → LLM analysis → execute trades
  3. LEARN: Record results → update strategy weights → feedback to next cycle
"""

import os
import sys
import json
import time
import asyncio
import logging
import functools
import traceback
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


AUTO_TRADER_SYSTEM_PROMPT = """Você é um trader expert e agressivo do Polymarket. Seu objetivo é MAXIMIZAR lucros com trades constantes.

Você vai receber:
- Saldo USDC atual
- Posições abertas com P&L
- Mercados trending/ativos com preços, token IDs e outcomes
- Sinais das 6 estratégias automáticas (já pré-analisados pelo scanner)
- PERFORMANCE HISTÓRICA das estratégias (win rates reais do bot)
- Ordens abertas
- Trades automáticos já executados neste ciclo (arbs, stop-loss, take-profit)

## 6 ESTRATÉGIAS DE LUCRO (PRIORIZADAS):

### 1. ARBITRAGEM TEMPORAL/LATÊNCIA (PRIORIDADE 1 - QUANDO DISPONÍVEL)
- Bot lê preços de BTC/ETH/SOL em tempo real da Binance
- Se crypto subiu >0.3% no último minuto e mercado de 15-min ainda não ajustou → COMPRE
- Sinais "LATENCY_ARB" já identificados com confiança (confidence)
- EXECUTE IMEDIATAMENTE quando confidence > 0.7

### 2. ARBITRAGEM YES+NO (PRIORIDADE 2 - RISCO ZERO)
- Se YES + NO < $0.97, compre AMBOS para lucro garantido
- Sinais "PARITY_ARB" já calcularam lucro líquido após taxas
- SEMPRE execute quando net_profit_pct > 1%

### 3. VIÉS CONTRÁRIO / NO BIAS (70% dos mercados resolvem NO)
- Compre NO em mercados overhyped onde YES está entre 0.15-0.55
- Sinais "NO_BIAS" identificam mercados com volume alto e hype
- Retorno esperado baseado em taxa de resolução NO de 70%

### 4. AUTO-COMPOSIÇÃO DE ALTA PROBABILIDADE
- Compre outcomes com 92-98% de probabilidade
- Retorno pequeno (2-8%) mas muito seguro
- Sinais "HIGH_PROB" para composição progressiva

### 5. LONG SHOTS (1-5 centavos)
- Compre outcomes baratos (1-5 centavos) com upside assimétrico
- Se acertar 1 em 20, ainda é lucrativo (20x-100x retorno)
- NUNCA mais que $1-2 por long shot

### 6. GESTÃO DE PORTFÓLIO ATIVA
- Venda posições perdedoras RÁPIDO (stop-loss automático já cuida disso)
- Venda posições com lucro > 15% para realizar ganhos
- O bot JÁ EXECUTOU trades automáticos de stop-loss e take-profit neste ciclo
- Foque em NOVAS oportunidades de entrada

## AUTO-LEARNING
- Você recebe a PERFORMANCE REAL de cada estratégia (win rate, P&L)
- PRIORIZE estratégias com win rate > 60%
- EVITE estratégias com win rate < 40% (a menos que a oportunidade seja excepcional)
- As weights das estratégias refletem o aprendizado do bot

REGRAS:
- PRIORIZE baseado no AUTO-LEARNING: estratégias com melhor win rate primeiro
- Para sinais com confidence > 0.8, SEMPRE execute
- Para vendas, só venda posições que já existem
- Use USDC values inteiros ($1, $2, $5) para amount
- NUNCA gaste mais que 40% do saldo em um único trade (exceto arbitragem risk-free)
- Para LONGSHOTS, use no máximo $1-2
- SEJA ATIVO: prefira fazer trades do que não fazer nada

IMPORTANTE SOBRE AMOUNT E PRICE:
- "amount" = valor em USDC (dólares) que você quer GASTAR no trade
- "price" = preço por share/contrato (entre 0.01 e 0.99)
- O sistema usa ordens AGRESSIVAS que executam imediatamente no melhor preço
- Exemplo: amount=5.0 com price=0.10 → compra ~50 shares por ~$5 USDC

Responda com APENAS JSON válido neste formato:
{
  "analysis": "Análise breve e raciocínio (2-3 frases em português)",
  "trades": [
    {
      "action": "BUY" ou "SELL",
      "token_id": "o token ID string",
      "market_question": "a pergunta do mercado",
      "amount": 5.0,
      "price": 0.65,
      "strategy": "LATENCY_ARB|PARITY_ARB|NO_BIAS|HIGH_PROB|LONGSHOT|VALUE",
      "reasoning": "Por que esse trade faz sentido (em português)"
    }
  ],
  "portfolio_notes": "Notas sobre saúde do portfólio (em português)"
}

Se nenhum trade deve ser feito:
{
  "analysis": "Análise explicando por que nenhum trade",
  "trades": [],
  "portfolio_notes": "Avaliação do portfólio"
}
"""


def _build_llm():
    """Build LLM client for auto-trader analysis. Priority: Claude > xAI > OpenAI."""
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    xai_key = os.getenv("XAI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if anthropic_key:
        from langchain_anthropic import ChatAnthropic
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        logger.info(f"AutoTrader using Anthropic Claude: {model}")
        return ChatAnthropic(
            model=model,
            temperature=0.3,
            api_key=anthropic_key,
        )
    elif xai_key:
        from langchain_openai import ChatOpenAI
        model = os.getenv("XAI_MODEL", "grok-3-mini")
        logger.info(f"AutoTrader using xAI Grok: {model}")
        return ChatOpenAI(
            model=model,
            temperature=0.3,
            api_key=xai_key,
            base_url="https://api.x.ai/v1",
        )
    elif openai_key:
        from langchain_openai import ChatOpenAI
        model = os.getenv("OPENAI_MODEL", "gpt-4-1106-preview")
        logger.info(f"AutoTrader using OpenAI: {model}")
        return ChatOpenAI(model=model, temperature=0.3)
    else:
        raise ValueError("No LLM API key. Set ANTHROPIC_API_KEY, XAI_API_KEY, or OPENAI_API_KEY.")


# ─── Position Manager ───

class PositionManager:
    """
    Monitors open positions and automatically triggers:
    - Stop-loss (sell at -X%)
    - Take-profit (sell at +Y%)
    - Trailing stop (lock breakeven after +Z%)
    - Time-based exit (sell before market closes)
    """

    def __init__(self, trade_db=None):
        self.stop_loss_pct = float(os.getenv("STOP_LOSS_PCT", "30"))     # -30%
        self.take_profit_pct = float(os.getenv("TAKE_PROFIT_PCT", "15")) # +15%
        self.trailing_stop_trigger = 20.0  # activate trailing stop after +20%
        self.trade_db = trade_db

    def check_exit_rules(self, position: dict) -> Optional[dict]:
        """
        Check if a position should be exited.
        Returns a trade dict if exit needed, None otherwise.
        """
        size = float(position.get("size", 0))
        if size <= 0:
            return None

        percent_pnl = float(position.get("percentPnl", 0))
        cash_pnl = float(position.get("cashPnl", 0))
        token_id = position.get("asset", "")
        market = position.get("title", "")
        cur_price = float(position.get("curPrice", 0))
        avg_price = float(position.get("avgPrice", 0))

        if not token_id:
            return None

        # 1. Stop-loss: P&L < -stop_loss_pct
        if percent_pnl <= -self.stop_loss_pct:
            return {
                "action": "SELL",
                "token_id": token_id,
                "market_question": market,
                "amount": size,  # sell all shares
                "price": cur_price if cur_price > 0 else 0.01,
                "strategy": "STOP_LOSS",
                "reasoning": f"STOP-LOSS: posição caiu {percent_pnl:.1f}% (limite: -{self.stop_loss_pct}%)",
                "is_exit": True,
                "exit_reason": "STOP_LOSS",
            }

        # 2. Take-profit: P&L > +take_profit_pct
        if percent_pnl >= self.take_profit_pct:
            return {
                "action": "SELL",
                "token_id": token_id,
                "market_question": market,
                "amount": size,
                "price": cur_price if cur_price > 0 else 0.99,
                "strategy": "TAKE_PROFIT",
                "reasoning": f"TAKE-PROFIT: lucro de {percent_pnl:.1f}% (limite: +{self.take_profit_pct}%)",
                "is_exit": True,
                "exit_reason": "TAKE_PROFIT",
            }

        # 3. Trailing stop: if position was up +20% but fell back near entry
        if self.trade_db:
            peak = self.trade_db.get_position_peak_pnl(token_id)
            if peak >= self.trailing_stop_trigger and percent_pnl <= 2:
                return {
                    "action": "SELL",
                    "token_id": token_id,
                    "market_question": market,
                    "amount": size,
                    "price": cur_price if cur_price > 0 else avg_price,
                    "strategy": "TAKE_PROFIT",
                    "reasoning": f"TRAILING STOP: pico de +{peak:.1f}% agora {percent_pnl:.1f}%",
                    "is_exit": True,
                    "exit_reason": "TRAILING_STOP",
                }

        return None


# ─── Auto Trader ───

class AutoTrader:
    """
    Continuous trading engine with auto-learning.

    Dual-speed loop:
    - FAST cycle (30s): position mgmt + crypto arb + parity arb (no LLM)
    - DEEP cycle (5min): full strategy scan + LLM analysis
    """

    def __init__(self, agent):
        self.agent = agent
        self.llm = _build_llm()
        self.running = False
        self._task: Optional[asyncio.Task] = None

        # Strategy engine
        try:
            from scripts.python.strategies import StrategyEngine
            self.strategy_engine = StrategyEngine()
            logger.info("Strategy engine initialized with 6 strategies")
        except ImportError:
            try:
                from strategies import StrategyEngine
                self.strategy_engine = StrategyEngine()
                logger.info("Strategy engine initialized with 6 strategies (relative import)")
            except ImportError:
                self.strategy_engine = None
                logger.warning("Strategy engine not available - using LLM-only mode")

        # Trade database
        try:
            from scripts.python.trade_db import TradeDB
            self.trade_db = TradeDB()
            logger.info("Trade database initialized")
        except ImportError:
            try:
                from trade_db import TradeDB
                self.trade_db = TradeDB()
                logger.info("Trade database initialized (relative import)")
            except ImportError:
                self.trade_db = None
                logger.warning("Trade database not available")

        # Position manager
        self.position_manager = PositionManager(trade_db=self.trade_db)

        # Blacklist: token_ids whose orderbook no longer exists (expired/resolved markets)
        self._dead_markets: set = set()

        # Config
        self.fast_interval_sec = int(os.getenv("AUTOTRADE_FAST_INTERVAL_SEC", "30"))
        self.deep_interval_cycles = int(os.getenv("AUTOTRADE_DEEP_EVERY_N", "10"))  # deep every N fast cycles
        self.max_trade_amount = float(os.getenv("AUTOTRADE_MAX_AMOUNT", "25"))
        self.max_trades_per_cycle = int(os.getenv("AUTOTRADE_MAX_TRADES", "15"))
        self.dry_run = os.getenv("AUTOTRADE_DRY_RUN", "true").lower() == "true"

        # Legacy support
        legacy_interval = os.getenv("AUTOTRADE_INTERVAL_MIN")
        if legacy_interval:
            self.fast_interval_sec = int(legacy_interval) * 60
            self.deep_interval_cycles = 1  # every cycle is deep in legacy mode

        # Speed mode
        self.speed_mode = "fast"  # "fast" (30s) or "normal" (5min deep cycles)

        # Goal-based trading
        self.goal_mode = False
        self.goal_amount = 0.0
        self.goal_start_amount = 0.0

        # Telegram callback
        self._notify_callback = None

        # Counters
        self.trade_history = []
        self.cycle_count = 0
        self.fast_cycle_count = 0
        self.auto_trades_count = 0  # trades without LLM
        self.llm_trades_count = 0   # trades via LLM

        # Balance-based bet sizing tiers
        # Format: (min_balance, max_bet, multiplier_label)
        # Bot adjusts bet size dynamically based on available USDC
        self._cached_balance = 0.0
        self._balance_tiers = [
            (100.0,  25.0,  "🟢 Full"),     # $100+ → bet up to $25
            (50.0,   10.0,  "🟡 Medium"),    # $50-100 → bet up to $10
            (20.0,   5.0,   "🟠 Small"),     # $20-50 → bet up to $5
            (5.0,    2.0,   "🔴 Micro"),     # $5-20 → bet up to $2
            (1.0,    0.50,  "⚫ Survival"),  # $1-5 → bet up to $0.50
            (0.0,    0.0,   "💀 No funds"),  # <$1 → no trading
        ]

        logger.info(
            f"AutoTrader v2: fast_interval={self.fast_interval_sec}s, "
            f"deep_every={self.deep_interval_cycles} cycles, "
            f"max_amount=${self.max_trade_amount}, "
            f"max_trades={self.max_trades_per_cycle}, "
            f"dry_run={self.dry_run}"
        )

    def set_notify_callback(self, callback):
        self._notify_callback = callback

    async def _notify(self, message: str):
        logger.info(f"AutoTrader: {message}")
        if self._notify_callback:
            try:
                await self._notify_callback(message)
            except Exception as e:
                logger.error(f"Notification failed: {e}")

    # ─── Balance-Based Bet Sizing ───

    def _get_usdc_balance_sync(self) -> float:
        """Get USDC balance from on-chain (Polygon)."""
        try:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
            wallet = Web3.to_checksum_address(self.agent.wallet_address)
            usdc_address = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
            abi = '[{"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"balanceOf","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]'
            usdc = w3.eth.contract(address=usdc_address, abi=abi)
            balance_raw = usdc.functions.balanceOf(wallet).call()
            return float(balance_raw / 1e6)
        except Exception as e:
            logger.error(f"Error getting USDC balance: {e}")
            return self._cached_balance  # return last known

    def _get_bet_tier(self, balance: float) -> tuple:
        """Get the bet tier for a given balance. Returns (max_bet, tier_label)."""
        for min_bal, max_bet, label in self._balance_tiers:
            if balance >= min_bal:
                return max_bet, label
        return 0.0, "💀 No funds"

    def _adjust_amount_for_balance(self, amount: float, balance: float) -> float:
        """Adjust trade amount based on current USDC balance using tiers.

        Tiers:
          $100+  → up to $25  (Full)
          $50+   → up to $10  (Medium)
          $20+   → up to $5   (Small)
          $5+    → up to $2   (Micro)
          $1+    → up to $0.50 (Survival)
          <$1    → $0 (no trading)

        Also ensures we never bet more than 40% of balance in a single trade.
        """
        max_bet, tier = self._get_bet_tier(balance)

        if max_bet <= 0:
            return 0.0

        # Cap at tier max
        adjusted = min(amount, max_bet)

        # Never bet more than 40% of balance
        safety_cap = balance * 0.40
        adjusted = min(adjusted, safety_cap)

        # Minimum viable bet on Polymarket
        if adjusted < 0.10:
            return 0.0

        return round(adjusted, 2)

    # ─── Portfolio ───

    def _get_portfolio_value_sync(self) -> float:
        """Get total portfolio value (USDC + positions)."""
        total = 0.0
        try:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
            wallet = Web3.to_checksum_address(self.agent.wallet_address)
            usdc_address = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
            abi = '[{"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"balanceOf","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]'
            usdc = w3.eth.contract(address=usdc_address, abi=abi)
            balance_raw = usdc.functions.balanceOf(wallet).call()
            total += float(balance_raw / 1e6)
        except Exception as e:
            logger.error(f"Error getting on-chain balance: {e}")

        try:
            import httpx
            wallet = self.agent.wallet_address
            if wallet:
                res = httpx.get(
                    "https://data-api.polymarket.com/positions",
                    params={"user": wallet, "sizeThreshold": 0, "limit": 100,
                            "sortBy": "CURRENT", "sortDirection": "DESC"},
                )
                if res.status_code == 200:
                    for p in res.json():
                        total += float(p.get("currentValue", 0))
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
        return total

    async def _get_portfolio_value(self) -> float:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_portfolio_value_sync)

    # ─── Position Management (FAST CYCLE) ───

    def _get_positions_sync(self) -> list:
        """Fetch current positions from Polymarket data API."""
        try:
            import httpx
            wallet = self.agent.wallet_address
            if not wallet:
                return []
            res = httpx.get(
                "https://data-api.polymarket.com/positions",
                params={"user": wallet, "sizeThreshold": 0, "limit": 50,
                        "sortBy": "CURRENT", "sortDirection": "DESC"},
            )
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
        return []

    async def _manage_positions(self) -> list:
        """Check all positions for stop-loss / take-profit / trailing stop. Returns exit trades."""
        loop = asyncio.get_event_loop()
        positions = await loop.run_in_executor(None, self._get_positions_sync)

        exit_trades = []
        for pos in positions:
            size = float(pos.get("size", 0))
            if size <= 0:
                continue

            # Skip markets whose orderbook no longer exists (expired/resolved)
            token_id = pos.get("asset", "")
            if token_id in self._dead_markets:
                continue

            # Record snapshot for trailing stop tracking
            if self.trade_db:
                self.trade_db.record_position_snapshot(
                    token_id=pos.get("asset", ""),
                    market=pos.get("title", ""),
                    size=size,
                    entry_price=float(pos.get("avgPrice", 0)),
                    current_price=float(pos.get("curPrice", 0)),
                    unrealized_pnl=float(pos.get("cashPnl", 0)),
                    percent_pnl=float(pos.get("percentPnl", 0)),
                )

            exit_trade = self.position_manager.check_exit_rules(pos)
            if exit_trade:
                exit_trades.append(exit_trade)

        # Cash liberation: if balance is very low, sell profitable positions to free up capital
        if self._cached_balance < 2.0 and not exit_trades:
            # Sort remaining positions by: profit first, then by value (highest first)
            sellable = []
            for pos in positions:
                size = float(pos.get("size", 0))
                token_id = pos.get("asset", "")
                cur_price = float(pos.get("curPrice", 0))
                current_value = float(pos.get("currentValue", 0))
                pnl_pct = float(pos.get("percentPnl", 0))

                if size <= 0 or token_id in self._dead_markets or cur_price <= 0.005:
                    continue  # skip dead/worthless positions

                sellable.append((pos, pnl_pct, current_value))

            # Sort: profitable first (highest PnL%), then highest value
            sellable.sort(key=lambda x: (-x[1], -x[2]))

            for pos, pnl_pct, current_value in sellable[:2]:  # sell up to 2 positions
                if current_value < 0.50:
                    continue  # not worth selling

                token_id = pos.get("asset", "")
                size = float(pos.get("size", 0))
                cur_price = float(pos.get("curPrice", 0))
                title = pos.get("title", "")

                reason = (
                    f"CASH-LIBERATION: saldo ${self._cached_balance:.2f} muito baixo. "
                    f"Vendendo posição (PnL: {pnl_pct:+.1f}%, val: ${current_value:.2f}) pra liberar caixa"
                )
                exit_trades.append({
                    "action": "SELL",
                    "token_id": token_id,
                    "market_question": title,
                    "amount": size,
                    "price": cur_price,
                    "strategy": "CASH_LIBERATION",
                    "reasoning": reason,
                    "is_exit": True,
                    "exit_reason": "CASH_LIBERATION",
                })
                logger.info(f"Cash liberation: selling '{title[:40]}' (val=${current_value:.2f}, PnL={pnl_pct:+.1f}%)")

        return exit_trades

    # ─── Direct Execution (No LLM) ───

    async def _execute_obvious_trades(self, context: dict) -> list:
        """Execute trades that don't need LLM analysis (arb > 2%, high-confidence signals)."""
        executed = []
        signals = context.get("strategy_signals", {})
        weights = self.trade_db.get_strategy_weights() if self.trade_db else {}

        # 1. Parity arbitrage with > 2% margin → execute directly
        parity_signals = signals.get("parity_arbitrage", [])
        for sig in parity_signals[:3]:
            net_profit = sig.get("net_profit_pct", 0)
            if net_profit >= 2.0:
                weight = weights.get("PARITY_ARB", 1.0)
                if weight < 0.3:
                    continue  # strategy disabled by auto-learning

                token_id = sig.get("token_id", "")
                if token_id:
                    trade = {
                        "action": "BUY",
                        "token_id": token_id,
                        "market_question": sig.get("question", "Parity Arb"),
                        "amount": min(3.0, self.max_trade_amount),
                        "price": sig.get("price", 0.50),
                        "strategy": "PARITY_ARB",
                        "reasoning": f"Arb automático: margin {net_profit:.1f}% (direto, sem LLM)",
                    }
                    result = await self._execute_trade(trade)
                    executed.append({"trade": trade, "result": result, "auto": True})

        # 2. Latency arb with confidence > 0.9 → execute directly
        latency_signals = signals.get("latency_arbitrage", [])
        for sig in latency_signals[:2]:
            confidence = sig.get("confidence", 0)
            if confidence >= 0.9:
                weight = weights.get("LATENCY_ARB", 1.0)
                if weight < 0.3:
                    continue

                token_id = sig.get("token_id", "")
                if token_id:
                    trade = {
                        "action": "BUY",
                        "token_id": token_id,
                        "market_question": sig.get("question", "Latency Arb"),
                        "amount": min(5.0, self.max_trade_amount),
                        "price": sig.get("price", 0.50),
                        "strategy": "LATENCY_ARB",
                        "reasoning": f"Latency arb automático: confidence {confidence:.2f} (direto, sem LLM)",
                    }
                    result = await self._execute_trade(trade)
                    executed.append({"trade": trade, "result": result, "auto": True})

        return executed

    # ─── Trade Execution ───

    async def _execute_trade(self, trade: dict) -> str:
        """Execute a single trade with SQLite tracking."""
        action = trade.get("action", "").upper()
        token_id = trade.get("token_id", "")
        amount = float(trade.get("amount", 0))
        price = float(trade.get("price", 0))
        market_q = trade.get("market_question", "")
        reasoning = trade.get("reasoning", "")
        strategy = trade.get("strategy", "MANUAL")
        is_exit = trade.get("is_exit", False)
        exit_reason = trade.get("exit_reason", "")
        confidence = trade.get("confidence", 0)

        if not all([token_id, amount, price, action in ("BUY", "SELL")]):
            return f"❌ Parâmetros inválidos: {trade}"

        if amount > self.max_trade_amount and strategy not in ("STOP_LOSS", "TAKE_PROFIT"):
            amount = self.max_trade_amount

        # Dynamic bet sizing: adjust BUY amount based on USDC balance
        if action == "BUY" and not self.dry_run:
            loop = asyncio.get_event_loop()
            balance = await loop.run_in_executor(None, self._get_usdc_balance_sync)
            self._cached_balance = balance
            original_amount = amount
            amount = self._adjust_amount_for_balance(amount, balance)
            if amount <= 0:
                _, tier = self._get_bet_tier(balance)
                return f"⏸️ SKIP BUY ${original_amount:.2f} — saldo ${balance:.2f} ({tier}), sem fundos suficientes"
            if amount != original_amount:
                _, tier = self._get_bet_tier(balance)
                logger.info(f"Bet sizing: ${original_amount:.2f} → ${amount:.2f} (saldo: ${balance:.2f}, tier: {tier})")

        # Convert USDC amount to shares (for BUY)
        if action == "BUY":
            size = round(amount / price, 2)
            if size < 5:
                size = 5
        else:
            size = amount  # for SELL, amount IS the number of shares

        if self.dry_run:
            result_msg = (
                f"[SIM] {action} ${amount:.2f} ({size:.0f}sh) '{market_q[:40]}' @{price}"
            )
            # Record in SQLite
            if self.trade_db:
                entry_id = 0
                if is_exit:
                    entry = self.trade_db.get_entry_trade_for_token(token_id)
                    entry_id = entry["id"] if entry else 0
                self.trade_db.record_trade(
                    action=action, token_id=token_id, market=market_q,
                    strategy=strategy, amount=amount, price=price, size=size,
                    result="SIMULAÇÃO", status="SIMULATED",
                    is_exit=is_exit, exit_reason=exit_reason,
                    entry_trade_id=entry_id, confidence=confidence,
                )
            self.trade_history.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "action": action, "token_id": token_id,
                "amount": amount, "price": price, "size": size,
                "market": market_q, "result": "SIMULAÇÃO", "strategy": strategy,
            })
            return result_msg

        # Real execution
        try:
            if not self.agent.polymarket:
                return "❌ Wallet não conectada."

            logger.info(f"EXEC {action} ${amount:.2f} ({strategy}) on '{market_q[:40]}'")

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.agent.polymarket.execute_aggressive_order(
                    token_id=token_id,
                    side=action,
                    amount=amount if action == "BUY" else size,
                )
            )

            # Record in SQLite
            if self.trade_db:
                entry_id = 0
                if is_exit:
                    entry = self.trade_db.get_entry_trade_for_token(token_id)
                    entry_id = entry["id"] if entry else 0
                self.trade_db.record_trade(
                    action=action, token_id=token_id, market=market_q,
                    strategy=strategy, amount=amount, price=price, size=size,
                    result=str(result)[:500], status="EXECUTED",
                    is_exit=is_exit, exit_reason=exit_reason,
                    entry_trade_id=entry_id, confidence=confidence,
                )

            self.trade_history.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "action": action, "token_id": token_id,
                "amount": amount, "price": price, "size": size,
                "market": market_q, "result": str(result), "strategy": strategy,
            })

            return (
                f"✅ {action} ${amount:.2f} ({size:.0f}sh) '{market_q[:40]}' @{price}\n"
                f"  [{strategy}] {reasoning[:60]}"
            )
        except Exception as e:
            error_str = str(e)
            # Detect expired/resolved markets — blacklist to avoid retrying every cycle
            if "No orderbook exists" in error_str or "status_code=404" in error_str:
                self._dead_markets.add(token_id)
                logger.info(f"Market expired, blacklisted: {market_q[:40]} ({token_id[:20]}...)")
            error_msg = f"❌ {action} ${amount:.2f} @{price} - {e}"
            if self.trade_db:
                self.trade_db.record_trade(
                    action=action, token_id=token_id, market=market_q,
                    strategy=strategy, amount=amount, price=price, size=size,
                    result=f"ERRO: {e}", status="FAILED",
                    is_exit=is_exit, exit_reason=exit_reason, confidence=confidence,
                )
            self.trade_history.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "action": action, "token_id": token_id,
                "amount": amount, "price": price, "size": size,
                "market": market_q, "result": f"ERRO: {e}", "strategy": strategy,
            })
            return error_msg

    # ─── Context Gathering ───

    def _gather_context_sync(self) -> dict:
        """Gather market state + run strategy engine."""
        context = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "balance": None,
            "positions": [],
            "markets": [],
            "open_orders": [],
            "arbitrage_opportunities": [],
            "strategy_signals": {},
            "crypto_prices": {},
        }

        # Balance
        try:
            balance_text = self.agent._handle_get_balance({})
            context["balance"] = balance_text
        except Exception as e:
            context["balance"] = f"Erro: {e}"

        # Positions
        try:
            import httpx
            wallet = self.agent.wallet_address
            if wallet:
                res = httpx.get(
                    "https://data-api.polymarket.com/positions",
                    params={"user": wallet, "sizeThreshold": 0, "limit": 50,
                            "sortBy": "CURRENT", "sortDirection": "DESC"},
                )
                if res.status_code == 200:
                    for p in res.json():
                        context["positions"].append({
                            "title": p.get("title", ""),
                            "outcome": p.get("outcome", ""),
                            "size": p.get("size", 0),
                            "avgPrice": p.get("avgPrice", 0),
                            "curPrice": p.get("curPrice", 0),
                            "currentValue": p.get("currentValue", 0),
                            "cashPnl": p.get("cashPnl", 0),
                            "percentPnl": p.get("percentPnl", 0),
                            "asset": p.get("asset", ""),
                        })
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")

        # Markets (top 200 by volume)
        try:
            raw_markets = self.agent.gamma.get_markets(querystring_params={
                "active": True, "closed": False,
                "limit": 200, "order": "volume", "ascending": False,
            })
            for m in raw_markets:
                token_ids = m.get("clobTokenIds", "")
                if isinstance(token_ids, str):
                    try: token_ids = json.loads(token_ids)
                    except: token_ids = []

                outcomes = m.get("outcomes", "")
                if isinstance(outcomes, str):
                    try: outcomes = json.loads(outcomes)
                    except: outcomes = []

                prices = m.get("outcomePrices", "")
                if isinstance(prices, str):
                    try: prices = json.loads(prices)
                    except: prices = []

                market_data = {
                    "question": m.get("question", ""),
                    "id": m.get("id", ""),
                    "outcomes": outcomes,
                    "prices": prices,
                    "token_ids": token_ids,
                    "spread": m.get("spread", 0),
                    "volume": m.get("volume", 0),
                    "liquidity": m.get("liquidity", 0),
                    "endDate": m.get("endDate", ""),
                }
                context["markets"].append(market_data)

                # Arbitrage scanner
                if len(prices) == 2 and len(token_ids) == 2:
                    try:
                        p_yes = float(prices[0])
                        p_no = float(prices[1])
                        total = p_yes + p_no
                        if total < 0.99:
                            spread_pct = round((1.0 - total) * 100, 2)
                            context["arbitrage_opportunities"].append({
                                "question": m.get("question", ""),
                                "yes_price": p_yes, "no_price": p_no,
                                "total_cost": round(total, 4),
                                "profit_per_pair": round(1.0 - total, 4),
                                "profit_pct": spread_pct,
                                "yes_token_id": token_ids[0],
                                "no_token_id": token_ids[1],
                            })
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")

        context["arbitrage_opportunities"].sort(
            key=lambda x: x.get("profit_pct", 0), reverse=True
        )

        # Strategy engine
        if self.strategy_engine:
            try:
                raw_for_strategies = self.agent.gamma.get_markets(querystring_params={
                    "active": True, "closed": False,
                    "limit": 200, "order": "volume", "ascending": False,
                })
                strategy_results = self.strategy_engine.run_all_strategies(raw_for_strategies)
                context["strategy_signals"] = {
                    "latency_arbitrage": strategy_results.get("latency_arbitrage", [])[:5],
                    "parity_arbitrage": strategy_results.get("parity_arbitrage", [])[:5],
                    "no_bias": strategy_results.get("no_bias", [])[:5],
                    "high_probability": strategy_results.get("high_probability", [])[:5],
                    "longshots": strategy_results.get("longshots", [])[:3],
                    "total_opportunities": strategy_results.get("total_opportunities", 0),
                }
                context["crypto_prices"] = strategy_results.get("crypto_prices", {})
            except Exception as e:
                logger.error(f"Strategy engine error: {e}")

        # Open orders
        try:
            if self.agent.polymarket:
                orders = self.agent.polymarket.get_open_orders()
                for o in orders:
                    context["open_orders"].append({
                        "id": o.get("id", ""), "side": o.get("side", ""),
                        "price": o.get("price", ""), "size": o.get("original_size", ""),
                        "filled": o.get("size_matched", ""), "outcome": o.get("outcome", ""),
                    })
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")

        return context

    async def _gather_context(self) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._gather_context_sync)

    # ─── LLM Analysis ───

    def _ask_llm_for_trades_sync(self, context: dict, extra_instructions: str = "") -> dict:
        """Send context to LLM for trade recommendations."""
        context_str = json.dumps(context, indent=2, default=str)

        # Calculate bet tier for LLM context
        max_bet, tier_label = self._get_bet_tier(self._cached_balance)

        user_msg = (
            f"Estado atual do Polymarket. Analise e recomende trades.\n\n"
            f"ESTADO ATUAL:\n{context_str}\n\n"
            f"RESTRIÇÕES:\n"
            f"- Saldo USDC disponível: ${self._cached_balance:.2f} ({tier_label})\n"
            f"- Valor máximo por trade: ${max_bet:.2f} (ajustado pelo saldo)\n"
            f"- Máximo de trades neste ciclo: {self.max_trades_per_cycle}\n"
            f"- Use APENAS token IDs dos mercados listados acima\n"
            f"- Verifique posições existentes antes de recomendar\n"
            f"- IMPORTANTE: ajuste amounts para o saldo disponível!\n"
        )

        if extra_instructions:
            user_msg += f"\nINSTRUÇÕES EXTRAS:\n{extra_instructions}\n"

        user_msg += "\nQuais trades devo fazer agora? SEJA ATIVO - prefira trades a inatividade."

        messages = [
            SystemMessage(content=AUTO_TRADER_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ]

        result = self.llm.invoke(messages)
        content = result.content.strip()

        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines).strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse LLM response: {content[:500]}")
            return {"analysis": content, "trades": [], "portfolio_notes": "Erro de parse"}

    async def _ask_llm_for_trades(self, context: dict, extra_instructions: str = "") -> dict:
        loop = asyncio.get_event_loop()
        fn = functools.partial(self._ask_llm_for_trades_sync, context, extra_instructions)
        return await loop.run_in_executor(None, fn)

    # ─── FAST CYCLE ───

    async def run_fast_cycle(self) -> str:
        """Fast cycle (30s): position mgmt + auto-trades only. No LLM."""
        self.fast_cycle_count += 1
        cycle_start = time.time()
        auto_trades = []
        exits = []

        # 0. Update cached balance for bet sizing
        try:
            loop = asyncio.get_event_loop()
            self._cached_balance = await loop.run_in_executor(None, self._get_usdc_balance_sync)
        except Exception:
            pass  # keep last known balance

        # 1. Manage positions (stop-loss, take-profit, trailing stop)
        try:
            exit_trades = await self._manage_positions()
            for trade in exit_trades:
                result = await self._execute_trade(trade)
                exits.append({"trade": trade, "result": result})
        except Exception as e:
            logger.error(f"Position management error: {e}")

        # 2. Quick strategy scan for obvious trades
        try:
            if self.strategy_engine:
                loop = asyncio.get_event_loop()
                # Quick fetch: only crypto prices + top 50 markets
                raw_markets = await loop.run_in_executor(
                    None,
                    lambda: self.agent.gamma.get_markets(querystring_params={
                        "active": True, "closed": False,
                        "limit": 50, "order": "volume", "ascending": False,
                    })
                )
                strategy_results = await loop.run_in_executor(
                    None,
                    lambda: self.strategy_engine.run_all_strategies(raw_markets)
                )

                quick_context = {
                    "strategy_signals": {
                        "latency_arbitrage": strategy_results.get("latency_arbitrage", [])[:3],
                        "parity_arbitrage": strategy_results.get("parity_arbitrage", [])[:3],
                    },
                    "crypto_prices": strategy_results.get("crypto_prices", {}),
                }

                auto_trades = await self._execute_obvious_trades(quick_context)
        except Exception as e:
            logger.error(f"Fast cycle strategy error: {e}")

        # Record cycle
        duration_ms = int((time.time() - cycle_start) * 1000)
        if self.trade_db:
            self.trade_db.record_cycle(
                cycle_type="FAST",
                trades_executed=len(exits) + len(auto_trades),
                trades_auto=len(auto_trades),
                positions_exited=len(exits),
                duration_ms=duration_ms,
            )

        # Only notify if something happened
        total_actions = len(exits) + len(auto_trades)
        if total_actions > 0:
            now = datetime.now(timezone.utc).strftime("%H:%M")
            lines = [f"⚡ Fast #{self.fast_cycle_count} [{now}] ({duration_ms}ms)"]

            for ex in exits:
                lines.append(f"  🔻 {ex['result']}")
            for at in auto_trades:
                lines.append(f"  🤖 {at['result']}")

            self.auto_trades_count += len(auto_trades)
            msg = "\n".join(lines)
            await self._notify(msg)
            return msg

        return f"⚡ Fast #{self.fast_cycle_count}: nada ({duration_ms}ms)"

    # ─── DEEP CYCLE ───

    async def run_deep_cycle(self) -> str:
        """Deep cycle (5min): full analysis + LLM. Returns summary."""
        self.cycle_count += 1
        cycle_start = time.time()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        await self._notify(f"🔄 Ciclo DEEP #{self.cycle_count} iniciando...")

        # Goal check
        if self.goal_mode:
            portfolio_value = await self._get_portfolio_value()
            if portfolio_value >= self.goal_amount:
                self.running = False
                msg = (
                    f"🎉🎉🎉 META ATINGIDA!\n"
                    f"💰 Portfólio: ${portfolio_value:.2f}\n"
                    f"🎯 Meta: ${self.goal_amount:.2f}\n"
                    f"📊 Ciclos: {self.cycle_count} deep + {self.fast_cycle_count} fast\n"
                    f"📈 Trades: {len(self.trade_history)}"
                )
                await self._notify(msg)
                return msg

        # 1. Position management first
        exit_trades = []
        try:
            exits = await self._manage_positions()
            for trade in exits:
                result = await self._execute_trade(trade)
                exit_trades.append(result)
        except Exception as e:
            logger.error(f"Position mgmt error: {e}")

        # 2. Gather full context
        try:
            context = await self._gather_context()
        except Exception as e:
            msg = f"❌ Erro ao coletar dados: {e}"
            await self._notify(msg)
            return msg

        # 3. Execute obvious trades (no LLM)
        auto_results = []
        try:
            auto_results = await self._execute_obvious_trades(context)
        except Exception as e:
            logger.error(f"Auto-trade error: {e}")

        # 4. Build extra instructions with auto-learning data
        extra = ""

        # Strategy performance report
        if self.trade_db:
            report = self.trade_db.get_strategy_report_for_llm()
            extra += f"\n{report}\n\n"

        # Auto-trades already executed this cycle
        if exit_trades or auto_results:
            extra += "TRADES JÁ EXECUTADOS AUTOMATICAMENTE NESTE CICLO:\n"
            for r in exit_trades:
                extra += f"  🔻 {r}\n"
            for ar in auto_results:
                extra += f"  🤖 {ar['result']}\n"
            extra += "NÃO repita esses trades. Foque em NOVAS oportunidades.\n\n"

        # Strategy signals summary
        signals = context.get("strategy_signals", {})
        if signals.get("total_opportunities", 0) > 0:
            extra += "SINAIS DAS ESTRATÉGIAS:\n"
            for strategy_name, signal_list in signals.items():
                if isinstance(signal_list, list) and signal_list:
                    extra += f"\n--- {strategy_name.upper()} ({len(signal_list)} sinais) ---\n"
                    for s in signal_list[:3]:
                        extra += f"  • {s.get('reasoning', json.dumps(s, default=str)[:200])}\n"
                        if s.get('token_id'):
                            extra += f"    token_id: {s['token_id']}\n"
                        if s.get('confidence'):
                            extra += f"    confidence: {s['confidence']}\n"
            extra += "\n"

        # Goal mode
        if self.goal_mode:
            portfolio_value = await self._get_portfolio_value()
            remaining = self.goal_amount - portfolio_value
            extra += (
                f"MODO META: ${portfolio_value:.2f} / ${self.goal_amount:.2f} "
                f"(falta ${remaining:.2f})\n"
            )

        # 5. Ask LLM
        try:
            recommendations = await self._ask_llm_for_trades(context, extra)
        except Exception as e:
            msg = f"❌ Erro LLM: {e}"
            await self._notify(msg)
            return msg

        analysis = recommendations.get("analysis", "Sem análise")
        llm_trades = recommendations.get("trades", [])
        portfolio_notes = recommendations.get("portfolio_notes", "")

        # 6. Execute LLM trades
        llm_results = []
        for trade in llm_trades[:self.max_trades_per_cycle]:
            if self.goal_mode:
                trade["amount"] = min(self.goal_start_amount, self.max_trade_amount)
            result = await self._execute_trade(trade)
            llm_results.append(result)
            self.llm_trades_count += 1

        # 7. Record cycle
        duration_ms = int((time.time() - cycle_start) * 1000)
        total_trades = len(exit_trades) + len(auto_results) + len(llm_results)
        if self.trade_db:
            self.trade_db.record_cycle(
                cycle_type="DEEP",
                signals_found=signals.get("total_opportunities", 0),
                trades_executed=total_trades,
                trades_auto=len(auto_results),
                trades_llm=len(llm_results),
                positions_exited=len(exit_trades),
                duration_ms=duration_ms,
            )

        # 8. Build summary
        mode_label = "SIM" if self.dry_run else "LIVE"
        crypto_prices = context.get("crypto_prices", {})

        lines = [
            f"📊 Deep #{self.cycle_count} [{mode_label}] ({duration_ms/1000:.1f}s)",
            f"⏰ {now}",
        ]

        # Crypto prices
        if crypto_prices:
            parts = []
            for symbol, data in crypto_prices.items():
                price = data.get("price", 0)
                change_1m = data.get("change_1m", 0)
                arrow = "🟢" if change_1m > 0 else "🔴" if change_1m < 0 else "⚪"
                parts.append(f"{arrow}{symbol}:${price:,.0f}({change_1m:+.2f}%)")
            lines.append(f"💹 {' '.join(parts)}")

        # Strategy signals
        if signals.get("total_opportunities", 0) > 0:
            sig_parts = []
            for name in ["latency_arbitrage", "parity_arbitrage", "no_bias", "high_probability", "longshots"]:
                count = len(signals.get(name, []))
                if count > 0:
                    emoji = {"latency_arbitrage": "⚡", "parity_arbitrage": "♻️", "no_bias": "🚫", "high_probability": "🎯", "longshots": "🎰"}.get(name, "📌")
                    sig_parts.append(f"{emoji}{count}")
            lines.append(f"🔍 {' '.join(sig_parts)} ({signals['total_opportunities']} total)")

        # Auto-learning stats
        if self.trade_db:
            stats = self.trade_db.get_portfolio_stats()
            if stats["total_trades"] > 0:
                lines.append(f"🧠 WR:{stats['win_rate']*100:.0f}% PnL:${stats['total_pnl']:+.2f} ({stats['total_trades']}T)")

        lines.append(f"\n📈 {analysis}")

        # Exits
        if exit_trades:
            lines.append(f"\n🔻 Exits ({len(exit_trades)}):")
            for r in exit_trades:
                lines.append(f"  {r}")

        # Auto-trades
        if auto_results:
            lines.append(f"\n🤖 Auto ({len(auto_results)}):")
            for ar in auto_results:
                lines.append(f"  {ar['result']}")

        # LLM trades
        if llm_results:
            lines.append(f"\n🎯 LLM ({len(llm_results)}):")
            for i, r in enumerate(llm_results, 1):
                lines.append(f"  #{i}: {r}")
        elif not exit_trades and not auto_results:
            lines.append("\n✋ Nenhum trade neste ciclo.")

        if portfolio_notes:
            lines.append(f"\n💼 {portfolio_notes}")

        summary = "\n".join(lines)
        await self._notify(summary)
        return summary

    # ─── Combined Cycle ───

    async def run_cycle(self) -> str:
        """Run a single cycle (backward compatible). Runs DEEP cycle."""
        return await self.run_deep_cycle()

    # ─── Main Loop ───

    async def _loop(self):
        """Dual-speed trading loop: fast every 30s, deep every N fast cycles."""
        try:
            # First cycle is always deep
            logger.info("Auto-trader starting first DEEP cycle...")
            await self.run_deep_cycle()

            fast_count = 0
            while self.running:
                await asyncio.sleep(self.fast_interval_sec)
                if not self.running:
                    break

                fast_count += 1

                if fast_count >= self.deep_interval_cycles:
                    # Deep cycle
                    fast_count = 0
                    await self.run_deep_cycle()
                else:
                    # Fast cycle
                    await self.run_fast_cycle()

        except asyncio.CancelledError:
            logger.info("Auto-trader loop cancelled.")
        except Exception as e:
            logger.error(f"Auto-trader loop error: {e}")
            logger.error(traceback.format_exc())
            await self._notify(f"❌ Auto-trader crashou: {e}")
            self.running = False

    # ─── Control ───

    async def start(self):
        """Start the auto-trading loop."""
        if self.running:
            return "Auto-trader já está rodando."

        self.running = True
        self._task = asyncio.create_task(self._loop())

        mode = "SIM" if self.dry_run else "LIVE"
        deep_sec = self.fast_interval_sec * self.deep_interval_cycles

        msg_lines = [
            f"🤖 Auto-trader v2 INICIADO [{mode}]",
            f"  ⚡ Fast: a cada {self.fast_interval_sec}s (posições + arbs)",
            f"  🔄 Deep: a cada {deep_sec}s (LLM + todas estratégias)",
            f"  💰 Max/trade: ${self.max_trade_amount}",
            f"  📊 Max trades/ciclo: {self.max_trades_per_cycle}",
            f"  📉 Stop-loss: -{self.position_manager.stop_loss_pct}%",
            f"  📈 Take-profit: +{self.position_manager.take_profit_pct}%",
        ]

        if self.goal_mode:
            msg_lines.extend([
                f"", f"🎯 META: ${self.goal_amount:.2f}",
                f"  Trade: ${self.goal_start_amount:.2f}",
            ])

        msg_lines.append(f"\nUse /stop_autotrade para parar.")
        msg = "\n".join(msg_lines)
        await self._notify(msg)
        return msg

    async def start_with_goal(self, start_amount: float, goal_amount: float,
                               interval_min: int = 1, dry_run: bool = False):
        """Start goal-based auto-trading."""
        self.goal_mode = True
        self.goal_amount = goal_amount
        self.goal_start_amount = start_amount
        self.max_trade_amount = start_amount
        self.max_trades_per_cycle = 5
        self.dry_run = dry_run

        portfolio_value = await self._get_portfolio_value()
        if portfolio_value >= goal_amount:
            return (
                f"🎯 Meta já atingida!\n"
                f"Portfólio: ${portfolio_value:.2f} >= Meta: ${goal_amount:.2f}"
            )

        return await self.start()

    async def stop(self):
        """Stop the auto-trading loop."""
        if not self.running:
            return "Auto-trader não está rodando."

        self.running = False
        self.goal_mode = False
        if self._task:
            self._task.cancel()
            self._task = None

        stats = ""
        if self.trade_db:
            s = self.trade_db.get_portfolio_stats()
            stats = (
                f"\n📊 Sessão: {s['total_trades']}T, WR:{s['win_rate']*100:.0f}%, "
                f"PnL:${s['total_pnl']:+.2f}"
            )

        msg = (
            f"🛑 Auto-trader PARADO\n"
            f"  Deep: {self.cycle_count} | Fast: {self.fast_cycle_count}\n"
            f"  Auto: {self.auto_trades_count} | LLM: {self.llm_trades_count}"
            f"{stats}"
        )
        await self._notify(msg)
        return msg

    async def get_status(self) -> str:
        """Return current auto-trader status."""
        mode = "SIM" if self.dry_run else "LIVE"
        status = "RODANDO" if self.running else "PARADO"
        deep_sec = self.fast_interval_sec * self.deep_interval_cycles

        # Bet tier info
        max_bet, tier_label = self._get_bet_tier(self._cached_balance)

        lines = [
            f"🤖 Auto-Trader v2: {status} [{mode}]",
            f"  💰 Saldo: ${self._cached_balance:.2f} → {tier_label} (max ${max_bet:.2f}/trade)",
            f"  ⚡ Fast: {self.fast_interval_sec}s | 🔄 Deep: {deep_sec}s",
            f"  📉 SL: -{self.position_manager.stop_loss_pct}% | 📈 TP: +{self.position_manager.take_profit_pct}%",
            f"  Ciclos: {self.cycle_count} deep + {self.fast_cycle_count} fast",
            f"  Trades: {self.auto_trades_count} auto + {self.llm_trades_count} LLM",
        ]

        if self.goal_mode:
            portfolio_value = await self._get_portfolio_value()
            progress = (portfolio_value / self.goal_amount) * 100 if self.goal_amount else 0
            lines.extend([
                f"", f"🎯 META: ${portfolio_value:.2f} / ${self.goal_amount:.2f} ({progress:.1f}%)",
            ])

        # DB stats
        if self.trade_db:
            stats = self.trade_db.get_portfolio_stats()
            if stats["total_trades"] > 0:
                lines.extend([
                    f"",
                    f"📊 PERFORMANCE:",
                    f"  WR: {stats['win_rate']*100:.1f}% ({stats['wins']}W/{stats['losses']}L)",
                    f"  PnL: ${stats['total_pnl']:+.4f}",
                    f"  Sharpe: {stats['sharpe_ratio']:.3f}",
                    f"  MaxDD: ${stats['max_drawdown']:.4f}",
                    f"  Volume: ${stats['total_volume']:.2f}",
                    f"  Hoje: {stats['today_trades']}T / {stats['today_cycles']} ciclos",
                ])

        if self.trade_history:
            lines.append(f"\n📜 Últimos 5:")
            for t in self.trade_history[-5:]:
                lines.append(
                    f"  {t['time'][11:16]} {t['action']} ${t['amount']:.2f} "
                    f"[{t.get('strategy', '?')}] {t['result'][:40]}"
                )

        return "\n".join(lines)

    def set_dry_run(self, enabled: bool):
        self.dry_run = enabled
        return f"Modo: {'SIM' if enabled else 'LIVE'}"

    def set_speed(self, mode: str):
        """Set speed mode: 'fast' (30s cycles) or 'normal' (5min deep)."""
        if mode == "fast":
            self.fast_interval_sec = 30
            self.deep_interval_cycles = 10
            self.speed_mode = "fast"
            return "⚡ Modo FAST: ciclo a cada 30s, deep a cada 5min"
        else:
            self.fast_interval_sec = 300
            self.deep_interval_cycles = 1
            self.speed_mode = "normal"
            return "🔄 Modo NORMAL: deep a cada 5min"

    def set_stop_loss(self, pct: float):
        """Set stop-loss percentage."""
        self.position_manager.stop_loss_pct = pct
        return f"📉 Stop-loss: -{pct}%"

    def set_take_profit(self, pct: float):
        """Set take-profit percentage."""
        self.position_manager.take_profit_pct = pct
        return f"📈 Take-profit: +{pct}%"
