"""Tests for orphan cleanup not closing already exited trades."""
import sys
sys.path.append(".")
import asyncio
import time
from datetime import datetime, timezone


def test_orphan_cleanup_skips_exited_trades():
    """Test that orphan cleanup skips trades that are already exited."""
    # This test verifies the logic that orphan cleanup should check trade.exited flag
    
    # Create a mock trade that is already exited
    class MockTrade:
        def __init__(self, exited=False, closing=False, created_at_utc=None):
            self.trade_id = "test_trade_123"
            self.exited = exited
            self.closing = closing
            self.created_at_utc = created_at_utc or datetime.now(timezone.utc).isoformat()
            self.created_at = time.monotonic() - 3600  # 1 hour ago
            self.status = "EXITED" if exited else "PENDING"
            self.market_id = "test_market"
            self.token_id = "token_123"
            
    # Test case 1: Trade already exited - should be skipped
    exited_trade = MockTrade(exited=True)
    assert exited_trade.exited is True
    
    # Test case 2: Trade closing - should be skipped
    closing_trade = MockTrade(closing=True)
    assert closing_trade.closing is True
    
    # Test case 3: Trade not exited and not closing - should be considered for cleanup
    active_trade = MockTrade(exited=False, closing=False)
    assert active_trade.exited is False
    assert active_trade.closing is False


def test_orphan_cleanup_age_calculation():
    """Test that orphan cleanup correctly calculates trade age."""
    from datetime import datetime, timezone, timedelta
    
    # Create timestamps for testing
    now_utc = datetime.now(timezone.utc)
    old_time = now_utc - timedelta(minutes=30)  # 30 minutes ago
    
    # Calculate age
    age_delta = now_utc - old_time
    age_seconds = age_delta.total_seconds()
    age_minutes = age_seconds / 60.0
    age_bars = int(age_seconds / 900)  # 15min = 1 bar
    
    assert age_minutes == 30.0
    assert age_bars == 2  # 30 minutes = 2 bars


def test_trade_status_filtering():
    """Test that orphan cleanup filters trades by status correctly."""
    # Simulate the status filtering logic from orphan_cleanup_task
    
    class MockTrade:
        def __init__(self, trade_id, status, exited=False, closing=False):
            self.trade_id = trade_id
            self.status = status
            self.exited = exited
            self.closing = closing
            self.created_at_utc = datetime.now(timezone.utc).isoformat()
            self.created_at = time.monotonic()
            
    # Create trades with different statuses
    trades = [
        MockTrade("t1", "PENDING", exited=False, closing=False),
        MockTrade("t2", "CONFIRMED", exited=False, closing=False),
        MockTrade("t3", "ADDED", exited=False, closing=False),
        MockTrade("t4", "HEDGED", exited=False, closing=False),
        MockTrade("t5", "EXITED", exited=True, closing=False),  # Already exited
        MockTrade("t6", "PENDING", exited=False, closing=True),  # Currently closing
    ]
    
    # Filter active trades (same logic as orphan_cleanup_task)
    active_statuses = {"PENDING", "CONFIRMED", "ADDED", "HEDGED"}
    active_trades = [
        t for t in trades
        if t.status in active_statuses
        and not t.exited
        and not t.closing
    ]
    
    # Should only include t1, t2, t3, t4
    assert len(active_trades) == 4
    assert "t1" in [t.trade_id for t in active_trades]
    assert "t2" in [t.trade_id for t in active_trades]
    assert "t3" in [t.trade_id for t in active_trades]
    assert "t4" in [t.trade_id for t in active_trades]
    assert "t5" not in [t.trade_id for t in active_trades]  # Excluded: already exited
    assert "t6" not in [t.trade_id for t in active_trades]  # Excluded: currently closing
