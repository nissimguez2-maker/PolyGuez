from src.utils.ab_router import ab_bucket, ab_variant


def test_ab_bucket_deterministic():
    k = "token-123"
    b1 = ab_bucket(k)
    b2 = ab_bucket(k)
    assert b1 in (0, 1)
    assert b1 == b2
    assert ab_variant(k) in ("control", "variant")


def test_ab_distribution():
    # quick smoke: ensure roughly half in each bucket for range of keys
    keys = [f"tok{i}" for i in range(100)]
    cnt0 = sum(1 for k in keys if ab_bucket(k) == 0)
    cnt1 = sum(1 for k in keys if ab_bucket(k) == 1)
    assert cnt0 + cnt1 == 100
    # allow imbalance but ensure both present
    assert cnt0 > 0 and cnt1 > 0

