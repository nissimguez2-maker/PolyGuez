# Logging Conventions

This document defines logging conventions for agents and supporting services.

## Log levels

- DEBUG: detailed internal state, disabled by default
- INFO: normal operational events
- WARN: unexpected situations that are recoverable
- ERROR: failed operations requiring attention

## Guidelines

- Do not log secrets, private keys, or tokens.
- Prefer structured logs over free-form strings.
- Include request or correlation IDs when available.
- Keep log messages concise and actionable.

## Examples

Good:
"order_submit_failed", order_id=123, reason="insufficient_balance"

Bad:
"Something went wrong with order 123, balance was low"

Consistent logging makes debugging and monitoring significantly easier.
