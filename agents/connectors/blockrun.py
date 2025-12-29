"""
BlockRun LLM Provider for Polymarket Agents

BlockRun enables AI agents to access 31+ LLMs (GPT-4, Claude, Gemini, etc.)
via x402 USDC micropayments on Base. No API keys required - agents pay
directly with their wallets.

Learn more: https://blockrun.ai
"""

import os
from typing import Optional

from langchain_openai import ChatOpenAI


# BlockRun model mappings (OpenAI-compatible format)
BLOCKRUN_MODELS = {
    # OpenAI models
    "gpt-5": "openai/gpt-5",
    "gpt-4o": "openai/gpt-4o",
    "gpt-4o-mini": "openai/gpt-4o-mini",
    "gpt-4-turbo": "openai/gpt-4-turbo",
    "gpt-3.5-turbo": "openai/gpt-3.5-turbo",
    "gpt-3.5-turbo-16k": "openai/gpt-3.5-turbo-16k",
    # Anthropic models
    "claude-3-5-sonnet": "anthropic/claude-3-5-sonnet",
    "claude-3-5-haiku": "anthropic/claude-3-5-haiku",
    "claude-3-opus": "anthropic/claude-3-opus",
    # Google models
    "gemini-2.0-flash": "google/gemini-2.0-flash",
    "gemini-1.5-pro": "google/gemini-1.5-pro",
    "gemini-1.5-flash": "google/gemini-1.5-flash",
}

# Token limits for BlockRun models
BLOCKRUN_TOKEN_LIMITS = {
    "openai/gpt-5": 256000,
    "openai/gpt-4o": 128000,
    "openai/gpt-4o-mini": 128000,
    "openai/gpt-4-turbo": 128000,
    "openai/gpt-3.5-turbo": 16000,
    "openai/gpt-3.5-turbo-16k": 16000,
    "anthropic/claude-3-5-sonnet": 200000,
    "anthropic/claude-3-5-haiku": 200000,
    "anthropic/claude-3-opus": 200000,
    "google/gemini-2.0-flash": 1000000,
    "google/gemini-1.5-pro": 2000000,
    "google/gemini-1.5-flash": 1000000,
}


def get_blockrun_model_name(model: str) -> str:
    """Convert common model names to BlockRun format."""
    return BLOCKRUN_MODELS.get(model, model)


def get_blockrun_token_limit(model: str) -> int:
    """Get token limit for a BlockRun model."""
    blockrun_model = get_blockrun_model_name(model)
    return BLOCKRUN_TOKEN_LIMITS.get(blockrun_model, 16000)


def create_blockrun_llm(
    model: str = "gpt-4o",
    temperature: float = 0,
    base_url: Optional[str] = None,
) -> ChatOpenAI:
    """
    Create a LangChain ChatOpenAI instance configured for BlockRun.

    BlockRun is an x402-enabled AI gateway that allows agents to pay for
    LLM inference with USDC micropayments. No API key management required.

    Args:
        model: Model name (e.g., "gpt-4o", "claude-3-5-sonnet", "gemini-2.0-flash")
        temperature: Response randomness (0-2)
        base_url: BlockRun API URL (defaults to https://api.blockrun.ai/v1)

    Returns:
        ChatOpenAI instance configured for BlockRun

    Example:
        >>> llm = create_blockrun_llm(model="gpt-4o")
        >>> response = llm.invoke("What is the probability of X?")

    Note:
        BlockRun uses x402 wallet-based authentication. Ensure your agent's
        wallet has USDC on Base for payment. No OPENAI_API_KEY needed.
    """
    blockrun_base_url = base_url or os.getenv(
        "BLOCKRUN_API_URL", "https://api.blockrun.ai/v1"
    )

    # Convert model name to BlockRun format
    blockrun_model = get_blockrun_model_name(model)

    return ChatOpenAI(
        model=blockrun_model,
        temperature=temperature,
        base_url=blockrun_base_url,
        api_key="x402-wallet-auth",  # BlockRun uses wallet auth, not API keys
    )


def list_available_models() -> dict:
    """List all available BlockRun models with their token limits."""
    return {
        model: {
            "blockrun_name": blockrun_name,
            "token_limit": BLOCKRUN_TOKEN_LIMITS.get(blockrun_name, 16000),
        }
        for model, blockrun_name in BLOCKRUN_MODELS.items()
    }
