import asyncio

import webhook_server_fastapi as ws


class _DummyState:
    def __init__(self):
        self.missing_count = {}


def test_reconcile_subscriptions_noop_when_adapter_missing():
    # Must not raise when adapter is unavailable.
    asyncio.run(ws._reconcile_subscriptions(None, {"to_subscribe": {"t1"}, "to_unsubscribe": {"t2"}}, _DummyState()))
