# Local Run Notes

This document provides a short checklist for running Polymarket agents locally during development.

## 1. Prepare environment variables

At minimum, you will typically need:

- `POLYGON_WALLET_PRIVATE_KEY`
- `OPENAI_API_KEY`
- any provider-specific URLs (for example, an RPC endpoint)

You can load them from a `.env` file or export them in your shell.

## 2. Install dependencies

Using a virtual environment is recommended:

    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    pip install -r requirements.txt

If the project uses Poetry, follow the instructions in the main README.

## 3. Run the main entrypoint

Typically, there will be a main script or CLI entrypoint such as:

    python -m agents

or an explicit script, for example:

    python scripts/run_agent.py

Refer to the main documentation for the exact entrypoint name.

## 4. Logs and debugging

- Check stdout and stderr for high-level errors.
- Enable more verbose logging if there is a debug or verbose flag.
- For long-running agents, consider writing logs to a file or using a structured logging backend.

These notes are meant as a quick reminder and do not replace the main README.
