import sys
sys.path.append('.')
import importlib
ws = importlib.import_module('webhook_server_fastapi')
ada = getattr(ws, '_market_data_adapter', None)
print('adapter present:', bool(ada))
print('adapter object:', type(ada))
try:
    print('adapter subs count:', len(getattr(ada,'_subs',[])))
except Exception as e:
    print('adapter subs error', e)

