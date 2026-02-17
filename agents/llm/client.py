"""
Model Selection and Fallback Handler for LLM Calls
Block D
"""

import os
import time
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ModelProvider(Enum):
    """Supported LLM providers"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    # Extendable for other providers


@dataclass
class ModelConfig:
    """Configuration for a model"""
    name: str
    provider: ModelProvider
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_delay: float = 1.0
    
    # Rate limiting (requests per minute)
    rpm_limit: int = 60


class ModelRegistry:
    """Registry of available models with fallback chain"""
    
    # Default model configurations
    DEFAULT_MODELS = {
        "gpt-4": ModelConfig(
            name="gpt-4",
            provider=ModelProvider.OPENAI,
            timeout_seconds=60.0,
            max_retries=2,
            rpm_limit=200
        ),
        "gpt-4-turbo": ModelConfig(
            name="gpt-4-turbo-preview",
            provider=ModelProvider.OPENAI,
            timeout_seconds=60.0,
            max_retries=2,
            rpm_limit=200
        ),
        "gpt-3.5-turbo": ModelConfig(
            name="gpt-3.5-turbo",
            provider=ModelProvider.OPENAI,
            timeout_seconds=30.0,
            max_retries=3,
            rpm_limit=3500
        ),
        "gpt-3.5-turbo-16k": ModelConfig(
            name="gpt-3.5-turbo-16k",
            provider=ModelProvider.OPENAI,
            timeout_seconds=45.0,
            max_retries=3,
            rpm_limit=3500
        ),
        "claude-3-opus": ModelConfig(
            name="claude-3-opus-20240229",
            provider=ModelProvider.ANTHROPIC,
            timeout_seconds=60.0,
            max_retries=2,
            rpm_limit=100
        ),
        "claude-3-sonnet": ModelConfig(
            name="claude-3-sonnet-20240229",
            provider=ModelProvider.ANTHROPIC,
            timeout_seconds=45.0,
            max_retries=2,
            rpm_limit=1000
        )
    }
    
    def __init__(self):
        self.models: Dict[str, ModelConfig] = {}
        self.fallback_chains: Dict[str, List[str]] = {}
        self._load_from_env()
    
    def _load_from_env(self):
        """Load model configuration from environment"""
        # Primary model
        default_model = os.getenv("DEFAULT_MODEL", "gpt-3.5-turbo-16k")
        
        # Fallback model
        fallback_model = os.getenv("FALLBACK_MODEL", "gpt-3.5-turbo")
        
        # Build fallback chain
        self.fallback_chains["default"] = [default_model, fallback_model]
        
        # Load all default models
        for name, config in self.DEFAULT_MODELS.items():
            self.models[name] = config
        
        logger.info(f"Model registry initialized. Default: {default_model}, Fallback: {fallback_model}")
    
    def get_model(self, name: str) -> Optional[ModelConfig]:
        """Get model configuration by name"""
        return self.models.get(name)
    
    def get_fallback_chain(self, chain_name: str = "default") -> List[ModelConfig]:
        """Get ordered list of models to try"""
        chain = self.fallback_chains.get(chain_name, [])
        return [self.models[name] for name in chain if name in self.models]


class LLMClient:
    """LLM client with automatic fallback handling"""
    
    def __init__(self, registry: Optional[ModelRegistry] = None):
        self.registry = registry or ModelRegistry()
        self._init_clients()
    
    def _init_clients(self):
        """Initialize provider clients"""
        self._openai_client = None
        self._anthropic_client = None
        
        # Lazy initialization on first use
    
    def _get_openai_client(self):
        """Get or create OpenAI client"""
        if self._openai_client is None:
            try:
                from openai import OpenAI
                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key:
                    raise ValueError("OPENAI_API_KEY not set")
                self._openai_client = OpenAI(api_key=api_key)
            except ImportError:
                raise ImportError("OpenAI package not installed. Run: pip install openai")
        return self._openai_client
    
    def _get_anthropic_client(self):
        """Get or create Anthropic client"""
        if self._anthropic_client is None:
            try:
                import anthropic
                api_key = os.getenv("ANTHROPIC_API_KEY")
                if not api_key:
                    raise ValueError("ANTHROPIC_API_KEY not set")
                self._anthropic_client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                raise ImportError("Anthropic package not installed. Run: pip install anthropic")
        return self._anthropic_client
    
    def call(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        chain_name: str = "default"
    ) -> Dict[str, Any]:
        """
        Call LLM with automatic fallback
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Specific model to use (overrides default chain)
            temperature: Sampling temperature
            max_tokens: Max tokens to generate
            chain_name: Which fallback chain to use
        
        Returns:
            Dict with 'content', 'model_used', 'latency_ms', etc.
        
        Raises:
            Exception if all models in chain fail
        """
        # Determine which models to try
        if model:
            models_to_try = [self.registry.get_model(model)] if self.registry.get_model(model) else []
        else:
            models_to_try = self.registry.get_fallback_chain(chain_name)
        
        if not models_to_try:
            raise ValueError(f"No valid models found for chain '{chain_name}'")
        
        last_error = None
        
        for model_config in models_to_try:
            for attempt in range(model_config.max_retries + 1):
                start_time = time.time()
                
                try:
                    result = self._call_model(
                        messages=messages,
                        model_config=model_config,
                        temperature=temperature,
                        max_tokens=max_tokens
                    )
                    
                    latency_ms = (time.time() - start_time) * 1000
                    
                    return {
                        "content": result,
                        "model_used": model_config.name,
                        "provider": model_config.provider.value,
                        "latency_ms": latency_ms,
                        "attempt": attempt + 1,
                        "success": True
                    }
                
                except Exception as e:
                    last_error = e
                    latency_ms = (time.time() - start_time) * 1000
                    
                    # Check if it's a rate limit or server error (retryable)
                    error_str = str(e).lower()
                    is_retryable = any(err in error_str for err in [
                        "rate limit", "429", "timeout", "503", "502", "500"
                    ])
                    
                    if is_retryable and attempt < model_config.max_retries:
                        logger.warning(
                            f"[{model_config.name}] Retryable error (attempt {attempt + 1}): {e}"
                        )
                        time.sleep(model_config.retry_delay * (2 ** attempt))  # Exponential backoff
                    else:
                        logger.error(f"[{model_config.name}] Failed after {attempt + 1} attempts: {e}")
                        break  # Move to next model in chain
        
        # All models failed
        raise Exception(f"All models in chain failed. Last error: {last_error}")
    
    def _call_model(
        self,
        messages: List[Dict[str, str]],
        model_config: ModelConfig,
        temperature: float,
        max_tokens: Optional[int]
    ) -> str:
        """Call specific model provider"""
        if model_config.provider == ModelProvider.OPENAI:
            return self._call_openai(messages, model_config, temperature, max_tokens)
        elif model_config.provider == ModelProvider.ANTHROPIC:
            return self._call_anthropic(messages, model_config, temperature, max_tokens)
        else:
            raise ValueError(f"Unknown provider: {model_config.provider}")
    
    def _call_openai(
        self,
        messages: List[Dict[str, str]],
        model_config: ModelConfig,
        temperature: float,
        max_tokens: Optional[int]
    ) -> str:
        """Call OpenAI API"""
        client = self._get_openai_client()
        
        kwargs = {
            "model": model_config.name,
            "messages": messages,
            "temperature": temperature,
            "timeout": model_config.timeout_seconds
        }
        
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
    
    def _call_anthropic(
        self,
        messages: List[Dict[str, str]],
        model_config: ModelConfig,
        temperature: float,
        max_tokens: Optional[int]
    ) -> str:
        """Call Anthropic API"""
        client = self._get_anthropic_client()
        
        # Convert messages to Anthropic format
        system_msg = ""
        user_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                user_messages.append(msg)
        
        # Build prompt
        prompt = ""
        for msg in user_messages:
            if msg["role"] == "user":
                prompt += f"\n\nHuman: {msg['content']}"
            elif msg["role"] == "assistant":
                prompt += f"\n\nAssistant: {msg['content']}"
        
        prompt += "\n\nAssistant:"
        
        kwargs = {
            "model": model_config.name,
            "max_tokens": max_tokens or 1024,
            "temperature": temperature,
            "timeout": model_config.timeout_seconds
        }
        
        if system_msg:
            kwargs["system"] = system_msg
        
        response = client.messages.create(
            messages=user_messages,
            **kwargs
        )
        
        return response.content[0].text


# Convenience functions for easy use

def get_llm_client() -> LLMClient:
    """Get singleton LLM client"""
    return LLMClient()


def llm_call(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None
) -> str:
    """
    Simple function to call LLM with fallback
    
    Returns just the content string for convenience
    """
    client = get_llm_client()
    result = client.call(messages, model, temperature, max_tokens)
    return result["content"]
