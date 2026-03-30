"""Offline RTDS parse test — validates parsing against actual deploy log payloads."""

import json

# Actual messages from Railway deploy logs
SAMPLE_MESSAGES = [
    # Chainlink message from logs
    json.dumps({
        "topic": "crypto_prices_chainlink",
        "type": "update",
        "timestamp": 1774882825,
        "payload": {
            "data": [
                {"timestamp": 1774882825000, "value": 67812.19},
                {"timestamp": 1774882826000, "value": 67817.12},
            ],
            "symbol": "btc/usd",
        },
    }),
    # Binance message (same format from logs)
    json.dumps({
        "topic": "crypto_prices",
        "type": "update",
        "timestamp": 1774882825,
        "payload": {
            "data": [
                {"timestamp": 1774882191000, "value": 67212.55780248667},
                {"timestamp": 1774882192000, "value": 67218.36106078961},
            ],
            "symbol": "btcusdt",
        },
    }),
    # Edge case: single entry in data array
    json.dumps({
        "topic": "crypto_prices",
        "type": "update",
        "payload": {
            "data": [{"timestamp": 1774882830000, "value": 67900.0}],
            "symbol": "btcusdt",
        },
    }),
    # Edge case: ack message with no payload
    json.dumps({
        "action": "subscribe",
        "status": "ok",
    }),
    # Edge case: empty data array
    json.dumps({
        "topic": "crypto_prices",
        "payload": {"data": [], "symbol": "btcusdt"},
    }),
]


def parse_rtds_message(raw: str):
    """Parse an RTDS message — returns (topic, symbol, price, ts) or None."""
    msg = json.loads(raw)
    topic = msg.get("topic", "")
    payload = msg.get("payload")

    if not payload or not isinstance(payload, dict):
        return None  # ack/error/etc

    symbol = (payload.get("symbol") or "").lower()

    # RTDS sends prices in a "data" array: [{"timestamp":..,"value":..}, ...]
    # Take the LAST entry for most recent price. Fall back to flat payload.
    data_arr = payload.get("data")
    if isinstance(data_arr, list) and data_arr:
        last_entry = data_arr[-1]
        try:
            price = float(last_entry["value"])
        except (KeyError, ValueError, TypeError):
            return None
        ts = last_entry.get("timestamp", 0)
    else:
        # Flat payload fallback
        price = None
        for key in ("value", "price", "p"):
            if key in payload:
                try:
                    price = float(payload[key])
                    break
                except (ValueError, TypeError):
                    continue
        if not price:
            return None
        ts = payload.get("timestamp", 0)

    # Convert ms timestamps to seconds
    if isinstance(ts, (int, float)) and ts > 1e12:
        ts = ts / 1000.0

    return topic, symbol, price, ts


def main():
    print("Testing RTDS parser against actual deploy log messages:\n")
    for i, raw in enumerate(SAMPLE_MESSAGES):
        result = parse_rtds_message(raw)
        if result:
            topic, symbol, price, ts = result
            print(f"  [{i+1}] OK  topic={topic:<30s} symbol={symbol:<10s} price={price:.2f}  ts={ts}")
        else:
            msg = json.loads(raw)
            print(f"  [{i+1}] SKIP  {str(msg)[:100]}")

    # Verify specific values
    print("\nAssertions:")

    r1 = parse_rtds_message(SAMPLE_MESSAGES[0])
    assert r1 is not None
    assert r1[1] == "btc/usd", f"Expected btc/usd, got {r1[1]}"
    assert r1[2] == 67817.12, f"Expected 67817.12 (last entry), got {r1[2]}"
    print("  Chainlink: last entry value = 67817.12")

    r2 = parse_rtds_message(SAMPLE_MESSAGES[1])
    assert r2 is not None
    assert r2[1] == "btcusdt", f"Expected btcusdt, got {r2[1]}"
    assert abs(r2[2] - 67218.36106078961) < 0.01, f"Expected 67218.36, got {r2[2]}"
    print("  Binance: last entry value = 67218.36")

    r3 = parse_rtds_message(SAMPLE_MESSAGES[2])
    assert r3 is not None
    assert r3[2] == 67900.0
    print("  Single entry: value = 67900.00")

    r4 = parse_rtds_message(SAMPLE_MESSAGES[3])
    assert r4 is None, "Ack message should return None"
    print("  Ack message: correctly skipped")

    r5 = parse_rtds_message(SAMPLE_MESSAGES[4])
    assert r5 is None, "Empty data array should return None"
    print("  Empty data[]: correctly skipped")

    print("\nAll assertions passed.")


if __name__ == "__main__":
    main()
