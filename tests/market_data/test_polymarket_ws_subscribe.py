import sys
import asyncio
import json
sys.path.append(".")

from src.market_data.providers.polymarket_ws import PolymarketWSProvider


class FakeWS:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send(self, payload):
        # emulate async send
        self.sent.append(payload)

    async def close(self):
        self.closed = True


def test_subscribe_op_sent_when_connected():
    prov = PolymarketWSProvider("wss://example.test/ws/market")
    fake = FakeWS()
    # emulate connected websocket
    prov._ws = fake
    # ensure closed attr exists and is False
    fake.closed = False

    async def run_sub():
        await prov.subscribe(["T1", "T2", "T3"])

    asyncio.run(run_sub())
    assert fake.sent, "no messages sent"
    last = json.loads(fake.sent[-1])
    # should be operation subscribe when sent after connect
    assert last.get("operation") == "subscribe"
    assert "assets_ids" in last and isinstance(last["assets_ids"], list)


def test_handshake_sent_on_handshake_call():
    prov = PolymarketWSProvider("wss://example.test/ws/market")
    fake = FakeWS()
    prov._ws = fake
    async def run_handshake():
        await prov._send_subscribe(["A1"])
    asyncio.run(run_handshake())
    assert fake.sent, "no handshake sent"
    last = json.loads(fake.sent[-1])
    assert last.get("type") == "market"
    assert "assets_ids" in last

