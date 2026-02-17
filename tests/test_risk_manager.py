"""
Unit Tests for Risk Management
Run with: python -m pytest tests/test_risk_manager.py -v
"""

import pytest
import os
from datetime import datetime

# Ensure we can import from parent
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.risk import (
    RiskManager,
    RiskConfig,
    PortfolioState,
    Position,
    RiskBlockReason
)


class TestRiskConfig:
    """Test RiskConfig validation"""
    
    def test_default_values(self):
        """Test default config values"""
        config = RiskConfig()
        assert config.max_risk_pct_per_trade == 2.0
        assert config.max_total_exposure_pct == 15.0
        assert config.daily_loss_limit_pct == 5.0
        assert config.max_concurrent_positions == 5
        assert config.risk_enabled == True
    
    def test_custom_values_from_env(self, monkeypatch):
        """Test loading from environment variables"""
        monkeypatch.setenv("MAX_RISK_PCT_PER_TRADE", "5.0")
        monkeypatch.setenv("MAX_TOTAL_EXPOSURE_PCT", "25.0")
        monkeypatch.setenv("DAILY_LOSS_LIMIT_PCT", "10.0")
        monkeypatch.setenv("MAX_CONCURRENT_POSITIONS", "10")
        monkeypatch.setenv("RISK_ENABLED", "0")
        
        config = RiskConfig()
        assert config.max_risk_pct_per_trade == 5.0
        assert config.max_total_exposure_pct == 25.0
        assert config.daily_loss_limit_pct == 10.0
        assert config.max_concurrent_positions == 10
        assert config.risk_enabled == False
    
    def test_invalid_values(self):
        """Test validation of invalid values"""
        with pytest.raises(AssertionError):
            RiskConfig(max_risk_pct_per_trade=150)  # > 100
        
        with pytest.raises(AssertionError):
            RiskConfig(max_concurrent_positions=0)  # < 1


class TestPortfolioState:
    """Test PortfolioState calculations"""
    
    def test_empty_portfolio(self):
        """Test empty portfolio state"""
        portfolio = PortfolioState(equity=10000.0)
        assert portfolio.total_exposure == 0.0
        assert portfolio.exposure_pct == 0.0
        assert portfolio.concurrent_positions == 0
        assert portfolio.daily_loss_pct == 0.0
    
    def test_with_positions(self):
        """Test portfolio with positions"""
        positions = [
            Position("m1", "t1", "yes", 0.5, 1000.0),
            Position("m2", "t2", "no", 0.6, 2000.0),
        ]
        portfolio = PortfolioState(
            equity=10000.0,
            positions=positions,
            daily_pnl=-300.0,
            daily_starting_equity=10000.0
        )
        
        assert portfolio.total_exposure == 3000.0
        assert portfolio.exposure_pct == 30.0
        assert portfolio.concurrent_positions == 2
        assert portfolio.daily_loss_pct == 3.0


class TestRiskManagerPositionSizing:
    """Test position sizing logic"""
    
    def test_calculate_position_size_basic(self):
        """Test basic position sizing"""
        config = RiskConfig(max_risk_pct_per_trade=2.0)
        manager = RiskManager(config)
        portfolio = PortfolioState(equity=10000.0)
        
        # High confidence, good edge
        size = manager.calculate_position_size(portfolio, confidence=0.9, edge=50)
        assert 0 < size <= 200.0  # Max 2% of 10000
    
    def test_calculate_position_size_low_confidence(self):
        """Test sizing with low confidence"""
        config = RiskConfig(max_risk_pct_per_trade=2.0)
        manager = RiskManager(config)
        portfolio = PortfolioState(equity=10000.0)
        
        # Low confidence should result in small size
        size = manager.calculate_position_size(portfolio, confidence=0.6, edge=20)
        assert size >= 1.0  # Hard floor
        assert size < 200.0
    
    def test_calculate_position_size_disabled(self):
        """Test legacy behavior when risk disabled"""
        config = RiskConfig(risk_enabled=False)
        manager = RiskManager(config)
        portfolio = PortfolioState(equity=10000.0)
        
        size = manager.calculate_position_size(portfolio, confidence=0.9, edge=100)
        assert size == 5000.0  # 50% legacy cap


class TestRiskManagerTradeChecks:
    """Test trade blocking logic"""
    
    def test_trade_allowed_basic(self):
        """Test basic allowed trade"""
        config = RiskConfig(
            max_risk_pct_per_trade=2.0,
            max_total_exposure_pct=15.0,
            daily_loss_limit_pct=5.0,
            max_concurrent_positions=5,
            max_spread_bps=1000  # Very relaxed for this test
        )
        manager = RiskManager(config)
        portfolio = PortfolioState(equity=10000.0)
        
        allowed, reason, msg = manager.check_trade_allowed(
            portfolio, proposed_size=100.0, entry_price=0.5,
            best_ask=0.51, best_bid=0.49
        )
        
        assert allowed is True
        assert reason is None
    
    def test_trade_blocked_by_daily_loss(self):
        """Test trade blocked by daily loss limit"""
        config = RiskConfig(daily_loss_limit_pct=5.0)
        manager = RiskManager(config)
        portfolio = PortfolioState(
            equity=10000.0,
            daily_pnl=-600.0,  # 6% loss
            daily_starting_equity=10000.0
        )
        
        allowed, reason, msg = manager.check_trade_allowed(
            portfolio, proposed_size=100.0, entry_price=0.5,
            best_ask=0.51, best_bid=0.49
        )
        
        assert allowed is False
        assert reason == RiskBlockReason.DAILY_LOSS_LIMIT
    
    def test_trade_blocked_by_max_positions(self):
        """Test trade blocked by max concurrent positions"""
        config = RiskConfig(max_concurrent_positions=2)
        manager = RiskManager(config)
        
        positions = [
            Position("m1", "t1", "yes", 0.5, 1000.0),
            Position("m2", "t2", "no", 0.6, 1000.0),
        ]
        portfolio = PortfolioState(equity=10000.0, positions=positions)
        
        allowed, reason, msg = manager.check_trade_allowed(
            portfolio, proposed_size=100.0, entry_price=0.5,
            best_ask=0.51, best_bid=0.49
        )
        
        assert allowed is False
        assert reason == RiskBlockReason.MAX_CONCURRENT_POSITIONS
    
    def test_trade_blocked_by_exposure(self):
        """Test trade blocked by max exposure"""
        config = RiskConfig(max_total_exposure_pct=10.0)
        manager = RiskManager(config)
        
        positions = [Position("m1", "t1", "yes", 0.5, 800.0)]  # 8% exposure
        portfolio = PortfolioState(equity=10000.0, positions=positions)
        
        allowed, reason, msg = manager.check_trade_allowed(
            portfolio, proposed_size=500.0, entry_price=0.5,  # Would exceed 10%
            best_ask=0.51, best_bid=0.49
        )
        
        assert allowed is False
        assert reason == RiskBlockReason.MAX_EXPOSURE
    
    def test_trade_blocked_by_spread(self):
        """Test trade blocked by wide spread"""
        config = RiskConfig(max_spread_bps=100)  # 1% max
        manager = RiskManager(config)
        portfolio = PortfolioState(equity=10000.0)
        
        # 5% spread (500 bps)
        allowed, reason, msg = manager.check_trade_allowed(
            portfolio, proposed_size=100.0, entry_price=0.5,
            best_ask=0.525, best_bid=0.475
        )
        
        assert allowed is False
        assert reason == RiskBlockReason.SPREAD_TOO_WIDE


class TestRiskManagerExitChecks:
    """Test exit/stop loss logic"""
    
    def test_no_exit_needed(self):
        """Test position that doesn't need exit"""
        config = RiskConfig(max_slippage_bps=100, max_spread_bps=1000)
        manager = RiskManager(config)
        
        position = Position("m1", "t1", "yes", 0.5, 1000.0)
        should_exit, reason = manager.check_exit_needed(
            position, current_mid_price=0.51,  # Moved in favor
            best_ask=0.52, best_bid=0.50
        )
        
        assert should_exit is False
    
    def test_exit_by_slippage_yes(self):
        """Test exit for YES position that moved against us"""
        config = RiskConfig(max_slippage_bps=100)  # 1%
        manager = RiskManager(config)
        
        position = Position("m1", "t1", "yes", 0.5, 1000.0)
        # Price dropped 2% (200 bps) against us
        should_exit, reason = manager.check_exit_needed(
            position, current_mid_price=0.49,
            best_ask=0.50, best_bid=0.48
        )
        
        assert should_exit is True
        assert "Stop loss" in reason
    
    def test_exit_by_slippage_no(self):
        """Test exit for NO position that moved against us"""
        config = RiskConfig(max_slippage_bps=100)
        manager = RiskManager(config)
        
        position = Position("m1", "t1", "no", 0.5, 1000.0)
        # Price rose 2% against NO position
        should_exit, reason = manager.check_exit_needed(
            position, current_mid_price=0.51,
            best_ask=0.52, best_bid=0.50
        )
        
        assert should_exit is True
        assert "Stop loss" in reason
    
    def test_exit_by_wide_spread(self):
        """Test exit when spread becomes too wide"""
        config = RiskConfig(max_spread_bps=100)
        manager = RiskManager(config)
        
        position = Position("m1", "t1", "yes", 0.5, 1000.0)
        should_exit, reason = manager.check_exit_needed(
            position, current_mid_price=0.50,
            best_ask=0.55, best_bid=0.45  # 10% spread
        )
        
        assert should_exit is True
        assert "Spread too wide" in reason


class TestRiskManagerTelemetry:
    """Test telemetry/logging features"""
    
    def test_blocked_trades_logged(self):
        """Test that blocked trades are logged"""
        config = RiskConfig(max_concurrent_positions=1)
        manager = RiskManager(config)
        
        positions = [Position("m1", "t1", "yes", 0.5, 1000.0)]
        portfolio = PortfolioState(equity=10000.0, positions=positions)
        
        # Block a trade
        manager.check_trade_allowed(
            portfolio, proposed_size=100.0, entry_price=0.5,
            best_ask=0.51, best_bid=0.49
        )
        
        blocked = manager.get_blocked_trades()
        assert len(blocked) == 1
        assert blocked[0]["reason"] == RiskBlockReason.MAX_CONCURRENT_POSITIONS.value
    
    def test_reset_daily_stats(self):
        """Test daily stats reset"""
        config = RiskConfig(max_concurrent_positions=1)
        manager = RiskManager(config)
        
        positions = [Position("m1", "t1", "yes", 0.5, 1000.0)]
        portfolio = PortfolioState(equity=10000.0, positions=positions)
        
        manager.check_trade_allowed(
            portfolio, proposed_size=100.0, entry_price=0.5,
            best_ask=0.51, best_bid=0.49
        )
        
        assert len(manager.get_blocked_trades()) == 1
        
        manager.reset_daily_stats(10000.0)
        assert len(manager.get_blocked_trades()) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
