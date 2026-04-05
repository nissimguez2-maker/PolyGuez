"""
RealizedVolTracker — 30-minute rolling realized volatility for BTC.

Usage:
    tracker = RealizedVolTracker()
    tracker.update(btc_price)          # call on every price tick
    sigma = tracker.sigma()            # None if <10 samples
    iv = implied_vol(token_price, spot, strike, seconds_remaining, sigma)
"""
import math
import time
import collections
from typing import Optional


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function (no scipy needed)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _brentq(f, a: float, b: float, xtol: float = 1e-4, maxiter: int = 50) -> float:
    """Minimal Brent root-finder replacing scipy.optimize.brentq."""
    fa, fb = f(a), f(b)
    if fa * fb > 0:
        raise ValueError("f(a) and f(b) must have opposite signs")
    for _ in range(maxiter):
        c = (a + b) / 2.0
        fc = f(c)
        if abs(fc) < xtol or (b - a) / 2.0 < xtol:
            return c
        if fa * fc < 0:
            b, fb = c, fc
        else:
            a, fa = c, fc
    return (a + b) / 2.0


class RealizedVolTracker:
    WINDOW_SECONDS = 1800  # 30-minute rolling window
    SIGMA_FLOOR = 0.20  # min 20% annualised
    SIGMA_CAP = 3.00  # max 300% annualised
    MIN_SAMPLES = 10  # need at least 10 prices to compute

    def __init__(self):
        self._prices: collections.deque = collections.deque()  # (ts, price)

    def update(self, price: float, ts: Optional[float] = None) -> None:
        """Add a new BTC price observation. ts defaults to now."""
        if price is None or price <= 0:
            return
        if ts is None:
            ts = time.time()
        self._prices.append((ts, price))
        # Evict samples older than the window
        cutoff = ts - self.WINDOW_SECONDS
        while self._prices and self._prices[0][0] < cutoff:
            self._prices.popleft()

    def sigma(self) -> Optional[float]:
        """
        Return annualised realized vol, or None if too few samples.
        Uses all log-returns in the rolling window, annualised by
        actual elapsed time (not assumed frequency).
        """
        if len(self._prices) < self.MIN_SAMPLES:
            return None
        prices = [p for _, p in self._prices]
        returns = [
            math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))
        ]
        if not returns:
            return None
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        duration = self._prices[-1][0] - self._prices[0][0]
        if duration <= 0:
            return None
        # Annualise: scale variance by (seconds_per_year / avg_interval)
        avg_interval = duration / len(returns)
        samples_per_year = 31_536_000 / avg_interval
        sigma = math.sqrt(variance * samples_per_year)
        return max(self.SIGMA_FLOOR, min(self.SIGMA_CAP, sigma))


def implied_vol(
    token_price: float,
    spot: float,
    strike: float,
    seconds_remaining: float,
    sigma_hint: Optional[float] = None,
) -> Optional[float]:
    """
    Invert the BS digital-call formula to get the vol the market is implying.
    Returns None if the inputs are degenerate or the solver fails.
    """
    T = seconds_remaining / 31_536_000.0
    if T <= 0 or spot <= 0 or strike <= 0:
        return None
    if token_price <= 0.01 or token_price >= 0.99:
        return None  # Deep ITM/OTM: BS inversion is unreliable

    def bs_digital(sigma):
        d2 = (math.log(spot / strike) - 0.5 * sigma**2 * T) / (
            sigma * math.sqrt(T)
        )
        return _norm_cdf(d2) - token_price

    try:
        return _brentq(bs_digital, 0.01, 1000.0, xtol=1e-4, maxiter=100)
    except (ValueError, RuntimeError):
        return None
