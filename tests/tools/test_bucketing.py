from tools.research.analyze_paper_trades import price_bucket


def test_price_bucket_basic():
    assert price_bucket(0.05) == "0.0-0.1"
    assert price_bucket(0.15) == "0.1-0.2"
    assert price_bucket(0.99) == "0.9-1.0"
    assert price_bucket(None) == "na"
    assert price_bucket("0.23") == "0.2-0.3"

