# PolyGuez

Algorithmic trading bot for Polymarket BTC/ETH crypto resolution markets.
Trades based on Chainlink oracle price feeds vs. market strike prices,
with Binance real-time price data for momentum signals.

## How it works

1. Scans Polymarket for active BTC/ETH price resolution markets
2. Reads Chainlink oracle prices (on-chain, manipulation-resistant)
3. Compares current price vs. market strike to compute directional edge
4. Evaluates 10 conditions before firing a trade
5. Executes CLOB limit orders via Polymarket API

## Architecture

| Module | Purpose |
|---|---|
| `agents/application/run_polyguez.py` | Main bot loop |
| `agents/strategies/polyguez_strategy.py` | Signal logic and trade decisions |
| `agents/connectors/chainlink_feed.py` | On-chain oracle price feed |
| `agents/polymarket/polymarket.py` | CLOB order execution |
| `agents/polymarket/gamma.py` | Market discovery |
| `scripts/python/server.py` | Live dashboard server |
| `scripts/frontend/dashboard.html` | Real-time monitoring UI |

## Setup

1. Clone the repo and create a virtual environment (Python 3.11)
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in your keys
4. Deploy to Railway or run locally:
   `PYTHONPATH=. python agents/application/run_polyguez.py`

## Environment variables

See `.env.example` for all required and optional variables.

## License

MIT — based on [polymarket/agents](https://github.com/polymarket/agents)
