"""
BlockRun LLM Provider for Polymarket Agents

BlockRun enables AI agents to access 31+ LLMs (GPT-4, Claude, Gemini, etc.)
via x402 USDC micropayments on Base. No API keys required - agents pay
directly with their wallets.

Payment: USDC on Base network only.

Security: Your private key NEVER leaves your machine. It is only used locally
to sign EIP-712 payment authorizations. Only the signature is transmitted -
BlockRun never sees your private key.

Learn more: https://blockrun.ai

Installation:
    pip install blockrun-llm
"""

import os
from typing import Any, Dict, List, Optional

from blockrun_llm import LLMClient, AsyncLLMClient


# BlockRun model mappings (short names to full model IDs)
BLOCKRUN_MODELS = {
    "gpt-5": "openai/gpt-5",
    "gpt-4o": "openai/gpt-4o",
    "gpt-4o-mini": "openai/gpt-4o-mini",
    "gpt-4-turbo": "openai/gpt-4-turbo",
    "claude-3-5-sonnet": "anthropic/claude-3-5-sonnet",
    "claude-3-5-haiku": "anthropic/claude-3-5-haiku",
    "claude-3-opus": "anthropic/claude-3-opus",
    "gemini-2.0-flash": "google/gemini-2.0-flash",
    "gemini-1.5-pro": "google/gemini-1.5-pro",
    "gemini-1.5-flash": "google/gemini-1.5-flash",
}


class BlockRunClient:
    """
    BlockRun LLM client wrapper for Polymarket Agents.

    Uses the official blockrun-llm SDK which handles x402 payments automatically:
    1. Make request to BlockRun API
    2. Receive 402 Payment Required with payment details
    3. SDK signs EIP-712 USDC transfer authorization locally
    4. SDK retries request with payment signature

    Payment: USDC on Base network only. Ensure your wallet has USDC on Base.
    Your private key is NEVER transmitted - only used locally for signing.

    Args:
        private_key: Wallet private key for signing payments (or set BLOCKRUN_WALLET_KEY env var)
        base_url: BlockRun API URL (default: https://blockrun.ai/api)
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        base_url: str = "https://blockrun.ai/api",
    ):
        self._client = LLMClient(
            private_key=private_key,
            api_url=base_url,
        )

    def chat(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        """
        Simple chat interface.

        Args:
            model: Model ID (e.g., "gpt-4o", "claude-3-5-sonnet")
            prompt: User message
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Response randomness (0-2)

        Returns:
            Assistant's response text
        """
        # Convert short model names to BlockRun format
        blockrun_model = BLOCKRUN_MODELS.get(model, model)

        return self._client.chat(
            model=blockrun_model,
            prompt=prompt,
            system=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """
        Full chat completion interface (OpenAI-compatible).

        Args:
            model: Model ID
            messages: List of message dicts with role and content
            max_tokens: Maximum tokens to generate
            temperature: Response randomness (0-2)

        Returns:
            OpenAI-compatible chat completion response
        """
        # Convert short model names to BlockRun format
        blockrun_model = BLOCKRUN_MODELS.get(model, model)

        result = self._client.chat_completion(
            model=blockrun_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # Convert ChatResponse to dict for compatibility
        return {
            "model": result.model,
            "choices": [
                {
                    "index": c.index,
                    "message": {
                        "role": c.message.role,
                        "content": c.message.content,
                    },
                    "finish_reason": c.finish_reason,
                }
                for c in result.choices
            ],
            "usage": {
                "prompt_tokens": result.usage.prompt_tokens if result.usage else 0,
                "completion_tokens": result.usage.completion_tokens if result.usage else 0,
                "total_tokens": result.usage.total_tokens if result.usage else 0,
            } if result.usage else None,
        }

    def get_wallet_address(self) -> str:
        """Get the wallet address used for payments."""
        return self._client.get_wallet_address()

    def list_models(self) -> List[Dict[str, Any]]:
        """List available models with pricing."""
        return self._client.list_models()

    def close(self):
        """Close the client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def create_blockrun_client(
    private_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> BlockRunClient:
    """
    Create a BlockRun client with x402 payment support.

    Args:
        private_key: Wallet private key (or set BLOCKRUN_WALLET_KEY env var)
        base_url: BlockRun API URL (or set BLOCKRUN_API_URL env var)

    Returns:
        BlockRunClient instance

    Example:
        >>> client = create_blockrun_client(private_key="0x...")
        >>> response = client.chat("gpt-4o", "What is 2+2?")
    """
    pk = private_key or os.getenv("BLOCKRUN_WALLET_KEY") or os.getenv("BLOCKRUN_PRIVATE_KEY")

    url = base_url or os.getenv("BLOCKRUN_API_URL", "https://blockrun.ai/api")

    return BlockRunClient(private_key=pk, base_url=url)


def list_available_models() -> Dict[str, str]:
    """List all available BlockRun models."""
    return BLOCKRUN_MODELS.copy()
