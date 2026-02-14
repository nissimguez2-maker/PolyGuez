import sys
from datetime import datetime, timezone, timedelta
sys.path.append(".")

from agents.application.fast_entry_engine import FastEntryEngine
from tools.research.trade_report import normalize_trade


def test_timing_gate_blocks_and_allows(monkeypatch):
    # Create engine with small params, no websocket
    class DummyPolymarket:
        def get_market(self, token):
            class M:
                id = "mkt"
            return M()
        def get_orderbook(self, token):
            return types.SimpleNamespace(bids=[types.SimpleNamespace(price=0.5)], asks=[types.SimpleNamespace(price=0.51)])

    import types, time
    pm = DummyPolymarket()
    engine = FastEntryEngine(polymarket=pm, use_websocket=False)

    # Build a fake signal with token
    from agents.application.fast_entry_engine import DislocationSignal
    now = datetime.now(timezone.utc)
    sig = DislocationSignal(timestamp_ms=int(now.timestamp()*1000), token_id="tok", side="UP", price_drop_pct=2.0, speed_ratio=2.0, current_price=0.5, baseline_price=0.51, window_ms=1000)
    sig.t_detect_ms = time.monotonic()*1000

    # monkeypatch timeframes to simulate late in window
    def fake_seconds_from_start(dt, minutes):
        return 9999
    def fake_seconds_to_end(dt, minutes):
        return 10
    monkeypatch.setattr("src.timeframes.seconds_from_start", fake_seconds_from_start)
    monkeypatch.setattr("src.timeframes.seconds_to_end", fake_seconds_to_end)

    # should be blocked (too close to end)
    res = engine._execute_leg1(sig)
    import asyncio
    r = asyncio.get_event_loop().run_until_complete(res)
    assert r is None

