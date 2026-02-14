import logging
from logging import Logger
from pathlib import Path


def setup_logging(settings) -> None:
    """Initialize console + file logging."""
    log_level = getattr(settings, "LOG_LEVEL", "INFO")
    log_path = Path(getattr(settings, "LOG_PATH", "logs/app.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:
        # Already configured
        return

    root.setLevel(log_level)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    try:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except Exception:
        # If file logging fails, continue with console only.
        pass


def get_logger(name: str) -> Logger:
    """Get a named logger."""
    return logging.getLogger(name)

