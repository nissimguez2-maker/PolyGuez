"""
LLM Client Module - Model Selection and Fallback
Block D
"""

from .client import (
    LLMClient,
    ModelRegistry,
    ModelConfig,
    ModelProvider,
    get_llm_client,
    llm_call
)

__all__ = [
    "LLMClient",
    "ModelRegistry",
    "ModelConfig",
    "ModelProvider",
    "get_llm_client",
    "llm_call"
]
