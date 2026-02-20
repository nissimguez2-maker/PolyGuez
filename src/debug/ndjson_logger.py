from __future__ import annotations
import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

def get_debug_log_path() -> str:
    # default path if not overridden by settings/env
    default = Path.cwd() / ".cursor" / "debug.log"
    return str(default)

def is_enabled() -> bool:
    # env override
    v = os.environ.get("DEBUG_NDJSON_LOG", None)
    if v is not None:
        return v.strip() not in ("0", "false", "False", "")
    # try settings if available
    try:
        from src.config.settings import get_settings
        s = get_settings()
        return bool(getattr(s, "DEBUG_NDJSON_LOG", False))
    except Exception:
        return False

def _ensure_parent(path: str):
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

def dbg_log(hypothesis: str, location: str, message: str, data: dict = None, run_id: str | None = None):
    if not is_enabled():
        return
    try:
        path = os.environ.get("DEBUG_NDJSON_LOG_PATH") or get_debug_log_path()
        _ensure_parent(path)
        entry = {
            "id": uuid.uuid4().hex,
            "ts_iso": datetime.now(timezone.utc).isoformat(),
            "ts_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            "run_id": run_id or "debug_run",
            "hypothesis": hypothesis,
            "location": location,
            "message": message,
            "data": data or {}
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # swallow all errors
        try:
            pass
        except Exception:
            pass

