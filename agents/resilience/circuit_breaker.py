"""
Circuit Breaker Pattern for API Resilience
Block B - Step 1
"""

import time
import random
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from datetime import datetime, timedelta
import threading


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5          # Failures before opening
    recovery_timeout: int = 60          # Seconds before half-open
    half_open_max_calls: int = 3        # Test calls in half-open
    success_threshold: int = 2          # Successes to close
    
    # Per-service defaults
    @classmethod
    def for_service(cls, service_name: str) -> "CircuitBreakerConfig":
        configs = {
            "polymarket": cls(
                failure_threshold=3,      # Fast fail for trading
                recovery_timeout=30,      # Quick recovery
                half_open_max_calls=1,
                success_threshold=1
            ),
            "gamma": cls(
                failure_threshold=5,
                recovery_timeout=60,
                half_open_max_calls=2,
                success_threshold=2
            ),
            "openai": cls(
                failure_threshold=10,     # More lenient for AI
                recovery_timeout=120,
                half_open_max_calls=2,
                success_threshold=2
            )
        }
        return configs.get(service_name, cls())


class CircuitBreaker:
    """Circuit breaker for API resilience"""
    
    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        
        self._lock = threading.Lock()
        
        # Metrics for telemetry
        self._metrics = {
            "state_changes": [],
            "total_failures": 0,
            "total_successes": 0,
            "blocked_calls": 0
        }
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state"""
        with self._lock:
            self._check_recovery_timeout()
            return self._state
    
    def _check_recovery_timeout(self):
        """Check if we should transition to half-open"""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.config.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    self._success_count = 0
                    self._log_state_change("OPEN -> HALF_OPEN")
    
    def _log_state_change(self, transition: str):
        """Log state transition for metrics"""
        self._metrics["state_changes"].append({
            "timestamp": datetime.utcnow().isoformat(),
            "transition": transition,
            "service": self.name
        })
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection
        
        Raises CircuitBreakerOpen if circuit is open
        """
        with self._lock:
            self._check_recovery_timeout()
            
            # Check if circuit is open
            if self._state == CircuitState.OPEN:
                self._metrics["blocked_calls"] += 1
                raise CircuitBreakerOpen(
                    f"Circuit {self.name} is OPEN. Last failure: "
                    f"{self._last_failure_time}"
                )
            
            # Check half-open limit
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    self._metrics["blocked_calls"] += 1
                    raise CircuitBreakerOpen(
                        f"Circuit {self.name} is HALF_OPEN (max calls reached)"
                    )
                self._half_open_calls += 1
        
        # Execute the call (outside lock)
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        """Handle successful call"""
        with self._lock:
            self._metrics["total_successes"] += 1
            
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._log_state_change("HALF_OPEN -> CLOSED")
            else:
                # In closed state, just reset failure count
                self._failure_count = 0
    
    def _on_failure(self):
        """Handle failed call"""
        with self._lock:
            self._metrics["total_failures"] += 1
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                # Failure in half-open -> back to open
                self._state = CircuitState.OPEN
                self._log_state_change("HALF_OPEN -> OPEN")
            elif self._failure_count >= self.config.failure_threshold:
                # Too many failures -> open circuit
                self._state = CircuitState.OPEN
                self._log_state_change("CLOSED -> OPEN")
    
    def get_metrics(self) -> dict:
        """Get circuit breaker metrics"""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "total_failures": self._metrics["total_failures"],
                "total_successes": self._metrics["total_successes"],
                "blocked_calls": self._metrics["blocked_calls"],
                "state_changes": self._metrics["state_changes"][-10:]  # Last 10
            }
    
    def force_reset(self):
        """Force circuit back to closed (for manual recovery)"""
        with self._lock:
            old_state = self._state
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._last_failure_time = None
            if old_state != CircuitState.CLOSED:
                self._log_state_change(f"{old_state.value} -> CLOSED (forced)")


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open"""
    pass


# Global circuit breaker registry
_circuit_breakers: dict = {}
_registry_lock = threading.Lock()


def get_circuit_breaker(name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
    """Get or create circuit breaker for service"""
    with _registry_lock:
        if name not in _circuit_breakers:
            if config is None:
                config = CircuitBreakerConfig.for_service(name)
            _circuit_breakers[name] = CircuitBreaker(name, config)
        return _circuit_breakers[name]


def get_all_circuit_metrics() -> dict:
    """Get metrics for all circuit breakers"""
    with _registry_lock:
        return {
            name: cb.get_metrics()
            for name, cb in _circuit_breakers.items()
        }
