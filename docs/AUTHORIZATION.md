# API authorization and scopes

The Polymarket agents require valid API keys to interact with the backend.

## API keys

- Obtain an API key from your dashboard and keep it secret.
- Set `POLYMARKET_API_KEY` in your `.env` file or environment.

## Scopes

API keys may have different scopes:

- `read:markets` – read market data
- `trade:orders` – place and cancel orders
- `read:positions` – read your positions

When generating a key, select the minimum required scopes. Expose keys only to trusted systems.

## Revocation

You can revoke an API key at any time from your dashboard. The agent will stop functioning until you provide a new key.
