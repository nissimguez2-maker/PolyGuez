"""
Enhanced Executor with Resilience, Risk, and Telemetry Integration
Integrates Blocks A-D into the trading flow
"""

import os
import time
import json
import ast
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from dotenv import load_dotenv

# Import our new modules
from agents.resilience import (
    get_circuit_breaker, 
    get_polymarket_retry, 
    get_gamma_retry, 
    get_openai_retry
)
from agents.llm import llm_call
from agents.telemetry import get_metrics_collector, TradeMetrics, CycleMetrics
from agents.risk import get_risk_manager, PortfolioState, Position, RiskBlockReason

from agents.polymarket.gamma import GammaMarketClient as Gamma
from agents.polymarket.polymarket import Polymarket
from agents.application.prompts import Prompter

load_dotenv()


@dataclass
class ExecutorConfig:
    """Configuration for enhanced executor"""
    enable_retry: bool = True
    enable_circuit_breaker: bool = True
    enable_telemetry: bool = True
    enable_risk: bool = True
    
    @classmethod
    def from_env(cls) -> "ExecutorConfig":
        return cls(
            enable_retry=os.getenv("RESILIENCE_ENABLED", "1") == "1",
            enable_circuit_breaker=os.getenv("RESILIENCE_ENABLED", "1") == "1",
            enable_telemetry=os.getenv("TELEMETRY_ENABLED", "1") == "1",
            enable_risk=os.getenv("RISK_ENABLED", "1") == "1"
        )


class EnhancedExecutor:
    """
    Enhanced executor with:
    - Retry/Backoff for all external calls
    - Circuit breaker protection
    - Risk management gates
    - Model fallback
    - Telemetry collection
    """
    
    def __init__(self, config: Optional[ExecutorConfig] = None):
        self.config = config or ExecutorConfig.from_env()
        self.prompter = Prompter()
        self.gamma = Gamma()
        self.polymarket = Polymarket()
        
        # Initialize resilience components
        if self.config.enable_retry:
            self.polymarket_retry = get_polymarket_retry()
            self.gamma_retry = get_gamma_retry()
            self.openai_retry = get_openai_retry()
        
        if self.config.enable_circuit_breaker:
            self.polymarket_cb = get_circuit_breaker("polymarket")
            self.gamma_cb = get_circuit_breaker("gamma")
            self.openai_cb = get_circuit_breaker("openai")
        
        if self.config.enable_telemetry:
            self.metrics = get_metrics_collector()
        
        if self.config.enable_risk:
            self.risk = get_risk_manager()
    
    def _call_with_resilience(self, func, service: str, *args, **kwargs):
        """Wrap call with retry and circuit breaker"""
        # Get circuit breaker
        if self.config.enable_circuit_breaker:
            cb = {
                "polymarket": self.polymarket_cb,
                "gamma": self.gamma_cb,
                "openai": self.openai_cb
            }.get(service)
            
            if cb and cb.state.value == "open":
                raise Exception(f"Circuit breaker open for {service}")
        
        # Get retry handler
        retry_handler = None
        if self.config.enable_retry:
            retry_handler = {
                "polymarket": self.polymarket_retry,
                "gamma": self.gamma_retry,
                "openai": self.openai_retry
            }.get(service)
        
        # Execute with retry
        try:
            if retry_handler:
                result = retry_handler.execute(func, *args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            # Record success for circuit breaker
            if self.config.enable_circuit_breaker and cb:
                cb._on_success()
            
            return result
            
        except Exception as e:
            # Record failure for circuit breaker
            if self.config.enable_circuit_breaker and cb:
                cb._on_failure()
            raise
    
    def filter_events_with_rag(self, events: List) -> List:
        """Filter events with resilience"""
        start_time = time.time()
        
        try:
            # Use circuit breaker + retry
            prompt = self.prompter.filter_events()
            
            # This would use Chroma RAG - simplified here
            result = self._call_with_resilience(
                self._filter_events_impl, 
                "openai",
                events, 
                prompt
            )
            
            # Record metrics
            if self.config.enable_telemetry:
                latency_ms = (time.time() - start_time) * 1000
                self.metrics.increment("filter_events_latency_ms", int(latency_ms))
                self.metrics.increment("filter_events_success")
            
            return result
            
        except Exception as e:
            if self.config.enable_telemetry:
                self.metrics.increment("filter_events_failed")
            raise
    
    def _filter_events_impl(self, events, prompt):
        """Actual implementation - would use Chroma"""
        # Placeholder - actual implementation uses Chroma
        return events[:10]  # Simplified
    
    def map_filtered_events_to_markets(self, filtered_events) -> List:
        """Map events to markets with resilience"""
        start_time = time.time()
        markets = []
        
        try:
            for e in filtered_events:
                data = json.loads(e[0].json()) if hasattr(e[0], 'json') else e[0]
                market_ids = data.get("metadata", {}).get("markets", "").split(",")
                
                for market_id in market_ids:
                    if not market_id:
                        continue
                    
                    # Fetch with retry/circuit breaker
                    market_data = self._call_with_resilience(
                        self.gamma.get_market,
                        "gamma",
                        market_id
                    )
                    
                    formatted = self.polymarket.map_api_to_market(market_data)
                    markets.append(formatted)
            
            # Record metrics
            if self.config.enable_telemetry:
                latency_ms = (time.time() - start_time) * 1000
                self.metrics.increment("map_markets_latency_ms", int(latency_ms))
                self.metrics.increment("markets_mapped", len(markets))
            
            return markets
            
        except Exception as e:
            if self.config.enable_telemetry:
                self.metrics.increment("map_markets_failed")
            raise
    
    def filter_markets(self, markets) -> List:
        """Filter markets with resilience"""
        start_time = time.time()
        
        try:
            prompt = self.prompter.filter_markets()
            
            # Use circuit breaker + retry
            result = self._call_with_resilience(
                self._filter_markets_impl,
                "openai",
                markets,
                prompt
            )
            
            # Record metrics
            if self.config.enable_telemetry:
                latency_ms = (time.time() - start_time) * 1000
                self.metrics.increment("filter_markets_latency_ms", int(latency_ms))
                self.metrics.increment("markets_filtered", len(result))
            
            return result
            
        except Exception as e:
            if self.config.enable_telemetry:
                self.metrics.increment("filter_markets_failed")
            raise
    
    def _filter_markets_impl(self, markets, prompt):
        """Actual implementation - would use Chroma"""
        return markets[:5]  # Simplified
    
    def source_best_trade(self, market_object) -> str:
        """Source trade with model fallback"""
        start_time = time.time()
        
        try:
            market_document = market_object[0].dict() if hasattr(market_object[0], 'dict') else {}
            market = market_document.get("metadata", {})
            
            outcome_prices = ast.literal_eval(market.get("outcome_prices", "[0, 0]"))
            outcomes = ast.literal_eval(market.get("outcomes", "[]"))
            question = market.get("question", "")
            description = market_document.get("page_content", "")
            
            # Use enhanced LLM call with fallback
            messages = self.prompter.superforecaster(question, description, outcomes)
            
            result = self._call_with_resilience(
                self._llm_call_with_fallback,
                "openai",
                messages
            )
            
            content = result
            
            # Second LLM call for trade sizing
            prompt = self.prompter.one_best_trade(content, outcomes, outcome_prices)
            
            result2 = self._call_with_resilience(
                self._llm_call_with_fallback,
                "openai",
                prompt
            )
            
            # Record metrics
            if self.config.enable_telemetry:
                latency_ms = (time.time() - start_time) * 1000
                self.metrics.increment("source_trade_latency_ms", int(latency_ms))
                self.metrics.increment("source_trade_success")
            
            return result2
            
        except Exception as e:
            if self.config.enable_telemetry:
                self.metrics.increment("source_trade_failed")
            raise
    
    def _llm_call_with_fallback(self, messages):
        """LLM call with model fallback"""
        return llm_call(messages, temperature=0)
    
    def check_risk_before_trade(
        self,
        portfolio: PortfolioState,
        amount: float,
        entry_price: float,
        best_ask: float,
        best_bid: float
    ) -> tuple[bool, Optional[str]]:
        """Risk gate before order submission"""
        if not self.config.enable_risk:
            return True, None
        
        allowed, reason, msg = self.risk.check_trade_allowed(
            portfolio, amount, entry_price, best_ask, best_bid
        )
        
        # Record telemetry
        if self.config.enable_telemetry:
            if not allowed:
                self.metrics.increment("trades_blocked_total", labels={"reason": reason.value if reason else "unknown"})
            else:
                self.metrics.increment("trades_allowed_total")
        
        return allowed, msg
    
    def record_trade_attempt(self, market_id: str, amount: float, status: str, **kwargs):
        """Record trade attempt for telemetry"""
        if not self.config.enable_telemetry:
            return
        
        trade = TradeMetrics(
            market_id=market_id,
            size=amount,
            status=status,
            **kwargs
        )
        self.metrics.record_trade(trade)
    
    def get_metrics_summary(self) -> Dict:
        """Get metrics summary"""
        if not self.config.enable_telemetry:
            return {}
        return self.metrics.get_metrics_summary()


# Backwards compatibility - original Executor interface
class Executor(EnhancedExecutor):
    """Backwards compatible Executor"""
    pass
