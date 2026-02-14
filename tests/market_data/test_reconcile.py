import sys
import asyncio
import types
# ensure local src/ is importable in CI / test runs
sys.path.append(".")
from src.market_data.reconcile import ReconcileState, reconcile_step


class FakeAdapter:
    def __init__(self, subs=None):
        self._subs = set(subs or [])

    async def subscribe(self, token_id):
        # emulate network-less subscribe
        self._subs.add(token_id)

    async def unsubscribe(self, token_id):
        self._subs.discard(token_id)


def test_unsubscribe_after_n_cycles(tmp_path):
    adapter = FakeAdapter(subs={"T1"})
    state = ReconcileState()
    # desired empty -> should not unsubscribe until threshold reached
    for i in range(2):
        res = reconcile_step(adapter, {}, state, missing_threshold=3)
        assert res["to_unsubscribe"] == set()

    # third cycle -> candidate should be scheduled for unsubscribe
    res = reconcile_step(adapter, {}, state, missing_threshold=3)
    assert res["to_unsubscribe"] == {"T1"}


def test_refcount_and_partial_close(tmp_path):
    adapter = FakeAdapter(subs=set())
    state = ReconcileState()
    # first, two open trades for T2 -> subscribe requested
    desired = {"T2": 2}
    res = reconcile_step(adapter, desired, state, missing_threshold=2)
    assert res["to_subscribe"] == {"T2"}
    # emulate subscribe applied
    adapter._subs.add("T2")

    # one trade closed -> desired_refcount 1 -> should not trigger unsubscribe
    desired = {"T2": 1}
    res = reconcile_step(adapter, desired, state, missing_threshold=2)
    assert res["to_unsubscribe"] == set()

    # now close last trade -> desired empty -> after threshold cycles => unsub
    desired = {}
    res = reconcile_step(adapter, desired, state, missing_threshold=2)
    # first cycle: no unsubscribe yet
    assert res["to_unsubscribe"] == set()
    # second cycle: now should unsubscribe
    res = reconcile_step(adapter, desired, state, missing_threshold=2)
    assert res["to_unsubscribe"] == {"T2"}

