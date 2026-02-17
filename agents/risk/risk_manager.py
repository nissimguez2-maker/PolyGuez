"""
Risk Management Models and Helpers for Polymarket Trading Bot
Block A: Risk Management - Step 1
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from enum import Enum
import os


class RiskBlockReason(Enum):
    """Reasons why a trade was blocked by risk management"""
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    MAX_EXPOSURE = "max_exposure"
    MAX_POSITION_SIZE = "max_position_size"
    MAX_CONCURRENT_POSITIONS = "max_concurrent_positions"
    SPREAD_TOO_WIDE = "spread_too_wide"
    PRICE_SLIPPAGE = "price_slippage"


@dataclass
class RiskConfig:
    """Configuration for risk management - loaded from ENV"""
    # Position Sizing
    max_risk_pct_per_trade: float = field(default_factory=lambda: float(os.getenv("MAX_RISK_PCT_PER_TRADE", "2.0")))
    max_total_exposure_pct: float = field(default_factory=lambda: float(os.getenv("MAX_TOTAL_EXPOSURE_PCT", "15.0")))
    
    # Hard Guardrails
    daily_loss_limit_pct: float = field(default_factory=lambda: float(os.getenv("DAILY_LOSS_LIMIT_PCT", "5.0")))
    max_concurrent_positions: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_POSITIONS", "5")))
    
    # Fast Exit / Stop
    max_slippage_bps: int = field(default_factory=lambda: int(os.getenv("MAX_SLIPPAGE_BPS", "100")))  # 1%
    max_spread_bps: int = field(default_factory=lambda: int(os.getenv("MAX_SPREAD_BPS", "200")))  # 2%
    
    # Feature Flags
    risk_enabled: bool = field(default_factory=lambda: os.getenv("RISK_ENABLED", "1") == "1")
    
    def __post_init__(self):
        """Validate config values"""
        assert 0 < self.max_risk_pct_per_trade <= 100, "max_risk_pct_per_trade must be 0-100"
        assert 0 < self.max_total_exposure_pct <= 100, "max_total_exposure_pct must be 0-100"
        assert 0 < self.daily_loss_limit_pct <= 100, "daily_loss_limit_pct must be 0-100"
        assert self.max_concurrent_positions >= 1, "max_concurrent_positions must be >= 1"


@dataclass
class Position:
    """Simplified position representation"""
    market_id: str
    token_id: str
    side: str  # "yes" or "no"
    entry_price: float
    size: float  # in USDC
    entry_time: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def exposure(self) -> float:
        """Dollar exposure of position"""
        return self.size


@dataclass
class PortfolioState:
    """Current portfolio state for risk calculations"""
    equity: float  # Total USDC balance
    positions: List[Position] = field(default_factory=list)
    daily_pnl: float = 0.0  # Today's realized P&L
    daily_starting_equity: float = 0.0
    
    @property
    def total_exposure(self) -> float:
        """Total dollar exposure across all positions"""
        return sum(p.exposure for p in self.positions)
    
    @property
    def exposure_pct(self) -> float:
        """Exposure as percentage of equity"""
        if self.equity <= 0:
            return 0.0
        return (self.total_exposure / self.equity) * 100
    
    @property
    def daily_loss_pct(self) -> float:
        """Daily loss as percentage of starting equity"""
        if self.daily_starting_equity <= 0:
            return 0.0
        return abs(min(0, self.daily_pnl)) / self.daily_starting_equity * 100
    
    @property
    def concurrent_positions(self) -> int:
        """Number of open positions"""
        return len(self.positions)


class RiskManager:
    """Main risk management class"""
    
    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self._blocked_trades: List[Dict] = []  # For telemetry
    
    def check_trade_allowed(
        self,
        portfolio: PortfolioState,
        proposed_size: float,
        entry_price: float,
        best_ask: float,
        best_bid: float
    ) -> tuple[bool, Optional[RiskBlockReason], Optional[str]]:
        """
        Check if a trade is allowed under risk rules
        
        Returns: (allowed, reason, message)
        """
        if not self.config.risk_enabled:
            return True, None, None
        
        # 1. Check daily loss limit
        if portfolio.daily_loss_pct >= self.config.daily_loss_limit_pct:
            msg = f"Daily loss limit hit: {portfolio.daily_loss_pct:.2f}% >= {self.config.daily_loss_limit_pct}%"
            self._log_blocked_trade(RiskBlockReason.DAILY_LOSS_LIMIT, msg)
            return False, RiskBlockReason.DAILY_LOSS_LIMIT, msg
        
        # 2. Check max concurrent positions
        if portfolio.concurrent_positions >= self.config.max_concurrent_positions:
            msg = f"Max positions reached: {portfolio.concurrent_positions} >= {self.config.max_concurrent_positions}"
            self._log_blocked_trade(RiskBlockReason.MAX_CONCURRENT_POSITIONS, msg)
            return False, RiskBlockReason.MAX_CONCURRENT_POSITIONS, msg
        
        # 3. Check max exposure
        if portfolio.equity <= 0:
            msg = f"Invalid equity: ${portfolio.equity:.2f}"
            self._log_blocked_trade(RiskBlockReason.MAX_EXPOSURE, msg)
            return False, RiskBlockReason.MAX_EXPOSURE, msg
        
        new_exposure_pct = ((portfolio.total_exposure + proposed_size) / portfolio.equity) * 100
        if new_exposure_pct > self.config.max_total_exposure_pct:
            msg = f"Max exposure would be exceeded: {new_exposure_pct:.2f}% > {self.config.max_total_exposure_pct}%"
            self._log_blocked_trade(RiskBlockReason.MAX_EXPOSURE, msg)
            return False, RiskBlockReason.MAX_EXPOSURE, msg
        
        # 4. Check position size (max risk per trade)
        if portfolio.equity <= 0:
            msg = f"Invalid equity: ${portfolio.equity:.2f}"
            self._log_blocked_trade(RiskBlockReason.MAX_POSITION_SIZE, msg)
            return False, RiskBlockReason.MAX_POSITION_SIZE, msg
        
        position_risk_pct = (proposed_size / portfolio.equity) * 100
        if position_risk_pct > self.config.max_risk_pct_per_trade:
            msg = f"Position size too large: {position_risk_pct:.2f}% > {self.config.max_risk_pct_per_trade}%"
            self._log_blocked_trade(RiskBlockReason.MAX_POSITION_SIZE, msg)
            return False, RiskBlockReason.MAX_POSITION_SIZE, msg
        
        # 5. Check spread
        if best_ask > 0 and best_bid > 0:
            mid = (best_ask + best_bid) / 2
            spread_bps = ((best_ask - best_bid) / mid) * 10000
            if spread_bps > self.config.max_spread_bps:
                msg = f"Spread too wide: {spread_bps:.0f} bps > {self.config.max_spread_bps} bps"
                self._log_blocked_trade(RiskBlockReason.SPREAD_TOO_WIDE, msg)
                return False, RiskBlockReason.SPREAD_TOO_WIDE, msg
        
        return True, None, None
    
    def check_exit_needed(
        self,
        position: Position,
        current_mid_price: float,
        best_ask: float,
        best_bid: float
    ) -> tuple[bool, Optional[str]]:
        """
        Check if position should be exited (lightweight stop)
        
        Returns: (should_exit, reason)
        """
        if not self.config.risk_enabled:
            return False, None
        
        # Check slippage from entry
        if position.entry_price > 0:
            slippage_bps = abs(current_mid_price - position.entry_price) / position.entry_price * 10000
            
            # Exit if price moved against us too much
            if position.side == "yes" and current_mid_price < position.entry_price:
                if slippage_bps > self.config.max_slippage_bps:
                    return True, f"Stop loss: {slippage_bps:.0f} bps against entry"
            
            elif position.side == "no" and current_mid_price > position.entry_price:
                if slippage_bps > self.config.max_slippage_bps:
                    return True, f"Stop loss: {slippage_bps:.0f} bps against entry"
        
        # Check spread
        if best_ask > 0 and best_bid > 0:
            mid = (best_ask + best_bid) / 2
            spread_bps = ((best_ask - best_bid) / mid) * 10000
            if spread_bps > self.config.max_spread_bps:
                return True, f"Spread too wide: {spread_bps:.0f} bps"
        
        return False, None
    
    def calculate_position_size(
        self,
        portfolio: PortfolioState,
        confidence: float,  # 0.0 to 1.0 from LLM
        edge: float  # expected edge in bps
    ) -> float:
        """
        Calculate appropriate position size based on Kelly Criterion (simplified)
        
        Returns: size in USDC
        """
        if not self.config.risk_enabled:
            # Legacy behavior - cap at 50% for safety
            return portfolio.equity * 0.5
        
        # Base size: max risk per trade
        max_size = portfolio.equity * (self.config.max_risk_pct_per_trade / 100)
        
        # Scale by confidence (0.5 = neutral, 1.0 = max confidence)
        confidence_multiplier = max(0, (confidence - 0.5) * 2)  # 0 to 1
        
        # Scale by edge (more edge = bigger size, up to limit)
        edge_factor = min(1.0, edge / 100)  # Cap at 100 bps edge
        
        # Combined sizing
        size = max_size * confidence_multiplier * edge_factor
        
        # Hard floor/ceiling
        size = max(1.0, min(size, max_size))  # At least $1, at most max_size
        
        return size
    
    def _log_blocked_trade(self, reason: RiskBlockReason, message: str):
        """Log blocked trade for telemetry"""
        self._blocked_trades.append({
            "timestamp": datetime.utcnow().isoformat(),
            "reason": reason.value,
            "message": message
        })
    
    def get_blocked_trades(self) -> List[Dict]:
        """Get list of blocked trades (for metrics)"""
        return self._blocked_trades.copy()
    
    def reset_daily_stats(self, starting_equity: float):
        """Reset daily statistics (call at start of trading day)"""
        self._blocked_trades = []


# Singleton instance for easy import
_risk_manager: Optional[RiskManager] = None

def get_risk_manager() -> RiskManager:
    """Get or create singleton risk manager instance"""
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager()
    return _risk_manager
