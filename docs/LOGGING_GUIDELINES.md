# Logging Guidelines

This document defines log levels and conventions for agent services.

## Levels

- DEBUG: detailed internal state (disabled by default)
- INFO: high-level events (startup, shutdown)
- WARN: recoverable issues (retry attempts)
- ERROR: unrecoverable failures

## Rules

- Do not log secrets (API keys, private keys).
- Use structured logging where supported.
- Include request IDs or correlation IDs.
- Keep messages clear and concise.

Consistent logging helps with debugging and monitoring.
