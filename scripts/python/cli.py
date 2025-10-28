import typer
from devtools import pprint

from agents.polymarket.polymarket import Polymarket
from agents.connectors.chroma import PolymarketRAG
from agents.connectors.news import News
from agents.application.trade import Trader
from agents.application.executor import Executor
from agents.application.creator import Creator
from agents.application.enhanced_trader import EnhancedTrader
from agents.analytics.metrics import MarketMetrics
from agents.analytics.calibration import CalibrationTracker
from agents.risk.portfolio import PortfolioManager

app = typer.Typer()
polymarket = Polymarket()
newsapi_client = News()
polymarket_rag = PolymarketRAG()


@app.command()
def get_all_markets(limit: int = 5, sort_by: str = "spread") -> None:
    """
    Query Polymarket's markets
    """
    print(f"limit: int = {limit}, sort_by: str = {sort_by}")
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
    articles = newsapi_client.get_articles_for_cli_keywords(keywords)
    pprint(articles)


@app.command()
def get_all_events(limit: int = 5, sort_by: str = "number_of_markets") -> None:
    """
    Query Polymarket's events
    """
    print(f"limit: int = {limit}, sort_by: str = {sort_by}")
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
    polymarket_rag.create_local_markets_rag(local_directory=local_directory)


@app.command()
def query_local_markets_rag(vector_db_directory: str, query: str) -> None:
    """
    RAG over a local database of Polymarket's events
    """
    response = polymarket_rag.query_local_markets_rag(
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
    c = Creator()
    market_description = c.one_best_market()
    print(f"market_description: str = {market_description}")


@app.command()
def ask_llm(user_input: str) -> None:
    """
    Ask a question to the LLM and get a response.
    """
    executor = Executor()
    response = executor.get_llm_response(user_input)
    print(f"LLM Response: {response}")


@app.command()
def ask_polymarket_llm(user_input: str) -> None:
    """
    What types of markets do you want trade?
    """
    executor = Executor()
    response = executor.get_polymarket_llm(user_input=user_input)
    print(f"LLM + current markets&events response: {response}")


@app.command()
def run_autonomous_trader() -> None:
    """
    Let an autonomous system trade for you (basic version).
    """
    trader = Trader()
    trader.one_best_trade()


@app.command()
def run_enhanced_trader() -> None:
    """
    Run enhanced autonomous trader with all new features:
    - Category-based filtering (information edge)
    - Quantitative pre-filters
    - News integration
    - Kelly sizing
    - Confidence scoring
    - Risk controls
    """
    trader = EnhancedTrader()
    trader.one_best_trade_enhanced()


@app.command()
def analyze_market_categories() -> None:
    """
    Analyze available markets by category and information edge.
    Shows which categories have the most tradeable opportunities.
    """
    metrics = MarketMetrics()
    metrics.analyze_market_universe(polymarket)


@app.command()
def show_performance() -> None:
    """
    Display calibration and portfolio performance metrics.
    """
    print("\n" + "="*70)
    print("PERFORMANCE DASHBOARD")
    print("="*70 + "\n")

    calibration = CalibrationTracker()
    calibration.print_performance_report()

    portfolio = PortfolioManager()
    portfolio.print_portfolio_summary()


@app.command()
def monitor_positions() -> None:
    """
    Monitor open positions and execute stop-loss/take-profit rules.
    """
    trader = EnhancedTrader()
    trader.monitor_and_exit_positions()


@app.command()
def find_obscure_markets(max_volume: float = 10000, min_spread: float = 0.03) -> None:
    """
    Find low-volume markets where LLMs may have edge.

    Args:
        max_volume: Maximum market volume (default $10k)
        min_spread: Minimum spread indicating mispricing (default 3%)
    """
    from agents.strategies.inefficiency import InefficiencyStrategies

    markets = polymarket.get_all_markets()
    obscure = InefficiencyStrategies.find_obscure_markets(
        markets,
        max_volume=max_volume,
        min_spread=min_spread
    )

    print(f"\nFound {len(obscure)} obscure markets:\n")
    for market in obscure[:10]:
        print(f"  - {market.question}")
        print(f"    Volume: ${market.volume:,.0f}, Spread: {market.spread:.2%}\n")


@app.command()
def find_time_decay_plays(min_days: int = 1, max_days: int = 7) -> None:
    """
    Find markets near resolution (potentially stale pricing).

    Args:
        min_days: Minimum days to close (default 1)
        max_days: Maximum days to close (default 7)
    """
    from agents.strategies.inefficiency import InefficiencyStrategies

    markets = polymarket.get_all_markets()
    time_decay = InefficiencyStrategies.find_time_decay_plays(
        markets,
        min_days=min_days,
        max_days=max_days
    )

    print(f"\nFound {len(time_decay)} markets near resolution:\n")
    for market in time_decay[:10]:
        from agents.utils.filters import QuantitativeFilters
        days = QuantitativeFilters.days_until_close(market)
        print(f"  - {market.question}")
        print(f"    Closes in: {days:.1f} days\n")


if __name__ == "__main__":
    app()
