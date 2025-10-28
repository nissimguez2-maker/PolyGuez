"""Quantitative filters for market pre-screening before LLM analysis"""

from datetime import datetime, timedelta
from typing import Optional
import ast


class QuantitativeFilters:
    """Pre-filter markets using quantitative criteria to reduce LLM costs"""

    @staticmethod
    def parse_date(date_str: str) -> Optional[datetime]:
        """Parse ISO date string to datetime"""
        try:
            # Handle various date formats
            if 'T' in date_str:
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return datetime.fromisoformat(date_str)
        except:
            return None

    @staticmethod
    def days_until_close(market) -> Optional[float]:
        """Calculate days until market closes"""
        # Handle both SimpleMarket and tuple (from RAG)
        if isinstance(market, tuple):
            end_date_str = market[0].metadata.get('end', '')
        else:
            end_date_str = market.end

        end_date = QuantitativeFilters.parse_date(end_date_str)
        if end_date:
            now = datetime.now(end_date.tzinfo) if end_date.tzinfo else datetime.now()
            delta = end_date - now
            return delta.total_seconds() / 86400  # Convert to days
        return None

    @staticmethod
    def get_market_volume(market) -> float:
        """Extract market volume"""
        try:
            if isinstance(market, tuple):
                # From RAG, may need to access differently
                return 0.0  # RAG doesn't include volume in metadata
            return float(market.volume) if hasattr(market, 'volume') else 0.0
        except:
            return 0.0

    @staticmethod
    def get_market_spread(market) -> float:
        """Extract market spread"""
        try:
            if isinstance(market, tuple):
                spread = market[0].metadata.get('spread', 0.0)
                return float(spread) if spread else 0.0
            return float(market.spread) if hasattr(market, 'spread') else 0.0
        except:
            return 0.0

    @staticmethod
    def has_extreme_prices(market) -> bool:
        """Check if market has extreme probabilities (>95% or <5%)"""
        try:
            if isinstance(market, tuple):
                prices_str = market[0].metadata.get('outcome_prices', '[]')
            else:
                prices_str = market.outcome_prices

            prices = ast.literal_eval(prices_str) if isinstance(prices_str, str) else prices_str

            for price in prices:
                if isinstance(price, (int, float)):
                    if price > 0.95 or price < 0.05:
                        return True
            return False
        except:
            return False

    @classmethod
    def filter_tradeable_markets(cls,
                                 markets: list,
                                 min_volume: float = 5000,      # $5k minimum
                                 max_spread: float = 0.05,       # 5% max spread
                                 min_days_to_close: float = 3,   # At least 3 days
                                 max_days_to_close: float = 180, # Not too far out
                                 exclude_extreme_prices: bool = True) -> list:
        """Apply quantitative filters to reduce search space"""

        filtered = []

        for market in markets:
            # Check volume (if available)
            volume = cls.get_market_volume(market)
            if volume > 0 and volume < min_volume:
                continue

            # Check spread
            spread = cls.get_market_spread(market)
            if spread > 0 and spread > max_spread:
                continue

            # Check time to close
            days = cls.days_until_close(market)
            if days is not None:
                if days < min_days_to_close or days > max_days_to_close:
                    continue

            # Check for extreme prices (low edge potential)
            if exclude_extreme_prices and cls.has_extreme_prices(market):
                continue

            filtered.append(market)

        return filtered

    @classmethod
    def filter_for_obscure_markets(cls, markets: list) -> list:
        """Find low-volume markets where LLMs have edge over thin liquidity"""
        filtered = []

        for market in markets:
            volume = cls.get_market_volume(market)
            spread = cls.get_market_spread(market)
            days = cls.days_until_close(market)

            # Low volume + wide spread + sufficient time = opportunity
            if (volume < 10000 and  # Under $10k volume
                spread > 0.03 and   # >3% spread (mispricing potential)
                days and days > 7): # At least a week to resolution
                filtered.append(market)

        return filtered

    @classmethod
    def filter_for_time_decay_plays(cls, markets: list) -> list:
        """Find markets near resolution with stale probabilities"""
        filtered = []

        for market in markets:
            days = cls.days_until_close(market)

            # Close to resolution
            if days and 1 < days < 7:  # Between 1-7 days
                filtered.append(market)

        return filtered
