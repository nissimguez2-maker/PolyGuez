import sys
sys.path.append(".")
import asyncio

from webhook_server_fastapi import smoke_trade, SmokeTradePayload, is_paper_trading

async def run():
    if not is_paper_trading():
        print("Not in paper mode; aborting.")
        return
    payload = SmokeTradePayload(side="YES", shares=1.0, hold_seconds=2)
    result = await smoke_trade(payload)
    print("SMOKE RESULT:", result)

if __name__ == "__main__":
    asyncio.run(run())

