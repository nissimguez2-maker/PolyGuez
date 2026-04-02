import typer
from devtools import pprint

app = typer.Typer()

# Lazy-initialized singletons — avoids wallet/API errors at import time
_polymarket = None
_newsapi_client = None


def _get_polymarket():
    global _polymarket
    if _polymarket is None:
        from agents.polymarket.polymarket import Polymarket
        _polymarket = Polymarket()
    return _polymarket


def _get_news():
    global _newsapi_client
    if _newsapi_client is None:
        from agents.connectors.news import News
        _newsapi_client = News()
    return _newsapi_client


@app.command()
def get_all_markets(limit: int = 5, sort_by: str = "spread") -> None:
    """
    Query Polymarket's markets
    """
    print(f"limit: int = {limit}, sort_by: str = {sort_by}")
    polymarket = _get_polymarket()
    markets = polymarket.get_all_markets()
    markets = polymarket.filter_markets_for_trading(markets)
    if sort_by == "spread":
        markets = sorted(markets, key=lambda x: x.spread, reverse=True)
    markets = markets[:limit]
    pprint(markets)


@app.command()
def get_relevant_news(keywords: str) -> None:
    """
    Use NewsAPI to query the internet
    """
    newsapi_client = _get_news()
    articles = newsapi_client.get_articles_for_cli_keywords(keywords)
    pprint(articles)


@app.command()
def get_all_events(limit: int = 5, sort_by: str = "number_of_markets") -> None:
    """
    Query Polymarket's events
    """
    print(f"limit: int = {limit}, sort_by: str = {sort_by}")
    polymarket = _get_polymarket()
    events = polymarket.get_all_events()
    events = polymarket.filter_events_for_trading(events)
    if sort_by == "number_of_markets":
        events = sorted(events, key=lambda x: len(x.markets), reverse=True)
    events = events[:limit]
    pprint(events)


@app.command()
def run_polyguez(
    mode: str = typer.Option("dry-run", help="Mode: dry-run, paper, or live"),
    live: bool = typer.Option(False, "--live", help="Shortcut for --mode live"),
    dashboard: bool = typer.Option(True, help="Start dashboard server"),
    dashboard_port: int = typer.Option(
        None, "--dashboard-port", "--port",
        help="Dashboard port (default: $PORT or 8080)",
    ),
) -> None:
    """
    Run the PolyGuez Momentum strategy.
    Default is dry-run. Use --live for real execution.
    """
    import asyncio
    import threading

    from agents.application.run_polyguez import PolyGuezRunner
    from agents.utils.objects import PolyGuezConfig
    import os

    # Resolve port: CLI flag > $PORT env (Railway) > default 8080
    port = dashboard_port or int(os.getenv("PORT", "8080"))

    effective_mode = "live" if live else mode
    if effective_mode not in ("dry-run", "paper", "live"):
        print(f"Invalid mode: {effective_mode}. Using dry-run.")
        effective_mode = "dry-run"

    config = PolyGuezConfig(
        mode=effective_mode,
        rtds_ws_url=os.getenv("POLYMARKET_RTDS_URL", PolyGuezConfig().rtds_ws_url),
        binance_ws_url=os.getenv("BINANCE_WS_URL", PolyGuezConfig().binance_ws_url),
        coinbase_ws_url=os.getenv("COINBASE_WS_URL", PolyGuezConfig().coinbase_ws_url),
        dashboard_secret=os.getenv("DASHBOARD_SECRET", ""),
    )

    runner = PolyGuezRunner(config=config)

    if dashboard:
        from scripts.python.server import app as fastapi_app, set_runner
        import uvicorn

        set_runner(runner)

        def _start_dashboard():
            uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="warning")

        t = threading.Thread(target=_start_dashboard, daemon=True)
        t.start()
        print(f"Dashboard running on port {port}")

    print(f"PolyGuez starting in [{effective_mode.upper()}] mode")
    asyncio.run(runner.run())


@app.command()
def kill() -> None:
    """
    Send kill signal to a running PolyGuez instance via the dashboard API.
    """
    import httpx
    import os

    port = int(os.getenv("POLYGUEZ_DASHBOARD_PORT", "8080"))
    secret = os.getenv("DASHBOARD_SECRET", "")
    url = f"http://localhost:{port}/api/kill"
    try:
        resp = httpx.post(url, params={"secret": secret})
        print(f"Kill response: {resp.json()}")
    except Exception as e:
        print(f"Failed to reach dashboard: {e}")


if __name__ == "__main__":
    app()
