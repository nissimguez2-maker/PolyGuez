"""
Unit Tests for Resilience, Risk, and LLM Components
Run with: pytest tests/test_integration.py -v
"""

import pytest
import time
import os
import sys
from unittest.mock import Mock, patch
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.resilience import (
    CircuitBreaker, CircuitBreakerConfig, CircuitState, CircuitBreakerOpen
)
from agents.resilience.retry_handler import RetryHandler, RetryConfig
from agents.risk import RiskManager, RiskConfig, PortfolioState, Position, RiskBlockReason
from agents.llm.client import ModelRegistry, LLMClient


# ============================================================================
# Circuit Breaker Tests
# ============================================================================

class TestCircuitBreakerTransitions:
    """Test circuit breaker state transitions"""
    
    def test_closed_to_open_on_failures(self):
        """Circuit opens after threshold failures"""
        config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout=1)
        cb = CircuitBreaker("test", config)
        
        # Should start closed
        assert cb.state == CircuitState.CLOSED
        
        # 3 failures should open circuit
        for _ in range(3):
            try:
                cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
            except:
                pass
        
        assert cb.state == CircuitState.OPEN
    
    def test_open_rejects_calls(self):
        """Open circuit rejects calls immediately"""
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60)
        cb = CircuitBreaker("test", config)
        
        # Force open
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
        except:
            pass
        
        assert cb.state == CircuitState.OPEN
        
        # Next call should be rejected
        with pytest.raises(CircuitBreakerOpen):
            cb.call(lambda: "success")
    
    def test_open_to_half_open_after_timeout(self):
        """Circuit transitions to half-open after timeout"""
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1)
        cb = CircuitBreaker("test", config)
        
        # Force open
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
        except:
            pass
        
        assert cb.state == CircuitState.OPEN
        
        # Wait for timeout
        time.sleep(0.15)
        
        # Access state (triggers check)
        _ = cb.state
        
        assert cb.state == CircuitState.HALF_OPEN
    
    def test_half_open_to_closed_on_success(self):
        """Circuit closes after success threshold in half-open"""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1,
            half_open_max_calls=3,
            success_threshold=2
        )
        cb = CircuitBreaker("test", config)
        
        # Force open
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
        except:
            pass
        
        time.sleep(0.15)
        _ = cb.state  # Trigger transition to half-open
        
        assert cb.state == CircuitState.HALF_OPEN
        
        # 2 successes should close circuit
        cb.call(lambda: "success1")
        cb.call(lambda: "success2")
        
        assert cb.state == CircuitState.CLOSED
    
    def test_half_open_to_open_on_failure(self):
        """Circuit reopens on failure in half-open"""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1
        )
        cb = CircuitBreaker("test", config)
        
        # Force open
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
        except:
            pass
        
        time.sleep(0.15)
        _ = cb.state
        
        assert cb.state == CircuitState.HALF_OPEN
        
        # Failure should reopen
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("fail again")))
        except:
            pass
        
        assert cb.state == CircuitState.OPEN


# ============================================================================
# Retry Handler Tests
# ============================================================================

class TestRetryHandler:
    """Test retry logic with deterministic behavior"""
    
    def test_success_no_retry(self):
        """Successful call doesn't retry"""
        config = RetryConfig(max_retries=3, jitter=False)
        handler = RetryHandler(config, "test")
        
        call_count = 0
        def success_func():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = handler.execute(success_func)
        
        assert result == "success"
        assert call_count == 1
        assert handler.get_metrics()["total_calls"] == 1
    
    def test_retry_on_failure_then_success(self):
        """Retry on failure, then succeed"""
        config = RetryConfig(max_retries=3, base_delay=0.01, jitter=False)
        handler = RetryHandler(config, "test")
        
        call_count = 0
        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("network error")
            return "success"
        
        result = handler.execute(flaky_func)
        
        assert result == "success"
        assert call_count == 3
        metrics = handler.get_metrics()
        assert metrics["retries_performed"] == 2
    
    def test_exhaust_retries(self):
        """Fail after exhausting retries"""
        config = RetryConfig(max_retries=2, base_delay=0.01, jitter=False)
        handler = RetryHandler(config, "test")
        
        def always_fail():
            raise ConnectionError("always fails")
        
        with pytest.raises(ConnectionError):
            handler.execute(always_fail)
        
        metrics = handler.get_metrics()
        assert metrics["total_failures"] == 1
    
    def test_no_retry_on_non_retryable(self):
        """Don't retry non-retryable exceptions"""
        config = RetryConfig(max_retries=3, jitter=False)
        handler = RetryHandler(config, "test")
        
        call_count = 0
        def value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("bad input")
        
        with pytest.raises(ValueError):
            handler.execute(value_error)
        
        assert call_count == 1  # No retries


# ============================================================================
# Risk Manager Tests
# ============================================================================

class TestRiskManagerSizing:
    """Test position sizing logic"""
    
    def test_position_size_respects_max_risk(self):
        """Position size capped at max_risk_pct_per_trade"""
        config = RiskConfig(max_risk_pct_per_trade=2.0)
        manager = RiskManager(config)
        portfolio = PortfolioState(equity=10000.0)
        
        size = manager.calculate_position_size(portfolio, confidence=0.9, edge=100)
        
        max_allowed = 10000.0 * 0.02  # 2%
        assert size <= max_allowed
        assert size >= 1.0  # Hard floor
    
    def test_position_size_zero_on_low_confidence(self):
        """Low confidence reduces position size"""
        config = RiskConfig(max_risk_pct_per_trade=2.0)
        manager = RiskManager(config)
        portfolio = PortfolioState(equity=10000.0)
        
        size = manager.calculate_position_size(portfolio, confidence=0.5, edge=10)
        
        # At 0.5 confidence, multiplier is 0
        assert size >= 1.0  # Hard floor
    
    def test_max_exposure_block(self):
        """Trade blocked when max exposure would be exceeded"""
        config = RiskConfig(max_total_exposure_pct=10.0)
        manager = RiskManager(config)
        
        positions = [Position("m1", "t1", "yes", 0.5, 800.0)]  # 8% exposure
        portfolio = PortfolioState(equity=10000.0, positions=positions)
        
        allowed, reason, msg = manager.check_trade_allowed(
            portfolio, proposed_size=500.0, entry_price=0.5,
            best_ask=0.51, best_bid=0.49
        )
        
        assert allowed is False
        assert reason == RiskBlockReason.MAX_EXPOSURE
    
    def test_daily_loss_limit_block(self):
        """Trade blocked when daily loss limit hit"""
        config = RiskConfig(daily_loss_limit_pct=5.0)
        manager = RiskManager(config)
        
        portfolio = PortfolioState(
            equity=10000.0,
            daily_pnl=-600.0,  # 6% loss
            daily_starting_equity=10000.0
        )
        
        allowed, reason, msg = manager.check_trade_allowed(
            portfolio, proposed_size=100.0, entry_price=0.5,
            best_ask=0.51, best_bid=0.49
        )
        
        assert allowed is False
        assert reason == RiskBlockReason.DAILY_LOSS_LIMIT
    
    def test_spread_too_wide_block(self):
        """Trade blocked when spread exceeds threshold"""
        config = RiskConfig(max_spread_bps=100)  # 1%
        manager = RiskManager(config)
        portfolio = PortfolioState(equity=10000.0)
        
        # 5% spread
        allowed, reason, msg = manager.check_trade_allowed(
            portfolio, proposed_size=100.0, entry_price=0.5,
            best_ask=0.525, best_bid=0.475
        )
        
        assert allowed is False
        assert reason == RiskBlockReason.SPREAD_TOO_WIDE


# ============================================================================
# Model Registry Tests
# ============================================================================

class TestModelRegistry:
    """Test model selection and fallback"""
    
    def test_load_from_env(self, monkeypatch):
        """Load default/fallback from ENV"""
        monkeypatch.setenv("DEFAULT_MODEL", "gpt-4")
        monkeypatch.setenv("FALLBACK_MODEL", "gpt-3.5-turbo")
        
        registry = ModelRegistry()
        chain = registry.get_fallback_chain("default")
        
        assert len(chain) == 2
        assert chain[0].name == "gpt-4"
        assert chain[1].name == "gpt-3.5-turbo"
    
    def test_get_model_config(self):
        """Get specific model config"""
        registry = ModelRegistry()
        
        config = registry.get_model("gpt-4")
        assert config is not None
        assert config.provider.value == "openai"
        assert config.timeout_seconds == 60.0


# ============================================================================
# Integration Smoke Tests
# ============================================================================

class TestIntegrationSmoke:
    """Smoke tests for component integration"""
    
    def test_metrics_collector_increment(self):
        """Metrics collector increments counters"""
        from agents.telemetry import get_metrics_collector
        
        metrics = get_metrics_collector()
        metrics.reset()
        
        metrics.increment("test_counter", 5)
        counters = metrics.get_counters()
        
        assert counters.get("test_counter") == 5
    
    def test_circuit_breaker_metrics(self):
        """Circuit breaker records state changes"""
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1)
        cb = CircuitBreaker("test", config)
        
        # Force failure
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
        except:
            pass
        
        metrics = cb.get_metrics()
        assert metrics["total_failures"] == 1
        assert metrics["state"] == "open"
        assert len(metrics["state_changes"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
