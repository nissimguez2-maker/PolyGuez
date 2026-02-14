import hashlib
import importlib
from src.order_executor import place_entry_order_with_gate


class FakeRiskManager:
    def __init__(self, equity):
        self.current_equity = equity


class FakePositionManager:
    def __init__(self, open_exposure):
        # active_trades map with objects having total_size
        self.active_trades = {"t1": type("T", (), {"total_size": open_exposure})()}


class FakePolymarket:
    def __init__(self):
        self.last_order = None

    def execute_order(self, price, size, side, token_id, gate_checked=False):
        self.last_order = {"price": price, "size": size, "side": side, "token_id": token_id, "gate_checked": gate_checked}
        return "order123"


def find_variant_token(desired_variant=1):
    # find a token string that maps to desired variant using sha256 lowest byte %2
    for i in range(10000):
        tok = f"tok_{i}"
        h = hashlib.sha256(tok.encode()).digest()[0]
        if (h % 2) == desired_variant:
            return tok
    return "tok_default"


def test_sizing_variant_applies(monkeypatch):
    # choose token that maps to variant 1
    token = find_variant_token(1)
    # patch webhook_server_fastapi get_risk_manager and get_position_manager
    fake_rm = FakeRiskManager(100.0)  # equity 100
    fake_pm = FakePositionManager(9.0)  # open exposure 9

    mod = importlib.import_module("webhook_server_fastapi")
    monkeypatch.setattr(mod, "get_risk_manager", lambda: fake_rm)
    monkeypatch.setattr(mod, "get_position_manager", lambda: fake_pm)

    poly = FakePolymarket()
    res = place_entry_order_with_gate(polymarket=poly, token_id=token, price=0.5, size=5.0)
    # With equity=100, desired=2, budget_total=10, open_exposure=9 => budget_left=1 => final_size=1
    assert res["allowed"] is True
    assert poly.last_order["size"] == 1.0


def test_sizing_variant_blocks_when_budget_exhausted(monkeypatch):
    token = find_variant_token(1)
    fake_rm = FakeRiskManager(100.0)
    fake_pm = FakePositionManager(10.0)  # open exposure = budget_total
    mod = importlib.import_module("webhook_server_fastapi")
    monkeypatch.setattr(mod, "get_risk_manager", lambda: fake_rm)
    monkeypatch.setattr(mod, "get_position_manager", lambda: fake_pm)
    poly = FakePolymarket()
    res = place_entry_order_with_gate(polymarket=poly, token_id=token, price=0.5, size=5.0)
    assert res["allowed"] is False
    assert res["reason"] == "exposure_budget_exhausted"

