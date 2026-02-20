import requests
import json

def main():
    url = "http://127.0.0.1:5000/debug/smoke_trade"
    payload = {"side": "YES", "shares": 1.0, "hold_seconds": 1}
    r = requests.post(url, json=payload, timeout=30)
    print(r.status_code)
    try:
        print(r.json())
    except Exception:
        print(r.text)

if __name__ == "__main__":
    main()

