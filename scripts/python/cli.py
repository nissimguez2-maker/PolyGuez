import typer
from devtools import pprint

app = typer.Typer()

# Lazy-initialized singletons — avoids wallet/API errors at import time
_polymarket = None
_newsapi_client = None
_polymarket_rag = None


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


def _get_rag():
    global _polymarket_rag
    if _polymarket_rag is None:
        from agents.connectors.chroma import PolymarketRAG
        _polymarket_rag = PolymarketRAG()
    return _polymarket_rag


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
def create_local_markets_rag(local_directory: str) -> None:
    """
    Create a local markets database for RAG
    """
    _get_rag().create_local_markets_rag(local_directory=local_directory)


@app.command()
def query_local_markets_rag(vector_db_directory: str, query: str) -> None:
    """
    RAG over a local database of Polymarket's events
    """
    response = _get_rag().query_local_markets_rag(
        local_directory=vector_db_directory, query=query
    )
    pprint(response)


@app.command()
def ask_superforecaster(event_title: str, market_question: str, outcome: str) -> None:
    """
    Ask a superforecaster about a trade
    """
    print(
        f"event: str = {event_title}, question: str = {market_question}, outcome (usually yes or no): str = {outcome}"
    )
    from agents.application.executor import Executor
    executor = Executor()
    response = executor.get_superforecast(
        event_title=event_title, market_question=market_question, outcome=outcome
    )
    print(f"Response:{response}")


@app.command()
def create_market() -> None:
    """
    Format a request to create a market on Polymarket
    """
    from agents.application.creator import Creator
    c = Creator()
    market_description = c.one_best_market()
    print(f"market_description: str = {market_description}")


@app.command()
def ask_llm(user_input: str) -> None:
    """
    Ask a question to the LLM and get a response.
    """
    from agents.application.executor import Executor
    executor = Executor()
    response = executor.get_llm_response(user_input)
    print(f"LLM Response: {response}")


@app.command()
def ask_polymarket_llm(user_input: str) -> None:
    """
    What types of markets do you want trade?
    """
    from agents.application.executor import Executor
    executor = Executor()
    response = executor.get_polymarket_llm(user_input=user_input)
    print(f"LLM + current markets&events response: {response}")


@app.command()
def run_autonomous_trader() -> None:
    """
    Let an autonomous system trade for you.
    """
    from agents.application.trade import Trader
    trader = Trader()
    trader.one_best_trade()


@app.command()
def run_polyguez(
    mode: str = typer.Option("dry-run", help="Mode: dry-run, paper, or live"),
    live: bool = typer.Option(False, "--live", help="Shortcut for --mode live"),
    dashboard: bool = typer.Option(True, help="Start dashboard server"),
    port: int = typer.Option(8080, help="Dashboard port"),
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

    effective_mode = "live" if live else mode
    if effective_mode not in ("dry-run", "paper", "live"):
        print(f"Invalid mode: {effective_mode}. Using dry-run.")
        effective_mode = "dry-run"

    config = PolyGuezConfig(
        mode=effective_mode,
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
        print(f"Dashboard running at http://localhost:{port}")

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
