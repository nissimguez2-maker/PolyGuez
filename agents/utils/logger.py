import logging

logger = logging.getLogger("polymarket")
logger.setLevel(logging.INFO)

handler = logging.StreamHandler()
formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

def info(message: str) -> None:
    logger.info(message)

def error(message: str) -> None:
    logger.error(message)
