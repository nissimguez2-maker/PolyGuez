#!/usr/bin/env python3
"""Test script: connect to Polymarket RTDS, parse messages, print prices.

Usage: python scripts/python/test_feeds.py

Connects to RTDS, subscribes to Binance (crypto_prices) and Chainlink
(crypto_prices_chainlink) feeds, parses 15 messages, prints extracted prices.

RTDS message format (from Polymarket docs):
  {
    "topic": "crypto_prices",
    "type": "update",
    "timestamp": 1753314088421,
    "payload": {
      "symbol": "btcusdt",
      "timestamp": 1753314088395,
      "value": 67234.50
    }
  }
"""

import asyncio
import json
import sys

import websockets

RTDS_URL = "wss://ws-live-data.polymarket.com"

# Binance: plain string filter on crypto_prices topic
SUB_BINANCE = json.dumps({
    "action": "subscribe",
    "subscriptions": [{
        "topic": "crypto_prices",
        "type": "update",
        "filters": "btcusdt",
    }],
})

# Chainlink: JSON-encoded filter on crypto_prices_chainlink topic
SUB_CHAINLINK = json.dumps({
    "action": "subscribe",
    "subscriptions": [{
        "topic": "crypto_prices_chainlink",
        "type": "*",
        "filters": json.dumps({"symbol": "btc/usd"}),
    }],
})


async def main():
    print(f"Connecting to {RTDS_URL}...")
    try:
        ws = await asyncio.wait_for(websockets.connect(RTDS_URL), timeout=10)
    except Exception as exc:
        print(f"Connection failed: {exc}")
        sys.exit(1)

    print("Connected!\n")

    print(f"Sending Binance subscription:\n  {SUB_BINANCE}")
    await ws.send(SUB_BINANCE)

    print(f"Sending Chainlink subscription:\n  {SUB_CHAINLINK}\n")
    await ws.send(SUB_CHAINLINK)

    binance_prices = []
    chainlink_prices = []
    msg_count = 0
    target = 15

    print("Listening for messages...\n" + "=" * 70)

    async for raw in ws:
        if raw == "PONG":
            continue

        msg_count += 1

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            print(f"  [{msg_count}] NOT JSON: {raw[:200]}")
            if msg_count >= target:
                break
            continue

        topic = msg.get("topic", "")
        payload = msg.get("payload")

        # Print first 5 messages in full
        if msg_count <= 5:
            print(f"\n[{msg_count}] FULL:\n  {json.dumps(msg, indent=2)[:600]}")
        else:
            print(f"\n[{msg_count}] topic={topic}", end="")

        if not payload or not isinstance(payload, dict):
            print(f"  (no payload)")
            if msg_count >= target:
                break
            continue

        symbol = (payload.get("symbol") or "").lower()
        price = None
        for key in ("value", "price", "p"):
            if key in payload:
                try:
                    price = float(payload[key])
                    break
                except (ValueError, TypeError):
                    continue

        if price and price > 1000:
            if topic == "crypto_prices_chainlink" or symbol in ("btc/usd", "btcusd"):
                chainlink_prices.append(price)
                print(f"  -> CHAINLINK: ${price:,.2f}")
            elif topic == "crypto_prices" or symbol == "btcusdt":
                binance_prices.append(price)
                print(f"  -> BINANCE: ${price:,.2f}")
            else:
                print(f"  -> UNKNOWN({symbol}): ${price:,.2f}")
        else:
            print(f"  symbol={symbol} payload={str(payload)[:100]}")

        if msg_count >= target:
            break

    await ws.close()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print(f"  Total messages: {msg_count}")
    print(f"  Binance prices: {len(binance_prices)}")
    if binance_prices:
        print(f"    Last 5: {['${:,.2f}'.format(p) for p in binance_prices[-5:]]}")
    print(f"  Chainlink prices: {len(chainlink_prices)}")
    if chainlink_prices:
        print(f"    Last 5: {['${:,.2f}'.format(p) for p in chainlink_prices[-5:]]}")

    if not binance_prices and not chainlink_prices:
        print("\n  WARNING: No prices extracted!")


if __name__ == "__main__":
    asyncio.run(main())
