import sys
sys.path.insert(0, ".")

from src.market_discovery.btc_updown import derive_btc_updown_slug_from_payload


def test_slug_from_payload_exact_window():
    payload = {"window_end_ms": 1771102800000}
    slug = derive_btc_updown_slug_from_payload(payload, 5)
    assert slug == "btc-updown-5m-1771102800"


def test_slug_from_payload_off_boundary_rounds_nearest():
    # base boundary (seconds) -> 1771102800 corresponds to ms 1771102800000
    base_ms = 1771102800000
    # add 200_000 ms ( > half of 5m window 150_000 ) -> should round up to next boundary (base + 300_000)
    window_ms = base_ms + 200_000
    slug = derive_btc_updown_slug_from_payload({"window_end_ms": window_ms}, 5)
    # next boundary seconds:
    expected_start_s = (base_ms + 300_000) // 1000
    assert slug == f"btc-updown-5m-{expected_start_s}"

