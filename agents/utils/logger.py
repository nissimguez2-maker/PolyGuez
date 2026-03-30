import json
import logging
import os
import re
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


_REDACT_PATTERNS = re.compile(r"(key|private|secret|password|token)", re.IGNORECASE)


class _RedactingFormatter(logging.Formatter):
    """JSON formatter that redacts sensitive fields."""

    def format(self, record):
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "event_type"):
            log_entry["event_type"] = record.event_type
        if hasattr(record, "data") and isinstance(record.data, dict):
            log_entry["data"] = self._redact(record.data)
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry, default=str)

    def _redact(self, data):
        out = {}
        for k, v in data.items():
            if _REDACT_PATTERNS.search(k):
                out[k] = "***REDACTED***"
            elif isinstance(v, dict):
                out[k] = self._redact(v)
            else:
                out[k] = v
        return out


def get_logger(name="polyguez"):
    """Return a structured JSON logger.

    Outputs to stdout and a rotating file at logs/polyguez.jsonl.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = _RedactingFormatter()

    # stdout handler
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    # file handler
    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    fh = RotatingFileHandler(
        os.path.join(log_dir, "polyguez.jsonl"),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


def log_event(logger, event_type, msg, data=None, level=logging.INFO):
    """Log a structured event with optional data dict."""
    record = logger.makeRecord(
        logger.name, level, "(polyguez)", 0, msg, (), None,
    )
    record.event_type = event_type
    record.data = data or {}
    logger.handle(record)
