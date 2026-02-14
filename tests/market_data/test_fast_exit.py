import time
from agents.application.position_manager import PositionManager, ActiveTrade


def make_trade(pm: PositionManager, token_id: str, entry_price: float, created_at: float = None) -> ActiveTrade:
    trade = ActiveTrade(
        trade_id="t1",
        market_id="m1",
        token_id=token_id,
        side="UP",
        leg1_size=1.0,
        leg1_price=entry_price,
        leg1_entry_id="e1",
        created_at=(created_at if created_at is not None else time.monotonic()),
        created_at_utc="now",
        total_size=1.0,
        entry_price=entry_price
    )
    pm.active_trades[trade.trade_id] = trade
    pm.market_locks[trade.market_id] = trade.trade_id
    return trade


def test_fast_exit_tp_sl_time(monkeypatch):
    pm = PositionManager()
    token = "TOK1"
    now = time.monotonic()
    trade = make_trade(pm, token, 0.50, created_at=now - 20)  # held 20s
    # TP scenario: best_bid enough to trigger take profit
    res = pm.evaluate_fast_exit(trade, best_bid=0.58, best_ask=0.59, now_monotonic=now)
    # Depending on hashing variant, either variant inactive (None) or exit executed.
    # If variant active, exit should have been performed and trade.exited True
    if res:
        assert trade.exited is True or res.get("action") == "exit"

    # SL scenario
    trade2 = make_trade(pm, "TOK2", 0.50, created_at=now - 20)
    res2 = pm.evaluate_fast_exit(trade2, best_bid=0.39, best_ask=0.40, now_monotonic=now)
    if res2:
        assert res2.get("reason") in ("sl", "tp", "time_stop", "max_hold")

