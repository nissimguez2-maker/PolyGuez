import logging
from typing import Optional


def get_logger(name: Optional[str] = None) -> logging.Logger:
  """
  Return a configured logger for Polymarket Agents components.

  The logger uses a simple, concise format that works well both in local
  development and in containerized environments.

  Example:
      from agents.logging_utils import get_logger

      logger = get_logger(__name__)
      logger.info("Starting agent loop")
  """
  logger_name = name or "polymarket-agents"
  logger = logging.getLogger(logger_name)

  if logger.handlers:
    return logger

  logger.setLevel(logging.INFO)

  handler = logging.StreamHandler()
  formatter = logging.Formatter(
      fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
      datefmt="%Y-%m-%d %H:%M:%S",
  )
  handler.setFormatter(formatter)
  logger.addHandler(handler)

  return logger
