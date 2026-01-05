# Agent deployment guide

This document walks through deploying a Polymarket agent in a production environment.

1. **Clone the repository** and create a virtual environment.
2. **Set environment variables** (`POLYGON_WALLET_PRIVATE_KEY`, `OPENAI_API_KEY`, etc.).
3. **Install dependencies** with `pip install -r requirements.txt`.
4. **Run the agent**: `python agents/main.py`.

For Docker deployments, build the image with `docker build -t polymarket-agent .` and configure secrets via environment variables.
