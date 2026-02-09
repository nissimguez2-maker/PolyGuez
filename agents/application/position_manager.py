"""
Position Manager for Fast Entry Engine + TradingView Integration.

Manages:
- Trade ID generation and correlation
- Position locks per market
- Timeout/cooldown handling
- Idempotency for confirmation actions
- State persistence
"""
import time
import uuid
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Set, List, Any
from enum import Enum
from datetime import datetime, timezone
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradeAction(str, Enum):
    """Confirmation actions from TradingView."""
    ADD = "ADD"  # Add size / nachkaufen
    HEDGE = "HEDGE"  # Hedge position
    EXIT = "EXIT"  # Close position


class TradeStatus(str, Enum):
    """Trade status."""
    PENDING = "PENDING"  # Leg 1 filled, waiting for confirmation
    CONFIRMED = "CONFIRMED"  # Confirmation received
    ADDED = "ADDED"  # Size added
    HEDGED = "HEDGED"  # Position hedged
    EXITED = "EXITED"  # Position closed
    TIMEOUT = "TIMEOUT"  # Confirmation timeout
    FAILED = "FAILED"  # Execution failed


@dataclass
class ActiveTrade:
    """Active trade state."""
    trade_id: str
    market_id: str
    token_id: str
    side: str  # "UP" or "DOWN"
    leg1_size: float
    leg1_price: float
    leg1_entry_id: str
    created_at: float  # Monotonic timestamp
    created_at_utc: str  # UTC ISO string
    status: TradeStatus = TradeStatus.PENDING
    confirmation_timeout_seconds: int = 30  # Default 30s timeout
    # Confirmation tracking
    confirmation_received: bool = False
    confirmation_at: Optional[float] = None
    # Idempotency
    processed_actions: Set[str] = field(default_factory=set)  # Set of action IDs
    # Additional size tracking
    total_size: float = 0.0  # Cumulative size
    hedged: bool = False
    exited: bool = False
    # PnL tracking (dry run)
    current_price: Optional[float] = None  # Current market price
    entry_price: float = 0.0  # Average entry price
    unrealized_pnl: float = 0.0  # Unrealized PnL
    realized_pnl: float = 0.0  # Realized PnL (on exit)
    # MAE/MFE tracking (for Soft-Stop validation)
    mae: float = 0.0  # Maximum Adverse Excursion (worst unrealized PnL, always <= 0)
    mfe: float = 0.0  # Maximum Favorable Excursion (best unrealized PnL, always >= 0)
    # Latency metrics
    detect_to_send_ms: Optional[float] = None
    send_to_ack_ms: Optional[float] = None
    detect_to_ack_ms: Optional[float] = None
    # Exit tracking
    exit_reason: Optional[str] = None  # Exit reason (soft_stop, time_stop, manual, etc.)
    exit_price: Optional[float] = None  # Exit price
    exit_at: Optional[float] = None  # Exit timestamp (monotonic)
    exit_at_utc: Optional[str] = None  # Exit timestamp (UTC ISO)
    bars_elapsed: int = 0  # Number of bars elapsed since entry
    closing: bool = False  # Flag to prevent multiple exit requests (set on first exit attempt)
    exit_request_id: Optional[str] = None  # Exit request ID for idempotency


class PositionManager:
    """
    Manages active positions and confirmation flow.
    
    Features:
    - Trade ID generation
    - Position locks per market
    - Timeout handling
    - Idempotency
    - State persistence
    """
    
    def __init__(self, default_timeout_seconds: int = 30, state_file: Optional[str] = None):
        self.default_timeout_seconds = default_timeout_seconds
        self.state_file = state_file or "position_state.json"
        self.active_trades: Dict[str, ActiveTrade] = {}  # trade_id -> ActiveTrade
        self.market_locks: Dict[str, str] = {}  # market_id -> trade_id (only one active per market)
        self.action_idempotency: Dict[str, float] = {}  # action_id -> timestamp (for TTL cleanup)
        self.action_cooldowns: Dict[str, float] = {}  # action_id -> last_execution_time
        self.action_cooldown_seconds = 2.0  # Minimum 2s between actions
        self.idempotency_ttl_seconds = 3600  # Keep idempotency records for 1 hour
        
        # State persistence debouncing
        self._save_pending = False
        self._last_save_time = 0.0
        self._save_debounce_seconds = 1.0  # Save at most once per second
        
        # Load state if exists
        self._load_state()
    
    def _load_state(self) -> None:
        """Load state from disk."""
        if not Path(self.state_file).exists():
            return
        
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
            
            # Restore market locks
            self.market_locks = data.get("market_locks", {})
            
            logger.info(f"Loaded state: {len(self.market_locks)} market locks")
        except Exception as e:
            logger.error(f"Error loading state: {e}")
    
    def _save_state(self, force: bool = False) -> None:
        """
        Save minimal state to disk (debounced to avoid I/O bottleneck).
        
        Args:
            force: If True, save immediately. Otherwise, debounce.
        """
        now = time.monotonic()
        self._save_pending = True
        
        # Debounce: only save if enough time has passed or forced
        if force or (now - self._last_save_time) >= self._save_debounce_seconds:
            try:
                state = {
                    "market_locks": self.market_locks,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                with open(self.state_file, "w") as f:
                    json.dump(state, f, indent=2)
                self._last_save_time = now
                self._save_pending = False
                logger.debug(f"State saved to {self.state_file} (force={force})")
            except Exception as e:
                logger.error(f"Error saving state: {e}")
                self._save_pending = False
        else:
            # Debounced - save will happen later
            elapsed = now - self._last_save_time
            logger.debug(f"State save debounced (elapsed={elapsed:.3f}s, pending=True)")
    
    def generate_trade_id(self) -> str:
        """Generate unique trade ID."""
        return f"trade_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    
    def create_trade(
        self,
        market_id: str,
        token_id: str,
        side: str,
        leg1_size: float,
        leg1_price: float,
        leg1_entry_id: str,
        timeout_seconds: Optional[int] = None,
    ) -> Optional[ActiveTrade]:
        """
        Create new active trade with position lock.
        
        Returns None if market is already locked.
        """
        # Check if market is already locked
        if market_id in self.market_locks:
            existing_trade_id = self.market_locks[market_id]
            existing_trade = self.active_trades.get(existing_trade_id)
            if existing_trade and existing_trade.status == TradeStatus.PENDING:
                logger.warning(
                    f"Market {market_id} already locked by trade {existing_trade_id}"
                )
                return None
        
        # HARD INVARIANT: leg1_price MUST be valid (not None) before creating trade
        if leg1_price is None:
            logger.error(
                f"PositionManager.create_trade: leg1_price is None for market {market_id}. "
                f"Trade will NOT be created. This indicates a race condition or missing price fetch."
            )
            return None
        
        # Validate leg1_price is a valid float
        # Polymarket prices are in range [0.0, 1.0] inclusive (extreme market states allowed)
        try:
            leg1_price_float = float(leg1_price)
            if leg1_price_float < 0 or leg1_price_float > 1:
                logger.error(
                    f"PositionManager.create_trade: Invalid leg1_price={leg1_price} for market {market_id}. "
                    f"Price must be in [0.0, 1.0]. Trade will NOT be created."
                )
                return None
        except (ValueError, TypeError):
            logger.error(
                f"PositionManager.create_trade: leg1_price={leg1_price} is not a valid float for market {market_id}. "
                f"Trade will NOT be created."
            )
            return None
        
        # Generate trade ID
        trade_id = self.generate_trade_id()
        
        # Create trade (leg1_price is guaranteed to be valid at this point)
        trade = ActiveTrade(
            trade_id=trade_id,
            market_id=market_id,
            token_id=token_id,
            side=side,
            leg1_size=leg1_size,
            leg1_price=leg1_price_float,  # Use validated float
            leg1_entry_id=leg1_entry_id,
            created_at=time.monotonic(),
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            confirmation_timeout_seconds=timeout_seconds or self.default_timeout_seconds,
            total_size=leg1_size,
            entry_price=leg1_price_float,  # Initial entry price (guaranteed valid)
        )
        
        # Lock market
        self.market_locks[market_id] = trade_id
        self.active_trades[trade_id] = trade
        
        # Save state (force immediate save for new trades)
        self._save_state(force=True)
        
        logger.info(
            f"Created trade {trade_id} for market {market_id} "
            f"(side={side}, size={leg1_size}, entry_price={leg1_price_float:.6f}, timeout={trade.confirmation_timeout_seconds}s)"
        )
        
        return trade
    
    def get_trade(self, trade_id: str) -> Optional[ActiveTrade]:
        """Get active trade by ID."""
        return self.active_trades.get(trade_id)
    
    def get_trade_by_market(self, market_id: str) -> Optional[ActiveTrade]:
        """Get active trade for market."""
        trade_id = self.market_locks.get(market_id)
        if trade_id:
            return self.active_trades.get(trade_id)
        return None
    
    def check_timeout(self, trade_id: str) -> bool:
        """Check if trade has timed out."""
        trade = self.active_trades.get(trade_id)
        if not trade:
            return False
        
        if trade.status != TradeStatus.PENDING:
            return False  # Already processed
        
        elapsed = time.monotonic() - trade.created_at
        if elapsed > trade.confirmation_timeout_seconds:
            trade.status = TradeStatus.TIMEOUT
            logger.warning(
                f"Trade {trade_id} timed out after {elapsed:.1f}s "
                f"(timeout={trade.confirmation_timeout_seconds}s)"
            )
            return True
        
        return False
    
    def check_idempotency(self, action_id: str) -> bool:
        """
        Check if action was already processed (idempotency).
        
        Returns True if already processed, False if new.
        Automatically cleans up old entries (TTL-based).
        """
        # Cleanup old entries first
        self._cleanup_old_idempotency()
        
        if action_id in self.action_idempotency:
            return True
        return False
    
    def _cleanup_old_idempotency(self) -> None:
        """Remove idempotency entries older than TTL."""
        now = time.monotonic()
        cutoff = now - self.idempotency_ttl_seconds
        
        # Remove old entries
        expired = [
            action_id for action_id, timestamp in self.action_idempotency.items()
            if timestamp < cutoff
        ]
        for action_id in expired:
            del self.action_idempotency[action_id]
        
        # Also cleanup old cooldowns (keep only last hour)
        expired_cooldowns = [
            action_id for action_id, timestamp in self.action_cooldowns.items()
            if timestamp < cutoff
        ]
        for action_id in expired_cooldowns:
            del self.action_cooldowns[action_id]
        
        if expired or expired_cooldowns:
            logger.debug(f"Cleaned up {len(expired)} idempotency + {len(expired_cooldowns)} cooldown entries")
    
    def check_cooldown(self, action_id: str) -> bool:
        """
        Check if action is in cooldown period.
        
        Returns True if in cooldown, False if allowed.
        """
        if action_id not in self.action_cooldowns:
            return False
        
        elapsed = time.monotonic() - self.action_cooldowns[action_id]
        if elapsed < self.action_cooldown_seconds:
            return True
        return False
    
    def mark_action_processed(self, action_id: str) -> None:
        """Mark action as processed and update cooldown."""
        now = time.monotonic()
        self.action_idempotency[action_id] = now  # Store timestamp for TTL cleanup
        self.action_cooldowns[action_id] = now
    
    def process_confirmation(
        self,
        trade_id: str,
        action: TradeAction,
        action_id: str,
        additional_size: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Process confirmation action from TradingView.
        
        Returns:
            {
                "ok": bool,
                "trade_id": str,
                "action": str,
                "status": str,
                "message": str,
                "already_handled": bool,
            }
        """
        # Check idempotency FIRST (has highest priority)
        if self.check_idempotency(action_id):
            logger.info(f"Action {action_id} already processed (idempotency)")
            return {
                "ok": True,
                "trade_id": trade_id,
                "action": action.value,
                "status": "already_handled",
                "message": "Action already processed",
                "already_handled": True,
            }
        
        # Get trade
        trade = self.get_trade(trade_id)
        if not trade:
            return {
                "ok": False,
                "trade_id": trade_id,
                "action": action.value,
                "status": "not_found",
                "message": f"Trade {trade_id} not found",
                "already_handled": False,
            }
        
        # Check timeout
        if self.check_timeout(trade_id):
            return {
                "ok": False,
                "trade_id": trade_id,
                "action": action.value,
                "status": "timeout",
                "message": f"Trade {trade_id} timed out",
                "already_handled": False,
            }
        
        # Check if trade status allows this action
        # For ADD: only allow if status is PENDING or ADDED (can add more size)
        # For HEDGE/EXIT: only allow if status is PENDING, ADDED, or HEDGED
        if action == TradeAction.ADD:
            if trade.status not in (TradeStatus.PENDING, TradeStatus.ADDED):
                return {
                    "ok": False,
                    "trade_id": trade_id,
                    "action": action.value,
                    "status": trade.status.value,
                    "message": f"Trade {trade_id} in status {trade.status.value}, cannot ADD",
                    "already_handled": False,
                }
        elif action == TradeAction.HEDGE:
            if trade.status not in (TradeStatus.PENDING, TradeStatus.ADDED, TradeStatus.HEDGED):
                return {
                    "ok": False,
                    "trade_id": trade_id,
                    "action": action.value,
                    "status": trade.status.value,
                    "message": f"Trade {trade_id} in status {trade.status.value}, cannot HEDGE",
                    "already_handled": False,
                }
        elif action == TradeAction.EXIT:
            if trade.status in (TradeStatus.EXITED, TradeStatus.TIMEOUT, TradeStatus.FAILED):
                return {
                    "ok": False,
                    "trade_id": trade_id,
                    "action": action.value,
                    "status": trade.status.value,
                    "message": f"Trade {trade_id} in status {trade.status.value}, cannot EXIT",
                    "already_handled": False,
                }
        
        # Process action
        trade.confirmation_received = True
        trade.confirmation_at = time.monotonic()
        trade.processed_actions.add(action_id)
        
        if action == TradeAction.ADD:
            if additional_size is None:
                return {
                    "ok": False,
                    "trade_id": trade_id,
                    "action": action.value,
                    "status": "invalid",
                    "message": "ADD action requires additional_size",
                    "already_handled": False,
                }
            # Update average entry price (weighted average)
            old_total = trade.total_size
            trade.total_size += additional_size
            # Weighted average: (old_total * old_price + new_size * new_price) / total
            # For simplicity, assume same price (can be enhanced)
            trade.entry_price = (old_total * trade.entry_price + additional_size * trade.leg1_price) / trade.total_size
            trade.status = TradeStatus.ADDED
            logger.info(
                f"Trade {trade_id}: ADD {additional_size} (total={trade.total_size}, avg_price={trade.entry_price:.6f})"
            )
        
        elif action == TradeAction.HEDGE:
            trade.hedged = True
            trade.status = TradeStatus.HEDGED
            logger.info(f"Trade {trade_id}: HEDGE")
        
        elif action == TradeAction.EXIT:
            # Idempotent exit: check if already exited
            if trade.exited:
                logger.info(f"Trade {trade_id}: EXIT already processed (idempotent)")
                return {
                    "ok": True,
                    "trade_id": trade_id,
                    "action": action.value,
                    "status": trade.status.value,
                    "message": "Exit already processed",
                    "already_handled": True,
                }
            
            trade.exited = True
            trade.status = TradeStatus.EXITED
            trade.exit_at = time.monotonic()
            trade.exit_at_utc = datetime.now(timezone.utc).isoformat()
            # Exit price will be set by caller if available
            # Exit reason will be set by caller if available
            
            # Release market lock
            if trade.market_id in self.market_locks:
                del self.market_locks[trade.market_id]
            logger.info(f"Trade {trade_id}: EXIT (reason={trade.exit_reason})")
        
        # Mark action as processed
        self.mark_action_processed(action_id)
        
        # Save state (debounced)
        self._save_state(force=False)
        
        return {
            "ok": True,
            "trade_id": trade_id,
            "action": action.value,
            "status": trade.status.value,
            "message": f"Action {action.value} processed",
            "already_handled": False,
            "total_size": trade.total_size if action == TradeAction.ADD else None,
            "unrealized_pnl": trade.unrealized_pnl,
            "realized_pnl": trade.realized_pnl,
        }
    
    def cleanup_timeout_trades(self) -> int:
        """
        Clean up timed out trades.
        
        Returns number of trades cleaned up.
        """
        cleaned = 0
        for trade_id, trade in list(self.active_trades.items()):
            if self.check_timeout(trade_id):
                # Release market lock
                if trade.market_id in self.market_locks:
                    del self.market_locks[trade.market_id]
                cleaned += 1
        return cleaned
    
    def update_pnl(self, trade_id: str, current_price: float) -> None:
        """
        Update PnL for a trade (dry run).
        Also tracks MAE (Maximum Adverse Excursion) and MFE (Maximum Favorable Excursion).
        """
        trade = self.active_trades.get(trade_id)
        if not trade or trade.exited:
            return
        
        trade.current_price = current_price
        
        # Calculate unrealized PnL
        # For UP: profit if price goes up
        # For DOWN: profit if price goes down
        if trade.side == "UP":
            # Long position: profit = (current - entry) * size
            trade.unrealized_pnl = (current_price - trade.entry_price) * trade.total_size
        else:  # DOWN
            # Short position: profit = (entry - current) * size
            trade.unrealized_pnl = (trade.entry_price - current_price) * trade.total_size
        
        # Update MAE (Maximum Adverse Excursion) - worst unrealized PnL
        # MAE is always <= 0 (most negative)
        if trade.unrealized_pnl < trade.mae:
            trade.mae = trade.unrealized_pnl
        
        # Update MFE (Maximum Favorable Excursion) - best unrealized PnL
        # MFE is always >= 0 (most positive)
        if trade.unrealized_pnl > trade.mfe:
            trade.mfe = trade.unrealized_pnl
    
    def get_active_trades_summary(self) -> List[Dict[str, Any]]:
        """Get summary of all active trades."""
        summary = []
        for trade_id, trade in self.active_trades.items():
            if trade.status in (TradeStatus.PENDING, TradeStatus.ADDED, TradeStatus.HEDGED):
                summary.append({
                    "trade_id": trade_id,
                    "market_id": trade.market_id,
                    "token_id": trade.token_id,
                    "side": trade.side,
                    "status": trade.status.value,
                    "total_size": trade.total_size,
                    "entry_price": trade.entry_price,
                    "current_price": trade.current_price,
                    "unrealized_pnl": trade.unrealized_pnl,
                    "realized_pnl": trade.realized_pnl,
                    "created_at_utc": trade.created_at_utc,
                })
        return summary
    
    def get_total_pnl(self) -> Dict[str, float]:
        """Get total PnL across all trades."""
        total_unrealized = sum(
            t.unrealized_pnl for t in self.active_trades.values()
            if t.status in (TradeStatus.PENDING, TradeStatus.ADDED, TradeStatus.HEDGED)
        )
        total_realized = sum(
            t.realized_pnl for t in self.active_trades.values()
            if t.status == TradeStatus.EXITED
        )
        return {
            "unrealized_pnl": total_unrealized,
            "realized_pnl": total_realized,
            "total_pnl": total_unrealized + total_realized,
        }
    
    def exit_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str,
        exit_request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Exit a trade with idempotency protection.
        
        Args:
            trade_id: Trade ID to exit
            exit_price: Exit price
            exit_reason: Exit reason (soft_stop, time_stop, manual, etc.)
            exit_request_id: Optional request ID for idempotency
        
        Returns:
            Result dict with ok flag and details
        """
        trade = self.get_trade(trade_id)
        if not trade:
            return {
                "ok": False,
                "trade_id": trade_id,
                "error": "not_found",
                "message": f"Trade {trade_id} not found",
            }
        
        # Check if already exited
        if trade.exited:
            return {
                "ok": True,
                "trade_id": trade_id,
                "status": "already_exited",
                "message": "Trade already exited",
                "already_handled": True,
            }
        
        # Check if already closing (prevent multiple exit requests)
        if trade.closing:
            logger.info(f"Trade {trade_id} already closing (exit_request_id={trade.exit_request_id}), skipping duplicate exit request")
            return {
                "ok": True,
                "trade_id": trade_id,
                "status": "already_closing",
                "message": "Trade already closing",
                "already_handled": True,
                "exit_request_id": trade.exit_request_id,
            }
        
        # Set closing flag immediately to prevent duplicate exit requests
        trade.closing = True
        if exit_request_id:
            trade.exit_request_id = exit_request_id
            # Check idempotency if exit_request_id provided
            if self.check_idempotency(exit_request_id):
                logger.info(f"Exit request {exit_request_id} already processed (idempotent)")
                return {
                    "ok": True,
                    "trade_id": trade_id,
                    "status": "already_exited",
                    "message": "Exit already processed",
                    "already_handled": True,
                }
            self.mark_action_processed(exit_request_id)
        else:
            # Generate exit_request_id if not provided
            trade.exit_request_id = f"exit_{trade_id}_{int(time.time() * 1000)}"
            exit_request_id = trade.exit_request_id
        
        # Calculate realized PnL
        if trade.side == "UP":
            realized_pnl = (exit_price - trade.entry_price) * trade.total_size
        else:  # DOWN
            realized_pnl = (trade.entry_price - exit_price) * trade.total_size
        
        # Update trade (closing flag already set above)
        trade.exited = True
        trade.status = TradeStatus.EXITED
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.exit_at = time.monotonic()
        trade.exit_at_utc = datetime.now(timezone.utc).isoformat()
        trade.realized_pnl = realized_pnl
        
        # Release market lock
        if trade.market_id in self.market_locks:
            del self.market_locks[trade.market_id]
        
        logger.info(
            f"Trade {trade_id}: EXIT at {exit_price:.6f} "
            f"(reason={exit_reason}, realized_pnl={realized_pnl:.2f}, exit_request_id={exit_request_id})"
        )
        
        # Save state
        self._save_state(force=False)
        
        return {
            "ok": True,
            "trade_id": trade_id,
            "status": "exited",
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "realized_pnl": realized_pnl,
            "exit_request_id": exit_request_id,
            "already_handled": False,
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get position manager statistics."""
        pending = sum(1 for t in self.active_trades.values() if t.status == TradeStatus.PENDING)
        confirmed = sum(1 for t in self.active_trades.values() if t.status != TradeStatus.PENDING)
        locked_markets = len(self.market_locks)
        
        pnl = self.get_total_pnl()
        
        return {
            "total_trades": len(self.active_trades),
            "pending_trades": pending,
            "confirmed_trades": confirmed,
            "locked_markets": locked_markets,
            **pnl,
        }
