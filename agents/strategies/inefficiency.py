"""Market inefficiency hunting strategies"""

from typing import List, Optional
from agents.utils.filters import QuantitativeFilters


class InefficiencyStrategies:
    """
    Specialized strategies for finding market inefficiencies
    """

    @staticmethod
    def find_obscure_markets(markets: List,
                            max_volume: float = 10000,
                            min_spread: float = 0.03,
                            min_days: int = 7) -> List:
        """
        Find low-volume markets where LLMs have edge over thin liquidity

        Strategy: Information advantage over less sophisticated market participants

        Args:
            markets: List of markets to filter
            max_volume: Maximum volume (default $10k)
            min_spread: Minimum spread indicating potential mispricing (default 3%)
            min_days: Minimum days to resolution (default 7)

        Returns:
            Filtered list of obscure markets
        """
        filtered = []

        for market in markets:
            volume = QuantitativeFilters.get_market_volume(market)
            spread = QuantitativeFilters.get_market_spread(market)
            days = QuantitativeFilters.days_until_close(market)

            # Low volume + wide spread + sufficient time = opportunity
            if (volume > 0 and volume < max_volume and
                spread > min_spread and
                days and days > min_days):
                filtered.append(market)

        return filtered

    @staticmethod
    def find_time_decay_plays(markets: List,
                             min_days: int = 1,
                             max_days: int = 7) -> List:
        """
        Find markets near resolution with potentially stale probabilities

        Strategy: Speed advantage via fresh information search

        Args:
            markets: List of markets to filter
            min_days: Minimum days to resolution (default 1)
            max_days: Maximum days to resolution (default 7)

        Returns:
            Filtered list of markets near resolution
        """
        filtered = []

        for market in markets:
            days = QuantitativeFilters.days_until_close(market)

            if days and min_days < days < max_days:
                filtered.append(market)

        return filtered

    @staticmethod
    def find_extreme_mispricing(markets: List,
                               extreme_threshold: float = 0.90) -> List:
        """
        Find markets with extreme probabilities that might be mispriced

        Strategy: Contrarian plays on overconfident markets

        Args:
            markets: List of markets to filter
            extreme_threshold: Threshold for extreme pricing (default 0.90 = 90%)

        Returns:
            Markets with extreme probabilities
        """
        import ast

        filtered = []

        for market in markets:
            try:
                if isinstance(market, tuple):
                    prices_str = market[0].metadata.get('outcome_prices', '[]')
                else:
                    prices_str = market.outcome_prices

                prices = ast.literal_eval(prices_str) if isinstance(prices_str, str) else prices_str

                # Check if any outcome is extremely priced
                for price in prices:
                    if isinstance(price, (int, float)):
                        if price > extreme_threshold or price < (1 - extreme_threshold):
                            # Market is extremely confident - might be mispriced
                            filtered.append(market)
                            break
            except:
                continue

        return filtered

    @classmethod
    def get_strategy_recommendations(cls, markets: List) -> dict:
        """
        Analyze markets and recommend which strategy to apply

        Returns:
            dict with strategy recommendations and filtered markets
        """
        return {
            'obscure_markets': cls.find_obscure_markets(markets),
            'time_decay_plays': cls.find_time_decay_plays(markets),
            'extreme_mispricing': cls.find_extreme_mispricing(markets)
        }
