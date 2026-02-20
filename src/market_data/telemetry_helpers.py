from __future__ import annotations
from typing import Optional, Set
import logging


def update_subs_gauge(adapter: Optional[object], telemetry) -> int:
    """
    Set telemetry gauge 'market_data_active_subscriptions' from adapter._subs.
    Returns the computed count.
    Best-effort: safe if adapter is None.
    """
    logger = logging.getLogger("market_data.telemetry_helpers")
    try:
        if adapter is None:
            return 0
        subs: Set[str] = set(getattr(adapter, "_subs", set()) or set())
        count = len(subs)
        try:
            telemetry.set_gauge("market_data_active_subscriptions", float(count))
        except Exception:
            logger.debug("telemetry.set_gauge failed")
        logger.info("Telemetry helper: market_data_active_subscriptions=%d", count)
        return count
    except Exception:
        logger.exception("Failed to update_subs_gauge")
        return 0

