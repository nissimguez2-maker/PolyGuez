from __future__ import annotations
import hashlib


def ab_bucket(key: str) -> int:
    """
    Deterministic A/B bucket for a given key.
    Returns 0 for control, 1 for variant.
    Uses SHA256(key).digest()[-1] % 2 as the lowest-byte method.
    """
    if key is None:
        return 0
    try:
        b = hashlib.sha256(str(key).encode()).digest()[-1]
        return int(b % 2)
    except Exception:
        # fallback deterministic: hash builtin
        return hash(key) % 2


def ab_variant(key: str) -> str:
    return "variant" if ab_bucket(key) == 1 else "control"

