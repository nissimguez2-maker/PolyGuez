#!/usr/bin/env python3
import json, time, sys
from urllib.request import Request, urlopen

def send(signal_id):
    url = "http://127.0.0.1:5000/webhook"
    payload = {
        "signal": "BULL",
        "signal_id": signal_id,
        "source": "tradingview",
        "confidence": 5,
        "rawConf": 5,
        "score": 1.0,
        "size": None,
        "speedRatio": 0.1,
        "rt": False,
        "sw": False,
        "mr": False,
        "botMove": False,
        "regime": "TREND",
        "session": "NY"
    }
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
            print(resp.status, body)
    except Exception as e:
        print("ERR", e)

if __name__ == "__main__":
    sid = "test-winrate-1"
    botmove_flag = False
    if len(sys.argv) > 1:
        sid = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2].lower() in ("botmove","true","1"):
        botmove_flag = True
    # if botmove_flag set, override payload to include botMove True
    if botmove_flag:
        # re-create payload with botMove True
        import json
        payload = {
            "signal": "BULL",
            "signal_id": sid,
            "source": "tradingview",
            "confidence": 5,
            "rawConf": 5,
            "score": 1.0,
            "size": None,
            "speedRatio": 0.1,
            "rt": False,
            "sw": False,
            "mr": False,
            "botMove": True,
            "regime": "TREND",
            "session": "NY"
        }
        from urllib.request import Request, urlopen
        data = json.dumps(payload).encode("utf-8")
        req = Request("http://127.0.0.1:5000/webhook", data=data, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8")
                print(resp.status, body)
        except Exception as e:
            print("ERR", e)
    else:
        send(sid)

