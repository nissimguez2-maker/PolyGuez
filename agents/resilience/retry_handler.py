"""
Retry Handler with Exponential Backoff and Jitter
Block B - Step 2
"""

import time
import random
import functools
from typing import Callable, Optional, Tuple, Type, Any
from dataclasses import dataclass
import logging

# Setup logging
logger = logging.getLogger(__name__)


@dataclass
class RetryConfig:
    """Configuration for retry behavior"""
    max_retries: int = 3
    base_delay: float = 1.0          # Initial delay in seconds
    max_delay: float = 60.0          # Cap delay at this
    exponential_base: float = 2.0    # Multiplier for each retry
    jitter: bool = True              # Add randomness to delay
    jitter_max: float = 1.0          # Max jitter in seconds
    
    # Retry only these exceptions
    retryable_exceptions: Tuple[Type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        Exception  # Catch-all, but should be more specific
    )
    
    # Don't retry these (e.g., auth failures)
    non_retryable_exceptions: Tuple[Type[Exception], ...] = (
        ValueError,
        TypeError,
        KeyError
    )


class RetryHandler:
    """Handles retries with exponential backoff"""
    
    def __init__(self, config: Optional[RetryConfig] = None, name: str = "default"):
        self.config = config or RetryConfig()
        self.name = name
        self._metrics = {
            "total_calls": 0,
            "successful_first_try": 0,
            "successful_after_retry": 0,
            "total_failures": 0,
            "retries_performed": 0
        }
    
    def calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay for retry attempt
        
        Uses exponential backoff with optional jitter
        """
        # Exponential: base * (2 ^ attempt)
        delay = self.config.base_delay * (self.config.exponential_base ** attempt)
        
        # Cap at max_delay
        delay = min(delay, self.config.max_delay)
        
        # Add jitter to avoid thundering herd
        if self.config.jitter:
            jitter = random.uniform(0, self.config.jitter_max)
            delay += jitter
        
        return delay
    
    def should_retry(self, exception: Exception) -> bool:
        """Determine if exception should trigger retry"""
        # Check non-retryable first (explicit deny)
        if isinstance(exception, self.config.non_retryable_exceptions):
            return False
        
        # Check retryable
        return isinstance(exception, self.config.retryable_exceptions)
    
    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with retry logic
        
        Returns: Function result
        Raises: Last exception if all retries exhausted
        """
        self._metrics["total_calls"] += 1
        last_exception = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                result = func(*args, **kwargs)
                
                # Success
                if attempt == 0:
                    self._metrics["successful_first_try"] += 1
                else:
                    self._metrics["successful_after_retry"] += 1
                
                return result
                
            except Exception as e:
                last_exception = e
                
                # Check if we should retry
                if not self.should_retry(e):
                    logger.debug(f"[{self.name}] Non-retryable exception: {e}")
                    break
                
                # Check if we have retries left
                if attempt >= self.config.max_retries:
                    logger.warning(
                        f"[{self.name}] Max retries ({self.config.max_retries}) exhausted"
                    )
                    break
                
                # Calculate and apply delay
                delay = self.calculate_delay(attempt)
                self._metrics["retries_performed"] += 1
                
                logger.info(
                    f"[{self.name}] Retry {attempt + 1}/{self.config.max_retries} "
                    f"after {delay:.2f}s due to: {e}"
                )
                
                time.sleep(delay)
        
        # All retries exhausted
        self._metrics["total_failures"] += 1
        raise last_exception
    
    def get_metrics(self) -> dict:
        """Get retry metrics"""
        total = self._metrics["total_calls"]
        success = self._metrics["successful_first_try"] + self._metrics["successful_after_retry"]
        
        return {
            "name": self.name,
            "total_calls": total,
            "success_rate": success / total if total > 0 else 0,
            "first_try_success_rate": self._metrics["successful_first_try"] / total if total > 0 else 0,
            "retry_success_rate": self._metrics["successful_after_retry"] / total if total > 0 else 0,
            "total_failures": self._metrics["total_failures"],
            "retries_performed": self._metrics["retries_performed"]
        }


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    name: Optional[str] = None
):
    """
    Decorator for adding retry logic to functions
    
    Usage:
        @with_retry(max_retries=3, base_delay=1.0)
        def fetch_data():
            return api.get_data()
    """
    config = RetryConfig(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay
    )
    if retryable_exceptions:
        config.retryable_exceptions = retryable_exceptions
    
    def decorator(func: Callable) -> Callable:
        handler = RetryHandler(config, name or func.__name__)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return handler.execute(func, *args, **kwargs)
        
        # Attach metrics getter
        wrapper.get_retry_metrics = handler.get_metrics
        
        return wrapper
    
    return decorator


# Pre-configured retry handlers for common services

def get_polymarket_retry() -> RetryHandler:
    """Retry handler for Polymarket API"""
    return RetryHandler(
        config=RetryConfig(
            max_retries=5,
            base_delay=1.0,
            max_delay=30.0,
            retryable_exceptions=(ConnectionError, TimeoutError, Exception)
        ),
        name="polymarket_api"
    )


def get_gamma_retry() -> RetryHandler:
    """Retry handler for Gamma API"""
    return RetryHandler(
        config=RetryConfig(
            max_retries=3,
            base_delay=0.5,
            max_delay=10.0,
            retryable_exceptions=(ConnectionError, TimeoutError, Exception)
        ),
        name="gamma_api"
    )


def get_openai_retry() -> RetryHandler:
    """Retry handler for OpenAI API"""
    return RetryHandler(
        config=RetryConfig(
            max_retries=3,
            base_delay=2.0,
            max_delay=60.0,
            retryable_exceptions=(ConnectionError, TimeoutError, Exception)
        ),
        name="openai_api"
    )
