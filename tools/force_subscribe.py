import sys
sys.path.append('.')
import asyncio
from webhook_server_fastapi import _market_data_adapter

async def main():
    if _market_data_adapter and getattr(_market_data_adapter, 'subscribe', None):
        await _market_data_adapter.subscribe('FORCE_TEST_TOKEN_1')
        print('subscribe awaited')
    else:
        print('adapter or subscribe missing')

if __name__ == '__main__':
    asyncio.run(main())

