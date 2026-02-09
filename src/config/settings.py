import os
from dataclasses import dataclass
from typing import Optional

from src.utils.helpers import parse_bool, parse_int, parse_float


@dataclass
class Settings:
    # App
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 5000
    APP_VERSION: str = "0.0.0"
    LOG_LEVEL: str = "INFO"
    LOG_PATH: str = "logs/app.log"

    # Trading mode
    TRADING_MODE: str = "paper"  # "paper" or "live"
    DRY_RUN: bool = True
    ALLOW_LIVE: bool = False
    LIVE_CONFIRMATION_TOKEN: Optional[str] = None
    LIVE_KILL_SWITCH: bool = False
    ALLOW_FALLBACK_TO_PAPER: bool = True

    # Session IDs
    SESSION_ID: Optional[str] = None
    PHASE2_SESSION_ID: Optional[str] = None
    ARCHIVE_ON_STARTUP: bool = True

    # Risk / trading
    BASE_RISK_PCT: float = 0.02
    MAX_EXPOSURE_PCT: float = 0.25
    SOFT_STOP_ADVERSE_MOVE: float = 0.15
    TIME_STOP_BARS: int = 2
    ENABLE_SESSION_FILTER: bool = True
    INITIAL_EQUITY: float = 100.0
    PAPER_USDC: float = 1.0

    # Confidence / confirmation
    MIN_CONFIDENCE: int = 4
    MAX_CONFIDENCE: int = 5
    ALLOW_CONF_4: bool = True
    CONFIRM_TTL_SECONDS: int = 90
    REQUIRE_RAWCONF: bool = False
    MISSING_RAWCONF_ACTION: str = "default_to_5"
    REQUIRE_DISLOCATION: bool = False

    # Auto-close
    AUTO_CLOSE_ENABLED: bool = True
    AUTO_CLOSE_TTL_MINUTES: float = 13.0
    AUTO_CLOSE_ON_MARKET_END: bool = True
    AUTO_CLOSE_PRICE_POLL_INTERVAL: float = 30.0

    # Cleanup / rehydrate
    ORPHAN_CLEANUP_ENABLED: bool = True
    MAX_OPEN_AGE_MIN: float = 90.0
    MAX_OPEN_AGE_BARS: int = 6
    FULL_REHYDRATE_ON_STARTUP: bool = True
    REHYDRATE_MAX_AGE_HOURS: float = 24.0

    # Pattern gate
    ENABLE_PATTERN_GATE: bool = False
    PATTERN_GATE_MIN_EDGE: float = 0.02
    PATTERN_GATE_MIN_SAMPLES: int = 10
    PATTERN_GATE_MIN_CONF: float = 0.55
    PATTERN_GATE_MODE: str = "shadow"

    # Logging / test signal detection
    TEST_SIGNAL_PREFIX: str = "test_"

    # Market/meta
    SYMBOL: str = "BTCUSDT"
    TIMEFRAME: str = "15m"
    PREFIX: str = "btc-updown-15m"
    PAPER_LOG_PATH: str = "paper_trades.jsonl"
    GAMMA_API: str = "https://gamma-api.polymarket.com"


_settings: Optional[Settings] = None


def _load_from_env(settings: Settings) -> None:
    env = os.environ
    # Helper to set if env exists
    def set_if(name: str, cast):
        if name in env and env[name] != "":
            setattr(settings, name, cast(env[name]))

    set_if("APP_HOST", str)
    set_if("APP_PORT", lambda v: int(float(v)))
    set_if("APP_VERSION", str)
    set_if("LOG_LEVEL", str)
    set_if("LOG_PATH", str)

    set_if("TRADING_MODE", str)
    set_if("DRY_RUN", lambda v: parse_bool(v, settings.DRY_RUN))
    set_if("ALLOW_LIVE", lambda v: parse_bool(v, settings.ALLOW_LIVE))
    set_if("LIVE_CONFIRMATION_TOKEN", str)
    set_if("LIVE_KILL_SWITCH", lambda v: parse_bool(v, settings.LIVE_KILL_SWITCH))
    set_if("ALLOW_FALLBACK_TO_PAPER", lambda v: parse_bool(v, settings.ALLOW_FALLBACK_TO_PAPER))

    set_if("SESSION_ID", str)
    set_if("PHASE2_SESSION_ID", str)
    set_if("ARCHIVE_ON_STARTUP", lambda v: parse_bool(v, settings.ARCHIVE_ON_STARTUP))

    set_if("BASE_RISK_PCT", lambda v: parse_float(v, settings.BASE_RISK_PCT))
    set_if("MAX_EXPOSURE_PCT", lambda v: parse_float(v, settings.MAX_EXPOSURE_PCT))
    set_if("SOFT_STOP_ADVERSE_MOVE", lambda v: parse_float(v, settings.SOFT_STOP_ADVERSE_MOVE))
    set_if("TIME_STOP_BARS", lambda v: parse_int(v, settings.TIME_STOP_BARS))
    set_if("ENABLE_SESSION_FILTER", lambda v: parse_bool(v, settings.ENABLE_SESSION_FILTER))
    set_if("INITIAL_EQUITY", lambda v: parse_float(v, settings.INITIAL_EQUITY))
    set_if("PAPER_USDC", lambda v: parse_float(v, settings.PAPER_USDC))

    set_if("MIN_CONFIDENCE", lambda v: parse_int(v, settings.MIN_CONFIDENCE))
    set_if("MAX_CONFIDENCE", lambda v: parse_int(v, settings.MAX_CONFIDENCE))
    set_if("ALLOW_CONF_4", lambda v: parse_bool(v, settings.ALLOW_CONF_4))
    set_if("CONFIRM_TTL_SECONDS", lambda v: parse_int(v, settings.CONFIRM_TTL_SECONDS))
    set_if("REQUIRE_RAWCONF", lambda v: parse_bool(v, settings.REQUIRE_RAWCONF))
    set_if("MISSING_RAWCONF_ACTION", str)
    set_if("REQUIRE_DISLOCATION", lambda v: parse_bool(v, settings.REQUIRE_DISLOCATION))

    set_if("AUTO_CLOSE_ENABLED", lambda v: parse_bool(v, settings.AUTO_CLOSE_ENABLED))
    set_if("AUTO_CLOSE_TTL_MINUTES", lambda v: parse_float(v, settings.AUTO_CLOSE_TTL_MINUTES))
    set_if("AUTO_CLOSE_ON_MARKET_END", lambda v: parse_bool(v, settings.AUTO_CLOSE_ON_MARKET_END))
    set_if("AUTO_CLOSE_PRICE_POLL_INTERVAL", lambda v: parse_float(v, settings.AUTO_CLOSE_PRICE_POLL_INTERVAL))

    set_if("ORPHAN_CLEANUP_ENABLED", lambda v: parse_bool(v, settings.ORPHAN_CLEANUP_ENABLED))
    set_if("MAX_OPEN_AGE_MIN", lambda v: parse_float(v, settings.MAX_OPEN_AGE_MIN))
    set_if("MAX_OPEN_AGE_BARS", lambda v: parse_int(v, settings.MAX_OPEN_AGE_BARS))
    set_if("FULL_REHYDRATE_ON_STARTUP", lambda v: parse_bool(v, settings.FULL_REHYDRATE_ON_STARTUP))
    set_if("REHYDRATE_MAX_AGE_HOURS", lambda v: parse_float(v, settings.REHYDRATE_MAX_AGE_HOURS))

    set_if("ENABLE_PATTERN_GATE", lambda v: parse_bool(v, settings.ENABLE_PATTERN_GATE))
    set_if("PATTERN_GATE_MIN_EDGE", lambda v: parse_float(v, settings.PATTERN_GATE_MIN_EDGE))
    set_if("PATTERN_GATE_MIN_SAMPLES", lambda v: parse_int(v, settings.PATTERN_GATE_MIN_SAMPLES))
    set_if("PATTERN_GATE_MIN_CONF", lambda v: parse_float(v, settings.PATTERN_GATE_MIN_CONF))
    set_if("PATTERN_GATE_MODE", str)
    set_if("TEST_SIGNAL_PREFIX", str)

    set_if("SYMBOL", str)
    set_if("TIMEFRAME", str)
    set_if("PREFIX", str)
    set_if("PAPER_LOG_PATH", str)
    set_if("GAMMA_API", str)


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _load_from_env(_settings)
    return _settings


def is_paper_trading() -> bool:
    settings = get_settings()
    return str(settings.TRADING_MODE).lower() != "live" or settings.DRY_RUN


def is_live_trading_allowed() -> tuple[bool, str]:
    settings = get_settings()
    if settings.LIVE_KILL_SWITCH:
        return False, "kill_switch_enabled"
    if not settings.ALLOW_LIVE:
        return False, "allow_live_disabled"
    if not settings.LIVE_CONFIRMATION_TOKEN:
        return False, "missing_live_token"
    return True, "ok"


def get_trading_mode_str() -> str:
    settings = get_settings()
    return "DRY_RUN" if settings.DRY_RUN else settings.TRADING_MODE.upper()

