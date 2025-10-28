"""Confidence scoring for trade filtering"""

from typing import Dict, Optional
from datetime import datetime
from agents.utils.filters import QuantitativeFilters


class ConfidenceScorer:
    """
    Multi-factor confidence scoring to filter trades
    """

    def __init__(self):
        # Factor weights (sum to 1.0)
        self.weights = {
            'information_freshness': 0.30,
            'forecast_certainty': 0.25,
            'edge_magnitude': 0.20,
            'market_quality': 0.15,
            'time_to_resolution': 0.10
        }

    def score_information_freshness(self,
                                    news_recency: Optional[datetime] = None,
                                    max_age_hours: int = 48) -> float:
        """
        Score based on how recent the information is

        Args:
            news_recency: Timestamp of most recent news
            max_age_hours: Maximum age for full score (default 48 hours)

        Returns:
            Score 0.0-1.0
        """
        if news_recency is None:
            return 0.5  # No news data = neutral

        now = datetime.now(news_recency.tzinfo) if news_recency.tzinfo else datetime.now()
        age_hours = (now - news_recency).total_seconds() / 3600

        if age_hours <= max_age_hours:
            # Recent news = high score
            return 1.0 - (age_hours / max_age_hours) * 0.3  # Scale from 1.0 to 0.7
        else:
            # Stale news = low score
            return max(0.3, 0.7 - (age_hours - max_age_hours) / (max_age_hours * 2))

    def score_forecast_certainty(self, ensemble_agreement: float) -> float:
        """
        Score based on model agreement

        Args:
            ensemble_agreement: Agreement score from ensemble (0.0-1.0)

        Returns:
            Score 0.0-1.0
        """
        return ensemble_agreement

    def score_edge_magnitude(self,
                            forecast_probability: float,
                            market_price: float) -> float:
        """
        Score based on size of edge

        Args:
            forecast_probability: Your probability estimate
            market_price: Current market price

        Returns:
            Score 0.0-1.0
        """
        edge = abs(forecast_probability - market_price)

        # Scale edge to 0-1 score (20% edge = 1.0 score)
        return min(edge / 0.20, 1.0)

    def score_market_quality(self, market, min_volume: float = 5000) -> float:
        """
        Score based on market liquidity and spread

        Args:
            market: Market object
            min_volume: Minimum volume for full score

        Returns:
            Score 0.0-1.0
        """
        volume = QuantitativeFilters.get_market_volume(market)
        spread = QuantitativeFilters.get_market_spread(market)

        # Volume score (0-1)
        volume_score = min(volume / min_volume, 1.0) if volume > 0 else 0.5

        # Spread score (lower spread = higher score)
        # 1% spread = 1.0, 5% spread = 0.5, 10%+ = 0.0
        spread_score = max(0.0, 1.0 - spread / 0.10) if spread > 0 else 0.5

        return (volume_score + spread_score) / 2

    def score_time_to_resolution(self, market, optimal_days: int = 30) -> float:
        """
        Score based on time to resolution

        Args:
            market: Market object
            optimal_days: Optimal time to resolution for full score

        Returns:
            Score 0.0-1.0
        """
        days = QuantitativeFilters.days_until_close(market)

        if days is None:
            return 0.5  # Unknown = neutral

        # Optimal at 14-60 days, lower score for very short or very long
        if days < 3:
            return 0.3  # Too soon
        elif days < 14:
            return 0.5 + (days - 3) / 11 * 0.3  # Scale from 0.5 to 0.8
        elif days <= optimal_days:
            return 0.8 + (optimal_days - days) / (optimal_days - 14) * 0.2  # Scale to 1.0
        elif days <= 90:
            return 1.0 - (days - optimal_days) / 60 * 0.4  # Scale from 1.0 to 0.6
        else:
            return 0.4  # Too far out

    def calculate_confidence(self,
                            market,
                            forecast_probability: float,
                            market_price: float,
                            ensemble_agreement: Optional[float] = None,
                            news_recency: Optional[datetime] = None) -> Dict:
        """
        Calculate overall confidence score

        Args:
            market: Market object
            forecast_probability: Your probability estimate
            market_price: Current market price
            ensemble_agreement: Model agreement score (optional)
            news_recency: Timestamp of recent news (optional)

        Returns:
            dict with overall confidence and component scores
        """

        scores = {
            'information_freshness': self.score_information_freshness(news_recency),
            'forecast_certainty': self.score_forecast_certainty(ensemble_agreement or 0.8),
            'edge_magnitude': self.score_edge_magnitude(forecast_probability, market_price),
            'market_quality': self.score_market_quality(market),
            'time_to_resolution': self.score_time_to_resolution(market)
        }

        # Calculate weighted confidence
        confidence = sum(
            scores[factor] * self.weights[factor]
            for factor in self.weights.keys()
        )

        return {
            'overall_confidence': confidence,
            'component_scores': scores,
            'should_trade': confidence > 0.70,  # Only trade high confidence
            'confidence_level': (
                'VERY HIGH' if confidence > 0.85 else
                'HIGH' if confidence > 0.75 else
                'MODERATE' if confidence > 0.65 else
                'LOW'
            )
        }
