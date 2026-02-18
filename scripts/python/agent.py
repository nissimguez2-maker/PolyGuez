"""
Interactive Polymarket Agent

A conversational command agent that lets you operate your Polymarket account
using natural language commands in Portuguese or English.
"""

import os
import sys
import ast
import json
import logging
import traceback

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agents.polymarket.gamma import GammaMarketClient

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """Você é um assistente de trading do Polymarket. Você entende português e inglês.
O usuário vai te mandar comandos por mensagem natural e você deve interpretar a intenção dele e responder com JSON estruturado.

Ferramentas disponíveis:

DADOS DE MERCADO:
- get_markets: Listar mercados ativos. Params: limit (int, default 10), sort_by (str: "spread", "liquidity", "volume")
- get_events: Listar eventos ativos. Params: limit (int, default 10)
- search_markets: Buscar mercados por palavra-chave. Params: query (str)
- market_info: Info detalhada de um mercado. Params: market_id (int)

CONTA:
- get_balance: Ver saldo USDC. Sem params.
- get_positions: Ver posições abertas com P&L. Params: limit (int, default 20)
- get_open_orders: Ver ordens abertas. Sem params.
- get_orderbook: Ver orderbook de um token. Params: token_id (str)
- get_price: Ver preço atual de um token. Params: token_id (str)

TRADING MANUAL:
- buy: Comprar. Params: token_id (str), amount (float), price (float)
- sell: Vender. Params: token_id (str), amount (float), price (float)
- cancel_order: Cancelar ordem. Params: order_id (str)
- cancel_all_orders: Cancelar todas as ordens. Sem params.

TRADING INTELIGENTE (IA decide os trades):
- smart_bet: O usuário quer apostar um valor em um tema/assunto e a IA escolhe o melhor mercado e trade.
  Params: topic (str - o assunto/tema), amount (float - valor em USDC)
  Exemplos de uso:
    "aposta 10 dólares em trump" -> {"tool": "smart_bet", "params": {"topic": "trump", "amount": 10}}
    "bet $5 on AI" -> {"tool": "smart_bet", "params": {"topic": "AI", "amount": 5}}
    "coloca 20 em bitcoin" -> {"tool": "smart_bet", "params": {"topic": "bitcoin", "amount": 20}}
    "faça aposta de 10 dólares em eleições" -> {"tool": "smart_bet", "params": {"topic": "eleições", "amount": 10}}

- auto_goal: O usuário quer que a IA faça trades automáticos com um valor inicial até atingir uma meta.
  Params: start_amount (float - valor por trade), goal_amount (float - meta total), interval_min (int, default 15)
  Exemplos de uso:
    "faça trade com 5 dólares até chegar em 50" -> {"tool": "auto_goal", "params": {"start_amount": 5, "goal_amount": 50}}
    "trade com 10 ate 100 dolares" -> {"tool": "auto_goal", "params": {"start_amount": 10, "goal_amount": 100}}
    "invista 3 dolares e pare quando eu tiver 30" -> {"tool": "auto_goal", "params": {"start_amount": 3, "goal_amount": 30}}

ANÁLISE:
- forecast: Análise de superforecaster. Params: event_title (str), question (str), outcome (str)
- news: Buscar notícias. Params: keywords (str)

OUTROS:
- help: Mostrar comandos. Sem params.

REGRAS DE INTERPRETAÇÃO:
1. O usuário pode falar em português ou inglês, interprete a intenção
2. "aposta", "apostar", "bet", "coloca", "invista" = smart_bet (quando menciona um assunto/tema)
3. "faça trade", "trade até", "até chegar em", "pare em", "meta de" = auto_goal (quando menciona um valor meta)
4. "dólares", "dolares", "reais", "$", "USDC" = valores monetários
5. Quando o usuário não menciona um token_id específico mas menciona um TEMA/ASSUNTO, use smart_bet
6. Quando o usuário menciona uma META de lucro, use auto_goal
7. Sempre responda com JSON válido

Formato de resposta:
{"tool": "tool_name", "params": {"param1": "value1"}}

Para mensagens que não mapeiam a nenhuma ferramenta:
{"tool": "chat", "params": {"message": "sua resposta aqui"}}

NUNCA adicione texto fora do JSON.
"""


def _build_llm():
    """Build the LLM client. Priority: Anthropic (Claude) > xAI (Grok) > OpenAI."""
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    xai_key = os.getenv("XAI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if anthropic_key:
        from langchain_anthropic import ChatAnthropic
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        logger.info(f"Using Anthropic Claude: {model}")
        return ChatAnthropic(
            model=model,
            temperature=0,
            api_key=anthropic_key,
        )
    elif xai_key:
        from langchain_openai import ChatOpenAI
        model = os.getenv("XAI_MODEL", "grok-3-mini")
        logger.info(f"Using xAI Grok: {model}")
        return ChatOpenAI(
            model=model,
            temperature=0,
            api_key=xai_key,
            base_url="https://api.x.ai/v1",
        )
    elif openai_key:
        from langchain_openai import ChatOpenAI
        model = os.getenv("OPENAI_MODEL", "gpt-4-1106-preview")
        logger.info(f"Using OpenAI: {model}")
        return ChatOpenAI(
            model=model,
            temperature=0,
        )
    else:
        raise ValueError(
            "No LLM API key found. Set ANTHROPIC_API_KEY, XAI_API_KEY, or OPENAI_API_KEY in .env"
        )


class PolymarketAgent:
    def __init__(self):
        print("Initializing Polymarket Agent...")

        # LLM is required — will raise if no key
        self.llm = _build_llm()

        # Gamma API (market data) — no auth needed
        self.gamma = GammaMarketClient()

        # Wallet address for read-only ops (positions, balance)
        self.wallet_address = os.getenv("POLYMARKET_WALLET_ADDRESS", "")

        # Polymarket CLOB client — needs wallet private key for trading
        self.polymarket = None
        self.executor = None
        private_key = os.getenv("POLYGON_WALLET_PRIVATE_KEY")
        if private_key:
            # Init Polymarket CLOB
            try:
                from agents.polymarket.polymarket import Polymarket
                self.polymarket = Polymarket()
                if not self.wallet_address:
                    self.wallet_address = self.polymarket.get_address_for_private_key()
                logger.info(f"Wallet connected: {self.wallet_address[:10]}...")
            except Exception as e:
                logger.error(f"Polymarket CLOB init failed: {e}")
                logger.error(traceback.format_exc())

            # Init Executor (optional, may fail)
            try:
                from agents.application.executor import Executor
                self.executor = Executor()
                logger.info("Executor initialized.")
            except Exception as e:
                logger.warning(f"Executor init failed (optional): {e}")
        else:
            if self.wallet_address:
                logger.info(f"Read-only mode: {self.wallet_address[:10]}...")
            else:
                logger.warning("No wallet configured.")

        # News — optional, needs NEWSAPI_API_KEY
        self.news_client = None
        if os.getenv("NEWSAPI_API_KEY"):
            try:
                from agents.connectors.news import News
                self.news_client = News()
            except Exception:
                pass

        # Cache for quick lookups during session
        self._market_cache = {}
        print("Agent ready.\n")

    def parse_command(self, user_input: str) -> dict:
        """Use LLM to parse natural language into a structured command."""
        messages = [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(content=user_input),
        ]
        result = self.llm.invoke(messages)
        content = result.content.strip()

        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines).strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"tool": "chat", "params": {"message": content}}

    def execute(self, command: dict) -> str:
        """Execute a parsed command and return the result string."""
        tool = command.get("tool", "help")
        params = command.get("params", {})

        handler = getattr(self, f"_handle_{tool}", None)
        if handler is None:
            return f"Comando desconhecido: {tool}. Digite 'help' para ver os comandos."
        return handler(params)

    # ---- Tool handlers ----

    def _handle_help(self, params: dict) -> str:
        return """
🤖 POLYMARKET BOT - Comandos

📊 DADOS DE MERCADO
  "mostra os mercados"               - Listar mercados
  "busca mercados sobre IA"          - Buscar por tema
  "info do mercado 12345"            - Detalhes de um mercado

💰 CONTA
  "qual meu saldo"                   - Ver saldo USDC
  "mostra minhas posições"           - Ver posições & P/L
  "mostra minhas ordens"             - Ver ordens abertas

🎯 APOSTAS INTELIGENTES (IA escolhe o trade!)
  "aposta 10 dólares em trump"       - IA busca mercado e aposta
  "coloca 5 em bitcoin"             - IA analisa e executa
  "bet $20 on elections"            - IA picks the best market

🚀 TRADING COM META
  "trade com 5 dólares até 50"      - IA faz trades até meta
  "invista 10 até chegar em 100"    - Trading automático com meta

📈 TRADING MANUAL
  "compra 10 de <token_id> a 0.65"  - Comprar
  "vende 5 de <token_id> a 0.80"   - Vender
  "cancela ordem <id>"              - Cancelar ordem

🔮 ANÁLISE
  "previsão: X vai acontecer?"      - Superforecaster
"""

    def _require_wallet(self) -> str:
        """Return error message if wallet is not connected, else empty string."""
        if self.polymarket is None:
            return "❌ Wallet não conectada. Configure POLYGON_WALLET_PRIVATE_KEY no .env."
        return ""

    def _handle_get_markets(self, params: dict) -> str:
        limit = int(params.get("limit", 10))
        sort_by = params.get("sort_by", "spread")

        try:
            raw_markets = self.gamma.get_current_markets(limit=100)
        except Exception as e:
            return f"Erro ao buscar mercados: {e}"

        if not raw_markets:
            return "Nenhum mercado ativo encontrado."

        if sort_by == "spread":
            raw_markets = sorted(
                raw_markets,
                key=lambda x: float(x.get("spread", 0) or 0),
                reverse=True,
            )
        elif sort_by == "liquidity":
            raw_markets = sorted(
                raw_markets,
                key=lambda x: float(x.get("liquidity", 0) or 0),
                reverse=True,
            )

        raw_markets = raw_markets[:limit]

        lines = []
        for i, m in enumerate(raw_markets, 1):
            question = m.get("question", "?")
            mid = m.get("id", "?")
            spread = m.get("spread", "?")
            outcomes = m.get("outcomes", "?")
            prices = m.get("outcomePrices", "?")
            token_ids = m.get("clobTokenIds", "N/A")
            lines.append(
                f"\n  [{i}] {question}\n"
                f"      ID: {mid} | Spread: {spread}\n"
                f"      Outcomes: {outcomes}\n"
                f"      Prices: {prices}\n"
                f"      Token IDs: {token_ids}"
            )

        return f"Mercados Ativos (top {limit}, por {sort_by}):" + "".join(lines)

    def _handle_get_events(self, params: dict) -> str:
        limit = int(params.get("limit", 10))

        try:
            raw_events = self.gamma.get_current_events(limit=100)
        except Exception as e:
            return f"Erro ao buscar eventos: {e}"

        if not raw_events:
            return "Nenhum evento ativo encontrado."

        raw_events = raw_events[:limit]

        lines = []
        for i, e in enumerate(raw_events, 1):
            title = e.get("title", "?")
            eid = e.get("id", "?")
            markets = e.get("markets", [])
            num_markets = len(markets) if isinstance(markets, list) else 0
            desc = e.get("description", "") or ""
            desc_short = (desc[:120] + "...") if len(desc) > 120 else desc
            lines.append(
                f"\n  [{i}] {title}\n"
                f"      ID: {eid} | Mercados: {num_markets}\n"
                f"      {desc_short}"
            )

        return f"Eventos Ativos (top {limit}):" + "".join(lines)

    def _search_markets_by_topic(self, query: str, limit: int = 20) -> list:
        """Search markets by topic using Gamma client's local keyword filtering."""
        return self.gamma.search_markets(query, limit=limit)

    def _handle_search_markets(self, params: dict) -> str:
        query = params.get("query", "")
        if not query:
            return "Informe uma busca."

        try:
            matched = self._search_markets_by_topic(query, limit=20)
        except Exception as e:
            return f"Erro ao buscar mercados: {e}"

        if not matched:
            return f"Nenhum mercado encontrado para '{query}'."

        lines = []
        for i, m in enumerate(matched[:20], 1):
            question = m.get("question", "?")
            mid = m.get("id", "?")
            spread = m.get("spread", "?")
            prices = m.get("outcomePrices", "?")
            token_ids = m.get("clobTokenIds", "N/A")
            lines.append(
                f"\n  [{i}] {question}\n"
                f"      ID: {mid} | Spread: {spread}\n"
                f"      Prices: {prices}\n"
                f"      Token IDs: {token_ids}"
            )

        return f"Mercados para '{query}' ({len(matched)} encontrados):" + "".join(lines)

    def _handle_market_info(self, params: dict) -> str:
        market_id = params.get("market_id")
        if market_id is None:
            return "Informe o market_id."

        try:
            market_data = self.gamma.get_market(int(market_id))
        except Exception as e:
            return f"Erro ao buscar mercado {market_id}: {e}"

        if not market_data:
            return f"Mercado {market_id} não encontrado."

        question = market_data.get("question", "N/A")
        description = market_data.get("description", "N/A")
        outcomes = market_data.get("outcomes", "N/A")
        prices = market_data.get("outcomePrices", "N/A")
        token_ids = market_data.get("clobTokenIds", "N/A")
        active = market_data.get("active", "N/A")
        volume = market_data.get("volume", "N/A")
        liquidity = market_data.get("liquidity", "N/A")
        end_date = market_data.get("endDate", "N/A")
        neg_risk = market_data.get("negRisk", False)

        return (
            f"\nMercado #{market_id}\n"
            f"  Pergunta:   {question}\n"
            f"  Descrição:  {description[:200]}\n"
            f"  Outcomes:   {outcomes}\n"
            f"  Preços:     {prices}\n"
            f"  Token IDs:  {token_ids}\n"
            f"  Ativo:      {active}\n"
            f"  Volume:     {volume}\n"
            f"  Liquidez:   {liquidity}\n"
            f"  Data fim:   {end_date}\n"
            f"  Neg Risk:   {neg_risk}"
        )

    def _get_usdc_balance(self, address: str) -> float:
        """Get USDC balance for an address on Polygon."""
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
        wallet = Web3.to_checksum_address(address)
        usdc_addr = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
        abi = '[{"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"balanceOf","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]'
        usdc = w3.eth.contract(address=usdc_addr, abi=abi)
        balance_raw = usdc.functions.balanceOf(wallet).call()
        return float(balance_raw / 1e6)

    def _handle_get_balance(self, params: dict) -> str:
        if not self.wallet_address:
            return "Wallet não configurada. Configure POLYMARKET_WALLET_ADDRESS no .env."
        try:
            lines = []
            # Polymarket proxy wallet balance
            proxy_bal = self._get_usdc_balance(self.wallet_address)
            lines.append(f"💰 Saldo Polymarket: ${proxy_bal:.2f} USDC")

            # EOA balance (if different from proxy)
            if self.polymarket:
                try:
                    eoa = self.polymarket.get_address_for_private_key()
                    if eoa.lower() != self.wallet_address.lower():
                        eoa_bal = self._get_usdc_balance(eoa)
                        lines.append(f"💳 Saldo EOA ({eoa[:10]}...): ${eoa_bal:.2f} USDC")
                except Exception:
                    pass

            return "\n".join(lines)
        except Exception as e:
            return f"Erro ao buscar saldo: {e}"

    def _handle_get_positions(self, params: dict) -> str:
        if not self.wallet_address:
            return "Wallet não configurada. Configure POLYMARKET_WALLET_ADDRESS no .env."
        limit = int(params.get("limit", 20))

        try:
            import httpx
            res = httpx.get(
                "https://data-api.polymarket.com/positions",
                params={
                    "user": self.wallet_address,
                    "sizeThreshold": 0,
                    "limit": limit,
                    "sortBy": "CURRENT",
                    "sortDirection": "DESC",
                },
            )
            positions = res.json() if res.status_code == 200 else []
        except Exception as e:
            return f"Erro ao buscar posições: {e}"

        if not positions:
            return "Nenhuma posição aberta."

        lines = []
        total_current = 0.0
        total_pnl = 0.0

        for i, p in enumerate(positions, 1):
            title = p.get("title", "Unknown")
            outcome = p.get("outcome", "?")
            size = float(p.get("size", 0))
            avg_price = float(p.get("avgPrice", 0))
            cur_price = float(p.get("curPrice", 0))
            current_value = float(p.get("currentValue", 0))
            cash_pnl = float(p.get("cashPnl", 0))
            pct_pnl = float(p.get("percentPnl", 0))

            total_current += current_value
            total_pnl += cash_pnl

            pnl_sign = "+" if cash_pnl >= 0 else ""
            lines.append(
                f"\n  [{i}] {title}\n"
                f"      Outcome: {outcome} | Size: {size:.2f}\n"
                f"      Preço médio: ${avg_price:.4f} | Preço atual: ${cur_price:.4f}\n"
                f"      Valor: ${current_value:.2f} | PnL: {pnl_sign}${cash_pnl:.2f} ({pnl_sign}{pct_pnl:.1f}%)"
            )

        pnl_sign = "+" if total_pnl >= 0 else ""
        summary = (
            f"\n\n  TOTAL: Valor ${total_current:.2f} | "
            f"PnL {pnl_sign}${total_pnl:.2f}"
        )

        return f"Posições Abertas ({len(positions)}):" + "".join(lines) + summary

    def _handle_get_open_orders(self, params: dict) -> str:
        err = self._require_wallet()
        if err:
            return err
        try:
            orders = self.polymarket.get_open_orders()
        except Exception as e:
            return f"Erro ao buscar ordens: {e}"

        if not orders:
            return "Nenhuma ordem aberta."

        lines = []
        for i, o in enumerate(orders, 1):
            order_id = o.get("id", "?")
            market = o.get("market", "?")
            side = o.get("side", "?")
            price = o.get("price", "?")
            orig_size = o.get("original_size", "?")
            size_matched = o.get("size_matched", "0")
            status = o.get("status", "?")
            outcome = o.get("outcome", "?")

            lines.append(
                f"\n  [{i}] {outcome} | {side}\n"
                f"      Order ID: {order_id}\n"
                f"      Preço: {price} | Size: {orig_size} | Filled: {size_matched}\n"
                f"      Status: {status} | Market: {market[:20]}..."
            )

        return f"Ordens Abertas ({len(orders)}):" + "".join(lines)

    def _handle_cancel_order(self, params: dict) -> str:
        err = self._require_wallet()
        if err:
            return err
        order_id = params.get("order_id")
        if not order_id:
            return "Informe o order_id."

        try:
            result = self.polymarket.cancel_order(order_id)
            canceled = result.get("canceled", [])
            not_canceled = result.get("not_canceled", {})

            if order_id in canceled:
                return f"✅ Ordem {order_id} cancelada."
            elif order_id in not_canceled:
                return f"❌ Falha ao cancelar {order_id}: {not_canceled[order_id]}"
            else:
                return f"Resultado: {result}"
        except Exception as e:
            return f"Erro ao cancelar ordem: {e}"

    def _handle_cancel_all_orders(self, params: dict) -> str:
        err = self._require_wallet()
        if err:
            return err
        try:
            result = self.polymarket.cancel_all_orders()
            canceled = result.get("canceled", [])
            not_canceled = result.get("not_canceled", {})

            msg = f"✅ {len(canceled)} ordem(ns) cancelada(s)."
            if not_canceled:
                msg += f" ❌ {len(not_canceled)} falhou(aram)."
            return msg
        except Exception as e:
            return f"Erro ao cancelar ordens: {e}"

    def _handle_get_orderbook(self, params: dict) -> str:
        err = self._require_wallet()
        if err:
            return err
        token_id = params.get("token_id")
        if not token_id:
            return "Informe o token_id."

        try:
            ob = self.polymarket.get_orderbook(token_id)
            bids = ob.bids[:5] if ob.bids else []
            asks = ob.asks[:5] if ob.asks else []

            bid_lines = [f"    {b.price} | {b.size}" for b in bids]
            ask_lines = [f"    {a.price} | {a.size}" for a in asks]

            return (
                f"\nOrderbook para {token_id[:20]}...\n"
                f"  BIDS (top 5):\n"
                f"    Preço | Size\n"
                + "\n".join(bid_lines)
                + f"\n\n  ASKS (top 5):\n"
                f"    Preço | Size\n"
                + "\n".join(ask_lines)
            )
        except Exception as e:
            return f"Erro ao buscar orderbook: {e}"

    def _handle_get_price(self, params: dict) -> str:
        err = self._require_wallet()
        if err:
            return err
        token_id = params.get("token_id")
        if not token_id:
            return "Informe o token_id."

        try:
            price = self.polymarket.get_orderbook_price(token_id)
            return f"Preço atual de {token_id[:20]}...: ${price:.4f}"
        except Exception as e:
            return f"Erro ao buscar preço: {e}"

    def _handle_buy(self, params: dict) -> str:
        err = self._require_wallet()
        if err:
            return err
        token_id = params.get("token_id")
        amount = params.get("amount")
        price = params.get("price")

        if not all([token_id, amount, price]):
            return "Compra requer: token_id, amount e price."

        amount = float(amount)
        price = float(price)

        self._pending_order = {
            "side": "BUY",
            "token_id": token_id,
            "amount": amount,
            "price": price,
        }

        return (
            f"⚠️ CONFIRMAR COMPRA:\n"
            f"  Token:  {token_id}\n"
            f"  Valor:  ${amount}\n"
            f"  Preço:  {price}\n\n"
            f"Confirma?"
        )

    def _handle_sell(self, params: dict) -> str:
        err = self._require_wallet()
        if err:
            return err
        token_id = params.get("token_id")
        amount = params.get("amount")
        price = params.get("price")

        if not all([token_id, amount, price]):
            return "Venda requer: token_id, amount e price."

        amount = float(amount)
        price = float(price)

        self._pending_order = {
            "side": "SELL",
            "token_id": token_id,
            "amount": amount,
            "price": price,
        }

        return (
            f"⚠️ CONFIRMAR VENDA:\n"
            f"  Token:  {token_id}\n"
            f"  Valor:  ${amount}\n"
            f"  Preço:  {price}\n\n"
            f"Confirma?"
        )

    def confirm_pending_order(self) -> str:
        """Execute the pending order after user confirmation."""
        if not hasattr(self, "_pending_order") or self._pending_order is None:
            return "Nenhuma ordem pendente."

        order = self._pending_order
        self._pending_order = None

        try:
            result = self.polymarket.execute_order(
                price=order["price"],
                size=order["amount"],
                side=order["side"],
                token_id=order["token_id"],
            )
            return f"✅ Ordem {order['side']} executada. Resultado: {result}"
        except Exception as e:
            return f"❌ Erro ao executar ordem: {e}"

    def cancel_pending_order(self) -> str:
        self._pending_order = None
        return "❌ Ordem cancelada."

    def has_pending_order(self) -> bool:
        return hasattr(self, "_pending_order") and self._pending_order is not None

    # ---- Smart Bet: AI picks the best market ----

    def _handle_smart_bet(self, params: dict) -> str:
        """AI searches for markets matching a topic and recommends the best trade."""
        err = self._require_wallet()
        if err:
            return err

        topic = params.get("topic", "")
        amount = float(params.get("amount", 5))

        if not topic:
            return "Informe o assunto para apostar. Ex: 'aposta 10 em trump'"

        # 1. Use LLM to expand topic into search keywords
        try:
            expand_prompt = (
                f'O usuário quer apostar sobre "{topic}". '
                f'Gere uma lista de 3-5 palavras-chave em INGLÊS para buscar mercados de previsão sobre esse tema. '
                f'Inclua sinônimos e termos relacionados. '
                f'Responda APENAS com as palavras separadas por espaço, sem explicação. '
                f'Exemplo: se o tema é "super bowl", responda: "super bowl NFL football championship"'
            )
            expand_result = self.llm.invoke([
                SystemMessage(content="Você gera palavras-chave de busca. Responda APENAS com palavras separadas por espaço."),
                HumanMessage(content=expand_prompt),
            ])
            expanded_query = expand_result.content.strip()
            # Combine original topic with expanded keywords
            search_query = f"{topic} {expanded_query}"
            logger.info(f"Smart bet search: topic='{topic}' expanded='{expanded_query}'")
        except Exception:
            search_query = topic

        # 2. Search markets matching the topic (local keyword filtering)
        try:
            matched = self._search_markets_by_topic(search_query, limit=30)
        except Exception as e:
            return f"Erro ao buscar mercados: {e}"

        if not matched:
            return f"🔍 Nenhum mercado encontrado para '{topic}'. Tente outro assunto."

        # Build context for LLM
        market_context = []
        for m in matched[:15]:
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

            market_context.append({
                "question": m.get("question", ""),
                "outcomes": outcomes,
                "prices": prices,
                "token_ids": token_ids,
                "volume": m.get("volume", 0),
                "liquidity": m.get("liquidity", 0),
                "spread": m.get("spread", 0),
            })

        # 2. Ask LLM to pick the best trade
        prompt = f"""O usuário quer apostar ${amount:.2f} sobre o tema: "{topic}"

Aqui estão os mercados disponíveis no Polymarket sobre esse tema:
{json.dumps(market_context, indent=2, default=str)}

Escolha O MELHOR mercado e o melhor outcome para apostar.
Considere: liquidez, volume, valor esperado, e sua análise.

Responda com APENAS JSON:
{{
  "market_question": "a pergunta do mercado",
  "outcome": "Yes ou No",
  "token_id": "o token_id do outcome escolhido",
  "price": 0.65,
  "amount": {amount},
  "reasoning": "explicação curta em português de por que essa aposta faz sentido"
}}"""

        try:
            messages = [
                SystemMessage(content="Você é um trader expert do Polymarket. Analise os mercados e escolha a melhor aposta. Responda APENAS com JSON válido."),
                HumanMessage(content=prompt),
            ]
            result = self.llm.invoke(messages)
            content = result.content.strip()

            if content.startswith("```"):
                lines = content.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                content = "\n".join(lines).strip()

            trade = json.loads(content)
        except Exception as e:
            return f"❌ Erro na análise da IA: {e}"

        # 3. Store as pending order for confirmation
        token_id = trade.get("token_id", "")
        price = float(trade.get("price", 0))
        trade_amount = float(trade.get("amount", amount))
        market_q = trade.get("market_question", "")
        outcome = trade.get("outcome", "")
        reasoning = trade.get("reasoning", "")

        if not token_id or not price:
            return f"❌ A IA não conseguiu escolher um trade válido. Tente outro assunto."

        self._pending_order = {
            "side": "BUY",
            "token_id": token_id,
            "amount": trade_amount,
            "price": price,
        }

        return (
            f"🎯 APOSTA INTELIGENTE - '{topic}'\n\n"
            f"📊 Mercado: {market_q}\n"
            f"🎲 Outcome: {outcome}\n"
            f"💰 Valor: ${trade_amount:.2f}\n"
            f"📈 Preço: {price}\n\n"
            f"🧠 Análise: {reasoning}\n\n"
            f"⚠️ Confirma essa aposta?"
        )

    # ---- Auto Goal: trade until reaching a target ----

    def _handle_auto_goal(self, params: dict) -> str:
        """Start goal-based auto-trading. Returns info for telegram_bot to handle."""
        err = self._require_wallet()
        if err:
            return err

        start_amount = float(params.get("start_amount", 5))
        goal_amount = float(params.get("goal_amount", 50))
        interval_min = int(params.get("interval_min", 15))

        if goal_amount <= start_amount:
            return "❌ A meta deve ser maior que o valor por trade."

        # Return a special marker that telegram_bot.py will intercept
        return json.dumps({
            "__auto_goal__": True,
            "start_amount": start_amount,
            "goal_amount": goal_amount,
            "interval_min": interval_min,
        })

    def _handle_forecast(self, params: dict) -> str:
        event_title = params.get("event_title", "")
        question = params.get("question", "")
        outcome = params.get("outcome", "Yes")

        if not question:
            return "Informe uma pergunta para prever."

        try:
            if self.executor:
                result = self.executor.get_superforecast(
                    event_title=event_title or question,
                    market_question=question,
                    outcome=outcome,
                )
            else:
                prompt = (
                    f"Você é um Superforecaster. Analise a seguinte questão "
                    f"e dê uma estimativa de probabilidade.\n\n"
                    f"Evento: {event_title or question}\n"
                    f"Pergunta: {question}\n"
                    f"Outcome: {outcome}\n\n"
                    f"Quebre em fatores, considere base rates e dê "
                    f"uma probabilidade entre 0 e 1."
                )
                messages = [
                    SystemMessage(content="Você é um superforecaster expert."),
                    HumanMessage(content=prompt),
                ]
                result = self.llm.invoke(messages).content
            return f"\n🔮 Análise Superforecaster:\n{result}"
        except Exception as e:
            return f"Erro na previsão: {e}"

    def _handle_news(self, params: dict) -> str:
        if self.news_client is None:
            return "Notícias não disponíveis. Configure NEWSAPI_API_KEY no .env."
        keywords = params.get("keywords", "")
        if not keywords:
            return "Informe palavras-chave para buscar notícias."

        try:
            articles = self.news_client.get_articles_for_cli_keywords(keywords)
            if not articles:
                return f"Nenhuma notícia encontrada para '{keywords}'."

            lines = []
            for i, a in enumerate(articles[:10], 1):
                lines.append(
                    f"\n  [{i}] {a.title}\n"
                    f"      Fonte: {a.source.name if a.source else 'N/A'}\n"
                    f"      {a.description[:120] if a.description else 'Sem descrição'}..."
                )

            return f"Notícias sobre '{keywords}':" + "".join(lines)
        except Exception as e:
            return f"Erro ao buscar notícias: {e}"

    def _handle_chat(self, params: dict) -> str:
        message = params.get("message", "")
        return message


def main():
    print("=" * 60)
    print("  POLYMARKET AGENT")
    print("  Interface interativa para sua conta Polymarket")
    print("  Digite 'help' para comandos, 'quit' para sair")
    print("=" * 60)
    print()

    try:
        agent = PolymarketAgent()
    except Exception as e:
        print(f"Falha ao inicializar agent: {e}")
        sys.exit(1)

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nTchau!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q", "sair"):
            print("Tchau!")
            break

        if user_input.lower() in ("help", "ajuda"):
            print(agent._handle_help({}))
            continue

        if agent.has_pending_order():
            if user_input.lower() in ("yes", "y", "confirm", "sim", "s", "confirma"):
                print(agent.confirm_pending_order())
            else:
                print(agent.cancel_pending_order())
            continue

        try:
            command = agent.parse_command(user_input)
            result = agent.execute(command)
            print(result)
        except Exception as e:
            print(f"Erro: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
