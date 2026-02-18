"""
Auto Trader Module

Two modes:
  1. Continuous auto-trading: periodically queries xAI for trade recommendations
  2. Goal-based trading: trade with $X per trade until portfolio reaches $Y target

Flow:
  1. Fetch current positions, balance, and trending markets
  2. Send all context to xAI asking for trade recommendations
  3. xAI returns structured JSON with trades to execute
  4. Execute each trade and report results via Telegram
  5. (Goal mode) Check if target reached, stop if yes
"""

import os
import sys
import json
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


AUTO_TRADER_SYSTEM_PROMPT = """Você é um trader expert e agressivo do Polymarket. Seu objetivo é MAXIMIZAR lucros.

Você vai receber:
- Saldo USDC atual
- Posições abertas com P&L
- Mercados trending/ativos com preços, token IDs e outcomes
- Sinais das 6 estratégias automáticas (já pré-analisados pelo scanner)
- Ordens abertas

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
- Bom para crescer saldo de forma estável

### 5. LONG SHOTS (1-5 centavos)
- Compre outcomes baratos (1-5 centavos) com upside assimétrico
- Se acertar 1 em 20, ainda é lucrativo (20x-100x retorno)
- NUNCA mais que $1-2 por long shot
- Sinais "LONGSHOT" identificados

### 6. GESTÃO DE PORTFÓLIO
- Venda posições perdedoras RÁPIDO (stop loss mental de -30%)
- Deixe vencedoras correr
- Diversifique entre 3-5 temas diferentes

REGRAS:
- PRIORIZE: Latency Arb > Parity Arb > NO Bias > High Prob > Longshot
- Para sinais com confidence > 0.8, SEMPRE execute
- Para vendas, só venda posições que já existem
- Use USDC values inteiros ($1, $2, $5) para amount
- NUNCA gaste mais que 40% do saldo em um único trade (exceto arbitragem risk-free)
- Para LONGSHOTS, use no máximo $1-2

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


class AutoTrader:
    """
    Autonomous trader that uses xAI to decide and execute trades on Polymarket.
    Supports continuous mode and goal-based mode.

    Uses 6 strategies based on top Polymarket bot analysis:
    1. Temporal/Latency Arbitrage (crypto 15-min markets)
    2. Parity Arbitrage (YES + NO < $1)
    3. Systematic NO Bias (70% resolve NO)
    4. High-Probability Auto-Compounding
    5. Long-Shot Floor Buying
    6. Portfolio Management
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
                logger.info("Strategy engine initialized with 6 strategies")
            except ImportError:
                self.strategy_engine = None
                logger.warning("Strategy engine not available - using LLM-only mode")

        # Config - faster cycles for latency arb
        self.interval_minutes = int(os.getenv("AUTOTRADE_INTERVAL_MIN", "10"))
        self.max_trade_amount = float(os.getenv("AUTOTRADE_MAX_AMOUNT", "25"))
        self.max_trades_per_cycle = int(os.getenv("AUTOTRADE_MAX_TRADES", "5"))
        self.dry_run = os.getenv("AUTOTRADE_DRY_RUN", "true").lower() == "true"

        # Goal-based trading
        self.goal_mode = False
        self.goal_amount = 0.0
        self.goal_start_amount = 0.0  # per-trade amount in goal mode

        # Telegram callback for notifications
        self._notify_callback = None

        # Trade history
        self.trade_history = []
        self.cycle_count = 0

        logger.info(
            f"AutoTrader initialized: interval={self.interval_minutes}min, "
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

    def _get_portfolio_value_sync(self) -> float:
        """Get total portfolio value (USDC balance + open positions value). Synchronous."""
        total = 0.0

        # USDC balance on-chain
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

        # Note: Polymarket uses proxy wallets, so on-chain USDC balance
        # of the proxy wallet IS the trading balance. No separate CLOB balance needed.

        # Position values
        try:
            import httpx
            wallet = self.agent.wallet_address
            if wallet:
                res = httpx.get(
                    "https://data-api.polymarket.com/positions",
                    params={
                        "user": wallet,
                        "sizeThreshold": 0,
                        "limit": 100,
                        "sortBy": "CURRENT",
                        "sortDirection": "DESC",
                    },
                )
                if res.status_code == 200:
                    for p in res.json():
                        total += float(p.get("currentValue", 0))
        except Exception as e:
            logger.error(f"Error getting positions: {e}")

        return total

    async def _get_portfolio_value(self) -> float:
        """Async wrapper - runs blocking I/O in executor to not block event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_portfolio_value_sync)

    def _gather_context_sync(self) -> dict:
        """Gather current market state and run strategy engine for the LLM to analyze."""
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
                    params={
                        "user": wallet,
                        "sizeThreshold": 0,
                        "limit": 50,
                        "sortBy": "CURRENT",
                        "sortDirection": "DESC",
                    },
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

        # Markets (top 50 by volume for best liquidity)
        try:
            raw_markets = self.agent.gamma.get_markets(querystring_params={
                "active": True,
                "closed": False,
                "limit": 50,
                "order": "volume",
                "ascending": False,
            })
            for m in raw_markets:
                token_ids = m.get("clobTokenIds", "")
                if isinstance(token_ids, str):
                    try:
                        token_ids = json.loads(token_ids)
                    except (json.JSONDecodeError, TypeError):
                        token_ids = []

                outcomes = m.get("outcomes", "")
                if isinstance(outcomes, str):
                    try:
                        outcomes = json.loads(outcomes)
                    except (json.JSONDecodeError, TypeError):
                        outcomes = []

                prices = m.get("outcomePrices", "")
                if isinstance(prices, str):
                    try:
                        prices = json.loads(prices)
                    except (json.JSONDecodeError, TypeError):
                        prices = []

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

                # Arbitrage scanner: check if YES + NO < $1.00
                if len(prices) == 2 and len(token_ids) == 2:
                    try:
                        p_yes = float(prices[0])
                        p_no = float(prices[1])
                        total = p_yes + p_no
                        if total < 0.99:  # At least 1% profit margin
                            spread_pct = round((1.0 - total) * 100, 2)
                            context["arbitrage_opportunities"].append({
                                "question": m.get("question", ""),
                                "yes_price": p_yes,
                                "no_price": p_no,
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

        # Sort arbitrage by profit %
        context["arbitrage_opportunities"].sort(
            key=lambda x: x.get("profit_pct", 0), reverse=True
        )

        if context["arbitrage_opportunities"]:
            logger.info(f"Found {len(context['arbitrage_opportunities'])} arbitrage opportunities!")

        # Run strategy engine on all fetched markets (raw_markets from Gamma API)
        if self.strategy_engine:
            try:
                raw_for_strategies = self.agent.gamma.get_markets(querystring_params={
                    "active": True,
                    "closed": False,
                    "limit": 100,
                    "order": "volume",
                    "ascending": False,
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
                logger.info(f"Strategy engine found {strategy_results.get('total_opportunities', 0)} total opportunities")
            except Exception as e:
                logger.error(f"Strategy engine error: {e}")

        # Open orders
        try:
            if self.agent.polymarket:
                orders = self.agent.polymarket.get_open_orders()
                for o in orders:
                    context["open_orders"].append({
                        "id": o.get("id", ""),
                        "side": o.get("side", ""),
                        "price": o.get("price", ""),
                        "size": o.get("original_size", ""),
                        "filled": o.get("size_matched", ""),
                        "outcome": o.get("outcome", ""),
                    })
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")

        return context

    async def _gather_context(self) -> dict:
        """Async wrapper for _gather_context_sync."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._gather_context_sync)

    def _ask_llm_for_trades_sync(self, context: dict, extra_instructions: str = "") -> dict:
        """Send context to xAI and get trade recommendations."""
        context_str = json.dumps(context, indent=2, default=str)

        user_msg = (
            f"Estado atual do Polymarket. Analise e recomende trades.\n\n"
            f"ESTADO ATUAL:\n{context_str}\n\n"
            f"RESTRIÇÕES:\n"
            f"- Valor máximo por trade: ${self.max_trade_amount}\n"
            f"- Máximo de trades neste ciclo: {self.max_trades_per_cycle}\n"
            f"- Use APENAS token IDs dos mercados listados acima\n"
            f"- Verifique posições existentes antes de recomendar\n"
        )

        if extra_instructions:
            user_msg += f"\nINSTRUÇÕES EXTRAS:\n{extra_instructions}\n"

        user_msg += "\nQuais trades devo fazer agora?"

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
        """Async wrapper for _ask_llm_for_trades_sync."""
        loop = asyncio.get_event_loop()
        fn = functools.partial(self._ask_llm_for_trades_sync, context, extra_instructions)
        return await loop.run_in_executor(None, fn)

    async def _execute_trade(self, trade: dict) -> str:
        """Execute a single trade.

        amount = valor em USDC que queremos gastar
        price = preço por share (ex: 0.05)
        size (para o CLOB) = amount / price = número de shares

        Exemplo: gastar $5 a price 0.05 → size = 5/0.05 = 100 shares
        """
        action = trade.get("action", "").upper()
        token_id = trade.get("token_id", "")
        amount = float(trade.get("amount", 0))  # USDC to spend
        price = float(trade.get("price", 0))
        market_q = trade.get("market_question", "")
        reasoning = trade.get("reasoning", "")

        if not all([token_id, amount, price, action in ("BUY", "SELL")]):
            return f"❌ Parâmetros inválidos: {trade}"

        if amount > self.max_trade_amount:
            amount = self.max_trade_amount

        # Convert USDC amount to number of shares
        # size = amount_usdc / price_per_share
        size = round(amount / price, 2)

        # Polymarket minimum size is 5 shares
        if size < 5:
            size = 5

        if self.dry_run:
            result_msg = (
                f"[SIMULAÇÃO] {action} ${amount:.2f} ({size:.0f} shares) em '{market_q}' a {price}\n"
                f"  Token: {token_id[:30]}...\n"
                f"  Razão: {reasoning}"
            )
            self.trade_history.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "token_id": token_id,
                "amount": amount,
                "price": price,
                "size": size,
                "market": market_q,
                "result": "SIMULAÇÃO",
            })
            return result_msg

        # Real execution - use aggressive orders that cross the spread for instant fill
        try:
            if not self.agent.polymarket:
                return "❌ Não é possível executar: wallet não conectada."

            logger.info(f"Executing AGGRESSIVE: {action} ${amount:.2f} USDC on '{market_q[:40]}'")

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.agent.polymarket.execute_aggressive_order(
                    token_id=token_id,
                    side=action,
                    amount=amount if action == "BUY" else size,
                )
            )

            self.trade_history.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "token_id": token_id,
                "amount": amount,
                "price": price,
                "size": size,
                "market": market_q,
                "result": str(result),
            })

            return (
                f"✅ EXECUTADO {action}: ${amount:.2f} ({size:.0f} shares) em '{market_q}' a {price}\n"
                f"  Token: {token_id[:30]}...\n"
                f"  Razão: {reasoning}\n"
                f"  Resultado: {result}"
            )
        except Exception as e:
            error_msg = f"❌ FALHOU {action}: ${amount:.2f} ({size:.0f} shares) a {price} - {e}"
            self.trade_history.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "token_id": token_id,
                "amount": amount,
                "price": price,
                "size": size,
                "market": market_q,
                "result": f"ERRO: {e}",
            })
            return error_msg

    async def run_cycle(self) -> str:
        """Run a single auto-trade cycle."""
        self.cycle_count += 1
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        await self._notify(f"🔄 Ciclo #{self.cycle_count} iniciando às {now}...")

        # Check goal if in goal mode
        if self.goal_mode:
            portfolio_value = await self._get_portfolio_value()
            if portfolio_value >= self.goal_amount:
                self.running = False
                msg = (
                    f"🎉🎉🎉 META ATINGIDA! 🎉🎉🎉\n\n"
                    f"💰 Valor do portfólio: ${portfolio_value:.2f}\n"
                    f"🎯 Meta: ${self.goal_amount:.2f}\n"
                    f"📊 Ciclos: {self.cycle_count}\n"
                    f"📈 Trades realizados: {len(self.trade_history)}\n\n"
                    f"Auto-trader parado automaticamente."
                )
                await self._notify(msg)
                return msg

        # Gather context + strategy signals
        try:
            logger.info("Gathering market context + running strategy engine...")
            context = await self._gather_context()
            signals = context.get("strategy_signals", {})
            total_signals = signals.get("total_opportunities", 0)
            logger.info(
                f"Context: {len(context.get('markets', []))} markets, "
                f"{len(context.get('positions', []))} positions, "
                f"{total_signals} strategy signals"
            )
        except Exception as e:
            logger.error(f"Error gathering context: {e}")
            logger.error(traceback.format_exc())
            msg = f"❌ Erro ao coletar dados: {e}"
            await self._notify(msg)
            return msg

        # Extra instructions for goal mode + strategy summary
        extra = ""

        # Summarize strategy signals for the LLM
        signals = context.get("strategy_signals", {})
        if signals.get("total_opportunities", 0) > 0:
            extra += "SINAIS DAS ESTRATÉGIAS AUTOMÁTICAS:\n"
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

        if self.goal_mode:
            portfolio_value = await self._get_portfolio_value()
            remaining = self.goal_amount - portfolio_value
            extra += (
                f"MODO META ATIVA:\n"
                f"- Valor atual do portfólio: ${portfolio_value:.2f}\n"
                f"- Meta: ${self.goal_amount:.2f}\n"
                f"- Falta: ${remaining:.2f}\n"
                f"- Valor por trade: ${self.goal_start_amount:.2f}\n"
                f"- Seja AGRESSIVO mas INTELIGENTE para atingir a meta!\n"
                f"- Prefira trades com alto potencial de retorno\n"
            )

        # Ask LLM
        try:
            logger.info("Asking LLM for trade recommendations...")
            recommendations = await self._ask_llm_for_trades(context, extra)
            logger.info(f"LLM response: {len(recommendations.get('trades', []))} trades recommended")
        except Exception as e:
            logger.error(f"Error asking LLM: {e}")
            logger.error(traceback.format_exc())
            msg = f"❌ Erro na análise da IA: {e}"
            await self._notify(msg)
            return msg

        analysis = recommendations.get("analysis", "Sem análise")
        trades = recommendations.get("trades", [])
        portfolio_notes = recommendations.get("portfolio_notes", "")

        # Build summary
        mode_label = "SIMULAÇÃO" if self.dry_run else "LIVE"
        if self.goal_mode:
            portfolio_value = await self._get_portfolio_value()
            mode_label += f" | META ${self.goal_amount:.0f}"

        # Crypto prices summary
        crypto_prices = context.get("crypto_prices", {})
        crypto_summary = ""
        if crypto_prices:
            parts = []
            for symbol, data in crypto_prices.items():
                price = data.get("price", 0)
                change_1m = data.get("change_1m", 0)
                arrow = "🟢" if change_1m > 0 else "🔴" if change_1m < 0 else "⚪"
                parts.append(f"{arrow} {symbol}: ${price:,.0f} ({change_1m:+.2f}%/1m)")
            crypto_summary = " | ".join(parts)

        summary_lines = [
            f"📊 Ciclo #{self.cycle_count} [{mode_label}]",
            f"⏰ {now}",
        ]

        if crypto_summary:
            summary_lines.append(f"💹 {crypto_summary}")

        # Strategy signals summary
        strategy_signals = context.get("strategy_signals", {})
        if strategy_signals.get("total_opportunities", 0) > 0:
            signal_parts = []
            for name in ["latency_arbitrage", "parity_arbitrage", "no_bias", "high_probability", "longshots"]:
                count = len(strategy_signals.get(name, []))
                if count > 0:
                    emoji = {"latency_arbitrage": "⚡", "parity_arbitrage": "♻️", "no_bias": "🚫", "high_probability": "🎯", "longshots": "🎰"}.get(name, "📌")
                    signal_parts.append(f"{emoji}{count}")
            summary_lines.append(f"🔍 Sinais: {' '.join(signal_parts)} ({strategy_signals['total_opportunities']} total)")

        if self.goal_mode:
            # portfolio_value already fetched above
            progress = (portfolio_value / self.goal_amount) * 100
            bar_filled = int(progress / 5)
            bar = "█" * bar_filled + "░" * (20 - bar_filled)
            summary_lines.append(
                f"🎯 Progresso: ${portfolio_value:.2f} / ${self.goal_amount:.2f} ({progress:.1f}%)\n"
                f"   [{bar}]"
            )

        summary_lines.extend([
            f"",
            f"📈 Análise: {analysis}",
            f"",
        ])

        if not trades:
            summary_lines.append("✋ Nenhum trade recomendado neste ciclo.")
        else:
            trades = trades[:self.max_trades_per_cycle]
            summary_lines.append(f"🎯 Executando {len(trades)} trade(s):\n")

            for i, trade in enumerate(trades, 1):
                # Override amount in goal mode
                if self.goal_mode:
                    trade["amount"] = min(
                        self.goal_start_amount,
                        self.max_trade_amount,
                    )
                result = await self._execute_trade(trade)
                summary_lines.append(f"  Trade #{i}: {result}\n")

        if portfolio_notes:
            summary_lines.append(f"\n💼 Portfólio: {portfolio_notes}")

        summary = "\n".join(summary_lines)
        await self._notify(summary)
        return summary

    async def start(self):
        """Start the auto-trading loop."""
        if self.running:
            return "Auto-trader já está rodando."

        self.running = True
        self._task = asyncio.create_task(self._loop())

        mode = "SIMULAÇÃO" if self.dry_run else "LIVE"
        msg_lines = [
            f"🤖 Auto-trader INICIADO [{mode}]",
            f"  Intervalo: a cada {self.interval_minutes} minutos",
            f"  Max por trade: ${self.max_trade_amount}",
            f"  Max trades/ciclo: {self.max_trades_per_cycle}",
        ]

        if self.goal_mode:
            msg_lines.extend([
                f"",
                f"🎯 MODO META:",
                f"  Valor por trade: ${self.goal_start_amount:.2f}",
                f"  Meta: ${self.goal_amount:.2f}",
                f"  Para quando atingir a meta!",
            ])

        msg_lines.append(f"\nUse /stop_autotrade para parar.")
        msg = "\n".join(msg_lines)
        await self._notify(msg)
        return msg

    async def start_with_goal(self, start_amount: float, goal_amount: float,
                               interval_min: int = 15, dry_run: bool = False):
        """Start goal-based auto-trading."""
        self.goal_mode = True
        self.goal_amount = goal_amount
        self.goal_start_amount = start_amount
        self.max_trade_amount = start_amount
        self.max_trades_per_cycle = 2
        self.interval_minutes = interval_min
        self.dry_run = dry_run

        portfolio_value = await self._get_portfolio_value()
        if portfolio_value >= goal_amount:
            return (
                f"🎯 Sua meta já foi atingida!\n"
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

        msg = f"🛑 Auto-trader PARADO após {self.cycle_count} ciclo(s)."
        await self._notify(msg)
        return msg

    async def _loop(self):
        """Main trading loop."""
        try:
            logger.info("Auto-trader loop starting first cycle...")
            await self.run_cycle()
            logger.info("Auto-trader first cycle completed.")

            while self.running:
                logger.info(f"Auto-trader sleeping for {self.interval_minutes} minutes...")
                await asyncio.sleep(self.interval_minutes * 60)
                if self.running:
                    logger.info("Auto-trader starting next cycle...")
                    await self.run_cycle()
                    logger.info("Auto-trader cycle completed.")

        except asyncio.CancelledError:
            logger.info("Auto-trader loop cancelled.")
        except Exception as e:
            logger.error(f"Auto-trader loop error: {e}")
            logger.error(traceback.format_exc())
            await self._notify(f"❌ Auto-trader crashou: {e}")
            self.running = False

    async def get_status(self) -> str:
        """Return current auto-trader status."""
        mode = "SIMULAÇÃO" if self.dry_run else "LIVE"
        status = "RODANDO" if self.running else "PARADO"

        lines = [
            f"🤖 Auto-Trader: {status} [{mode}]",
            f"  Intervalo: {self.interval_minutes} min",
            f"  Max por trade: ${self.max_trade_amount}",
            f"  Max trades/ciclo: {self.max_trades_per_cycle}",
            f"  Ciclos: {self.cycle_count}",
            f"  Total trades: {len(self.trade_history)}",
        ]

        if self.goal_mode:
            portfolio_value = await self._get_portfolio_value()
            progress = (portfolio_value / self.goal_amount) * 100 if self.goal_amount else 0
            lines.extend([
                f"",
                f"🎯 MODO META:",
                f"  Portfólio: ${portfolio_value:.2f}",
                f"  Meta: ${self.goal_amount:.2f}",
                f"  Progresso: {progress:.1f}%",
            ])

        if self.trade_history:
            lines.append(f"\n📜 Últimos 5 trades:")
            for t in self.trade_history[-5:]:
                lines.append(
                    f"  {t['time'][:16]} | {t['action']} ${t['amount']:.2f} "
                    f"a {t['price']} | {t['result'][:50]}"
                )

        return "\n".join(lines)

    def set_dry_run(self, enabled: bool):
        self.dry_run = enabled
        mode = "SIMULAÇÃO" if enabled else "LIVE"
        return f"Modo: {mode}"
