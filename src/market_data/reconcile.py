from __future__ import annotations
from typing import Dict, Set
import logging

logger = logging.getLogger(__name__)


class ReconcileState:
    def __init__(self) -> None:
        # missing_count[token] = consecutive reconcile cycles where token was absent from desired set
        self.missing_count: Dict[str, int] = {}


def reconcile_step(
    adapter,
    desired_refcount: Dict[str, int],
    state: ReconcileState,
    missing_threshold: int = 3,
) -> Dict[str, Set[str]]:
    """
    Compute subscription actions to sync adapter subscriptions with desired_refcount.

    Returns dict with keys: to_subscribe, to_unsubscribe.
    Unsubscribe decisions are guarded by missing_threshold (must be missing for that many cycles).
    """
    current_tokens: Set[str] = set(getattr(adapter, "_subs", set()) or set())

    desired_tokens = set(k for k, v in desired_refcount.items() if v and v > 0)

    to_subscribe = desired_tokens - current_tokens

    # Tokens potentially to unsubscribe are those present but not desired now
    candidates_unsub = current_tokens - desired_tokens

    to_unsubscribe: Set[str] = set()
    # update missing counts
    for tk in candidates_unsub:
        state.missing_count[tk] = state.missing_count.get(tk, 0) + 1
        if state.missing_count[tk] >= missing_threshold:
            to_unsubscribe.add(tk)

    # reset missing count for tokens that reappeared
    for tk in desired_tokens & set(state.missing_count.keys()):
        if state.missing_count.get(tk):
            logger.debug("reconcile: token %s reappeared, clearing missing_count", tk)
        state.missing_count.pop(tk, None)

    # Cleanup missing_count entries for tokens already unsubscribed
    for tk in list(state.missing_count.keys()):
        if tk not in current_tokens and tk not in desired_tokens:
            # keep counting until threshold; nothing else to do here
            pass

    return {"to_subscribe": to_subscribe, "to_unsubscribe": to_unsubscribe}

