"""Enhanced Trader with all new features integrated"""

from agents.application.executor import Executor as Agent
from agents.polymarket.gamma import GammaMarketClient as Gamma
from agents.polymarket.polymarket import Polymarket
from agents.connectors.news import News
from agents.utils.classifier import MarketClassifier
from agents.utils.filters import QuantitativeFilters
from agents.analytics.calibration import CalibrationTracker
from agents.analytics.metrics import MarketMetrics
from agents.risk.sizing import KellySizing
from agents.risk.portfolio import PortfolioManager
from agents.risk.circuit_breakers import CircuitBreaker, TradingHalted
from agents.risk.exit_rules import ExitRules
from agents.strategies.inefficiency import InefficiencyStrategies
from agents.strategies.confidence import ConfidenceScorer
import shutil
import ast
from collections import Counter


class EnhancedTrader:
    """
    Advanced trader with:
    - Category-based filtering (information edge focus)
    - Quantitative pre-filters
    - News integration
    - Kelly sizing
    - Portfolio management
    - Risk controls
    - Calibration tracking
    """

    def __init__(self):
        self.polymarket = Polymarket()
        self.gamma = Gamma()
        self.agent = Agent()
        self.news = News()

        # Analytics
        self.calibration = CalibrationTracker()
        self.metrics = MarketMetrics()

        # Risk management
        self.portfolio = PortfolioManager(max_positions=10)
        self.circuit_breaker = CircuitBreaker()
        self.exit_rules = ExitRules(
            stop_loss_pct=0.15,
            take_profit_pct=0.25,
            trailing_stop_pct=0.10
        )

        # Strategy components
        self.confidence_scorer = ConfidenceScorer()

        # Configuration
        self.min_skill_weight = 0.65  # Only trade markets with 65%+ skill factor
        self.min_confidence = 0.70    # Only trade with 70%+ confidence
        self.min_edge = 0.05          # Minimum 5% edge required

    def pre_trade_logic(self) -> None:
        """Pre-trade checks and cleanup"""
        self.clear_local_dbs()

        # Check circuit breakers
        try:
            self.circuit_breaker.check_halt_conditions(self.portfolio)
        except TradingHalted as e:
            print(f"\n⚠️  TRADING HALTED: {e}\n")
            raise

    def clear_local_dbs(self) -> None:
        """Clear local RAG databases"""
        try:
            shutil.rmtree("local_db_events")
        except:
            pass
        try:
            shutil.rmtree("local_db_markets")
        except:
            pass

    def one_best_trade_enhanced(self) -> None:
        """
        Enhanced trading strategy with all new features:
        1. Category filtering (information edge)
        2. Quantitative pre-filters
        3. News integration
        4. Confidence scoring
        5. Kelly sizing
        6. Risk controls
        7. Calibration tracking
        """
        try:
            self.pre_trade_logic()

            # Step 1: Get all tradeable events
            print("\n" + "="*70)
            print("STEP 1: Fetching Tradeable Events")
            print("="*70)
            events = self.polymarket.get_all_tradeable_events()
            print(f"✓ Found {len(events)} total events")

            # Step 2: Filter events with RAG (now category-aware)
            print("\n" + "="*70)
            print("STEP 2: Filtering Events (Category + RAG)")
            print("="*70)
            filtered_events = self.agent.filter_events_with_rag(events)
            print(f"✓ Filtered to {len(filtered_events)} high-potential events")

            # Step 3: Map to markets
            print("\n" + "="*70)
            print("STEP 3: Mapping Events to Markets")
            print("="*70)
            markets = self.agent.map_filtered_events_to_markets(filtered_events)
            print(f"✓ Found {len(markets)} associated markets")

            # Step 4: CATEGORY FILTERING - Only skill-based markets
            print("\n" + "="*70)
            print("STEP 4: Category Filtering (Information Edge)")
            print("="*70)
            high_edge_markets = MarketClassifier.filter_by_information_edge(
                markets,
                min_skill_weight=self.min_skill_weight
            )

            category_summary = MarketClassifier.get_category_summary(high_edge_markets)
            print(f"✓ Filtered to {len(high_edge_markets)} high-edge markets")
            print(f"  Categories: {dict(category_summary)}")

            if len(high_edge_markets) == 0:
                print("\n⚠️  No high-information-edge markets found. Aborting.")
                return

            # Step 5: QUANTITATIVE FILTERING - Remove illiquid/extreme markets
            print("\n" + "="*70)
            print("STEP 5: Quantitative Pre-Filtering")
            print("="*70)
            tradeable_markets = QuantitativeFilters.filter_tradeable_markets(
                high_edge_markets,
                min_volume=5000,
                max_spread=0.05,
                min_days_to_close=3,
                max_days_to_close=180,
                exclude_extreme_prices=True
            )
            print(f"✓ {len(tradeable_markets)} markets pass quantitative filters")

            if len(tradeable_markets) == 0:
                print("\n⚠️  No tradeable markets after filtering. Aborting.")
                return

            # Step 6: RAG filtering on tradeable markets
            print("\n" + "="*70)
            print("STEP 6: Final RAG Filtering")
            print("="*70)
            filtered_markets = self.agent.filter_markets(tradeable_markets)
            print(f"✓ Top {len(filtered_markets)} markets selected")

            if len(filtered_markets) == 0:
                print("\n⚠️  No markets after RAG filtering. Aborting.")
                return

            # Step 7: Get best market and analyze
            market_tuple = filtered_markets[0]
            market_data = market_tuple[0].dict()
            market_metadata = market_data["metadata"]

            market_question = market_metadata["question"]
            description = market_data["page_content"]
            outcomes = ast.literal_eval(market_metadata["outcomes"])
            outcome_prices = ast.literal_eval(market_metadata["outcome_prices"])
            market_id = market_metadata["id"]
            category = getattr(market_tuple, 'category', 'unknown')

            print("\n" + "="*70)
            print("STEP 7: Analyzing Selected Market")
            print("="*70)
            print(f"Market: {market_question}")
            print(f"Category: {category.upper()}")
            print(f"Outcomes: {outcomes}")
            print(f"Current Prices: {outcome_prices}")

            # Step 8: NEWS INTEGRATION - Get recent news for context
            print("\n" + "="*70)
            print("STEP 8: Fetching Recent News")
            print("="*70)
            try:
                articles = self.news.get_articles_for_options(market_question, outcomes)
                print(f"✓ Found {len(articles)} relevant articles")
                news_context = "\n".join([
                    f"- {a.title}: {a.description}" for a in articles[:5]
                ])
            except Exception as e:
                print(f"⚠️  News fetch failed: {e}")
                news_context = ""

            # Step 9: Generate forecast
            print("\n" + "="*70)
            print("STEP 9: Generating Forecast (Superforecaster)")
            print("="*70)
            forecast_response = self.agent.source_best_trade(market_tuple)
            print(f"Forecast: {forecast_response}")

            # Step 10: KELLY SIZING - Calculate optimal position
            print("\n" + "="*70)
            print("STEP 10: Calculating Position Size (Kelly Criterion)")
            print("="*70)

            # Extract probability from forecast (simplified - would use regex in production)
            import re
            prob_match = re.search(r'(\d+\.\d+)', forecast_response)
            if not prob_match:
                print("⚠️  Could not extract probability from forecast. Aborting.")
                return

            forecast_probability = float(prob_match.group(1))
            market_price = outcome_prices[0]  # Assuming binary market

            print(f"Forecast Probability: {forecast_probability:.2%}")
            print(f"Market Price: {market_price:.2%}")
            print(f"Edge: {abs(forecast_probability - market_price):.2%}")

            # Calculate Kelly size
            trade_params = KellySizing.calculate_position_for_trade(
                forecast_probability=forecast_probability,
                market_price=market_price,
                available_capital=self.polymarket.get_usdc_balance(),
                confidence=0.8,  # Default confidence (would use ensemble in production)
                min_edge=self.min_edge
            )

            if trade_params is None:
                print(f"\n⚠️  Insufficient edge ({abs(forecast_probability - market_price):.2%} < {self.min_edge:.2%}). No trade.")
                return

            print(f"\n✓ Trade Parameters:")
            print(f"  Side: {trade_params['side']}")
            print(f"  Size: {trade_params['size_fraction']:.1%} (${trade_params['size_usd']:,.2f})")
            print(f"  Edge: {trade_params['edge']:.2%}")

            # Step 11: CONFIDENCE SCORING
            print("\n" + "="*70)
            print("STEP 11: Confidence Assessment")
            print("="*70)

            confidence_result = self.confidence_scorer.calculate_confidence(
                market=market_tuple,
                forecast_probability=forecast_probability,
                market_price=market_price,
                ensemble_agreement=0.8,  # Would use actual ensemble
                news_recency=None  # Would use actual news timestamp
            )

            print(f"Overall Confidence: {confidence_result['overall_confidence']:.1%} ({confidence_result['confidence_level']})")
            print(f"Component Scores:")
            for component, score in confidence_result['component_scores'].items():
                print(f"  {component}: {score:.2f}")

            if not confidence_result['should_trade']:
                print(f"\n⚠️  Confidence too low ({confidence_result['overall_confidence']:.1%} < {self.min_confidence:.1%}). No trade.")
                return

            # Step 12: PORTFOLIO CHECK
            print("\n" + "="*70)
            print("STEP 12: Portfolio Risk Check")
            print("="*70)

            if not self.portfolio.should_add_position(
                new_position_size=trade_params['size_fraction'],
                category=category,
                max_category_exposure=0.25
            ):
                print("⚠️  Portfolio risk limits would be exceeded. No trade.")
                return

            print("✓ Portfolio risk check passed")

            # Step 13: CIRCUIT BREAKER CHECK
            print("\n" + "="*70)
            print("STEP 13: Circuit Breaker Check")
            print("="*70)

            try:
                self.circuit_breaker.check_position_size(trade_params['size_fraction'])
                print("✓ Circuit breaker check passed")
            except TradingHalted as e:
                print(f"⚠️  {e}")
                return

            # Step 14: LOG FORECAST (for calibration tracking)
            print("\n" + "="*70)
            print("STEP 14: Logging Forecast")
            print("="*70)

            forecast_id = self.calibration.log_forecast(
                market_id=str(market_id),
                market_question=market_question,
                outcome=outcomes[0],
                forecast_probability=forecast_probability,
                market_price=market_price,
                category=category,
                confidence_score=confidence_result['overall_confidence']
            )
            print(f"✓ Forecast logged (ID: {forecast_id})")

            # Step 15: EXECUTE TRADE (currently disabled per TOS)
            print("\n" + "="*70)
            print("STEP 15: Trade Execution")
            print("="*70)
            print("⚠️  TRADE EXECUTION DISABLED (see TOS: polymarket.com/tos)")
            print(f"\nWould execute:")
            print(f"  Market: {market_question}")
            print(f"  Side: {trade_params['side']}")
            print(f"  Size: ${trade_params['size_usd']:,.2f}")
            print(f"  Expected Price: {market_price:.4f}")

            # If execution were enabled:
            # trade = self.polymarket.execute_market_order(market_tuple, trade_params['size_usd'])
            # trade_id = self.calibration.log_trade(forecast_id, market_id, ...)
            # position_id = self.portfolio.add_position(...)

            print("\n" + "="*70)
            print("TRADE ANALYSIS COMPLETE")
            print("="*70 + "\n")

        except TradingHalted as e:
            print(f"\n🛑 Trading halted: {e}\n")
        except Exception as e:
            print(f"\n❌ Error: {e}\n")
            import traceback
            traceback.print_exc()

    def monitor_and_exit_positions(self):
        """Monitor open positions and execute stop-loss/take-profit"""
        print("\n" + "="*70)
        print("MONITORING OPEN POSITIONS")
        print("="*70 + "\n")

        exit_signals = self.exit_rules.monitor_positions(
            self.portfolio,
            self.polymarket
        )

        if exit_signals:
            print(f"Found {len(exit_signals)} positions to exit")
            self.exit_rules.execute_exits(
                exit_signals,
                self.portfolio,
                self.polymarket
            )
        else:
            print("No positions require exit")

    def show_performance(self):
        """Display performance metrics"""
        self.calibration.print_performance_report()
        self.portfolio.print_portfolio_summary()


if __name__ == "__main__":
    trader = EnhancedTrader()
    trader.one_best_trade_enhanced()
