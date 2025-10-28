"""Kelly Criterion position sizing and risk management"""

import math
from typing import Optional


class KellySizing:
    """Dynamic position sizing using Kelly Criterion"""

    @staticmethod
    def calculate_kelly_size(
        forecast_probability: float,
        market_price: float,
        confidence: float = 1.0,
        kelly_fraction: float = 0.25,
        max_position_size: float = 0.15
    ) -> float:
        """
        Calculate optimal position size using Kelly Criterion

        Args:
            forecast_probability: Your estimated probability (0.0-1.0)
            market_price: Current market price (0.0-1.0)
            confidence: Confidence multiplier based on ensemble agreement (0.0-1.0)
            kelly_fraction: Fraction of full Kelly to use (default 0.25 = quarter Kelly)
            max_position_size: Maximum position size cap (default 0.15 = 15%)

        Returns:
            Position size as fraction of bankroll (0.0-1.0)

        Formula:
            edge = forecast_probability - market_price
            kelly = edge / (1 - market_price)
            final_size = kelly * confidence * kelly_fraction
        """

        # Calculate edge
        edge = forecast_probability - market_price

        # No edge or negative edge = no trade
        if edge <= 0:
            return 0.0

        # Kelly formula: f* = edge / odds
        # For binary outcomes: f* = p - (1-p)/odds
        # Simplified: f* = edge / (1 - price)
        if market_price >= 0.99:
            # Avoid division by zero
            return 0.0

        kelly = edge / (1.0 - market_price)

        # Apply confidence adjustment (from ensemble agreement)
        adjusted_kelly = kelly * confidence

        # Use fractional Kelly for safety (typically 1/4 or 1/2)
        fractional_kelly = adjusted_kelly * kelly_fraction

        # Cap at maximum position size
        final_size = min(fractional_kelly, max_position_size)

        # Ensure non-negative
        return max(0.0, final_size)

    @staticmethod
    def calculate_size_with_edge_threshold(
        forecast_probability: float,
        market_price: float,
        confidence: float = 1.0,
        min_edge: float = 0.05
    ) -> Optional[float]:
        """
        Only return position size if edge exceeds minimum threshold

        Args:
            forecast_probability: Your probability estimate
            market_price: Current market price
            confidence: Confidence score
            min_edge: Minimum edge required to trade (default 5%)

        Returns:
            Position size or None if edge too small
        """

        edge = abs(forecast_probability - market_price)

        if edge < min_edge:
            return None

        return KellySizing.calculate_kelly_size(
            forecast_probability,
            market_price,
            confidence
        )

    @staticmethod
    def determine_side(forecast_probability: float, market_price: float) -> str:
        """
        Determine BUY or SELL based on forecast vs market price

        Args:
            forecast_probability: Your probability estimate
            market_price: Current market price

        Returns:
            "BUY" if forecast > price, "SELL" if forecast < price
        """

        if forecast_probability > market_price:
            return "BUY"
        elif forecast_probability < market_price:
            return "SELL"
        else:
            return "NONE"

    @staticmethod
    def calculate_position_for_trade(
        forecast_probability: float,
        market_price: float,
        available_capital: float,
        confidence: float = 1.0,
        min_edge: float = 0.05
    ) -> Optional[dict]:
        """
        Calculate complete trade recommendation

        Returns:
            dict with side, size_fraction, size_usd, or None if no trade
        """

        size_fraction = KellySizing.calculate_size_with_edge_threshold(
            forecast_probability,
            market_price,
            confidence,
            min_edge
        )

        if size_fraction is None or size_fraction == 0:
            return None

        side = KellySizing.determine_side(forecast_probability, market_price)

        if side == "NONE":
            return None

        return {
            'side': side,
            'size_fraction': size_fraction,
            'size_usd': size_fraction * available_capital,
            'edge': abs(forecast_probability - market_price),
            'forecast': forecast_probability,
            'price': market_price
        }
