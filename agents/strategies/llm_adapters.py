"""Pluggable LLM adapter interface for trade confirmation."""

import asyncio
import os
import re
from abc import ABC, abstractmethod

from dotenv import load_dotenv

from agents.utils.logger import get_logger, log_event

load_dotenv()
logger = get_logger("polyguez.llm")

_VERDICT_RE = re.compile(
    r"VERDICT:\s*(GO|NO-GO|REDUCE-SIZE)\s*\|\s*REASON:\s*(.+)",
    re.IGNORECASE,
)


_NEGATIVE_RE = re.compile(
    r"\bNO\b|REJECT|DECLINE|AGAINST|WOULDN'T|NOT ADVISABLE",
    re.IGNORECASE,
)


def parse_llm_response(raw):
    """Extract (verdict, reason) from LLM output. Returns ('NO-GO', 'parse-fallback') on failure."""
    match = _VERDICT_RE.search(raw.strip())
    if match:
        return (match.group(1).upper(), match.group(2).strip())
    upper = raw.strip().upper()
    if "NO-GO" in upper:
        return ("NO-GO", raw.strip()[:200])
    if "REDUCE-SIZE" in upper:
        return ("REDUCE-SIZE", raw.strip()[:200])
    if "GO" in upper:
        return ("GO", raw.strip()[:200])
    if _NEGATIVE_RE.search(raw.strip()):
        return ("NO-GO", raw.strip()[:200])
    return ("NO-GO", "parse-fallback")


class LLMAdapter(ABC):
    """Base class for LLM confirmation adapters."""

    name = "base"

    @abstractmethod
    async def confirm_trade(self, prompt, timeout):
        """Send prompt to LLM, return (verdict, reason).

        Must respect timeout (seconds). On any failure, return ('NO-GO', 'llm-unavailable').
        """
        raise NotImplementedError


class OpenAIAdapter(LLMAdapter):
    """OpenAI adapter using langchain_openai (repo's existing integration)."""

    name = "openai"

    def __init__(self, model=None):
        self._model = model or os.getenv("LLM_MODEL_OPENAI", "gpt-4o-mini")

    async def confirm_trade(self, prompt, timeout):
        loop = asyncio.get_event_loop()
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage

            from langchain_core.messages import SystemMessage

            llm = ChatOpenAI(model=self._model, temperature=0, request_timeout=timeout)
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: llm.invoke([
                        SystemMessage(content="Respond with exactly one word: GO or NO-GO. No explanation."),
                        HumanMessage(content=prompt),
                    ]).content,
                ),
                timeout=timeout,
            )
            return parse_llm_response(result)
        except asyncio.TimeoutError:
            log_event(logger, "llm_timeout", f"OpenAI timed out after {timeout}s")
            return ("NO-GO", "llm-unavailable")
        except Exception as exc:
            log_event(logger, "llm_error", f"OpenAI error: {exc}")
            return ("NO-GO", f"llm-unavailable: {exc}")


class AnthropicAdapter(LLMAdapter):
    """Anthropic adapter using the anthropic SDK."""

    name = "anthropic"

    def __init__(self, model=None):
        self._model = model or os.getenv("LLM_MODEL_ANTHROPIC", "claude-3-5-haiku-20241022")

    async def confirm_trade(self, prompt, timeout):
        try:
            import anthropic

            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if not api_key:
                return ("NO-GO", "llm-unavailable")

            client = anthropic.AsyncAnthropic(api_key=api_key)
            response = await asyncio.wait_for(
                client.messages.create(
                    model=self._model,
                    max_tokens=5,
                    system="Respond with exactly one word: GO or NO-GO. No explanation.",
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=timeout,
            )
            raw = response.content[0].text
            return parse_llm_response(raw)
        except asyncio.TimeoutError:
            log_event(logger, "llm_timeout", f"Anthropic timed out after {timeout}s")
            return ("NO-GO", "llm-unavailable")
        except Exception as exc:
            log_event(logger, "llm_error", f"Anthropic error: {exc}")
            return ("NO-GO", f"llm-unavailable: {exc}")


class GroqAdapter(LLMAdapter):
    """Groq adapter using the groq SDK."""

    name = "groq"

    def __init__(self, model=None):
        self._model = model or os.getenv("LLM_MODEL_GROQ", "llama-3.3-70b-versatile")

    async def confirm_trade(self, prompt, timeout):
        loop = asyncio.get_event_loop()
        try:
            from groq import Groq

            api_key = os.getenv("GROQ_API_KEY", "")
            if not api_key:
                return ("NO-GO", "llm-unavailable")

            client = Groq(api_key=api_key)

            def _call():
                return client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": "Respond with exactly one word: GO or NO-GO. No explanation."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=5,
                    temperature=0,
                )

            response = await asyncio.wait_for(
                loop.run_in_executor(None, _call),
                timeout=timeout,
            )
            raw = response.choices[0].message.content
            return parse_llm_response(raw)
        except asyncio.TimeoutError:
            log_event(logger, "llm_timeout", f"Groq timed out after {timeout}s")
            return ("NO-GO", "llm-unavailable")
        except Exception as exc:
            log_event(logger, "llm_error", f"Groq error: {exc}")
            return ("NO-GO", f"llm-unavailable: {exc}")


# -- Registry ----------------------------------------------------------------

_ADAPTER_REGISTRY = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "groq": GroqAdapter,
}


def get_llm_adapter(config):
    """Return the configured LLM adapter instance."""
    provider = config.llm_provider
    cls = _ADAPTER_REGISTRY.get(provider)
    if cls is None:
        log_event(logger, "llm_error", f"Unknown LLM provider: {provider}, falling back to openai")
        cls = OpenAIAdapter

    model_map = {
        "openai": config.llm_model_openai,
        "anthropic": config.llm_model_anthropic,
        "groq": config.llm_model_groq,
    }
    model = model_map.get(provider)
    return cls(model=model)
