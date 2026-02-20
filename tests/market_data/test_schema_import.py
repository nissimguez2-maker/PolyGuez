import importlib


def test_schema_module_imports_cleanly():
    mod = importlib.import_module("src.market_data.schema")
    assert hasattr(mod, "OrderBookSnapshot")
    assert hasattr(mod, "MarketEvent")
