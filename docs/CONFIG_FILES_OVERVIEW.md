# Config Files Overview

This document briefly describes where configuration for Polymarket
agents typically lives.

## Environment variables

Many settings are provided via environment variables, for example:

- API keys for external services,
- private keys for signing transactions,
- feature flags.

Use a `.env` file or your shell to set these values, and avoid
committing them to version control.

## `config/` directory

If present, the `config/` directory may contain:

- YAML or JSON files describing agent behavior,
- network endpoints and timeouts,
- feature toggles.

Keep such files generic and avoid including secrets.

## `logs/` directory

By convention, logs may be written to a `logs/` directory in the
project root. If you are troubleshooting an issue, it can be helpful
to inspect the most recent log files in this directory.

This overview is intentionally high-level and should be read together
with the main project documentation.
