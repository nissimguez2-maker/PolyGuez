import os
from pathlib import Path

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
    SOFT_STOP_ADVERSE_MOVE: float = 0.10   # 10% (was 15% – tighter stop to cut losses faster)
    TIME_STOP_BARS: int = 2
    ENABLE_SESSION_FILTER: bool = True
    INITIAL_EQUITY: float = 100.0
    PAPER_USDC: float = 1.0

    # Confidence / confirmation
    MIN_CONFIDENCE: int = 5                 # was 4 – skip lowest-quality signals
    MAX_CONFIDENCE: int = 10                # was 5 – allow high-confidence signals through
    ALLOW_CONF_4: bool = False              # was True – conf 4 trades were mostly losers
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
    
    # Win-rate upgrade (feature flag)
    WINRATE_UPGRADE_ENABLED: bool = False  # safe default: disabled

    # Market Quality Gate
    ENABLE_MARKET_QUALITY_GATE: bool = True
    MARKET_QUALITY_MODE: str = "enforce"    # was "shadow" – now BLOCKS trades with bad orderbook
    REQUIRE_BEST_ASK: bool = True           # must have sellers to buy

    # Market Quality (entry) params
    MAX_SPREAD_ENTRY: float = 0.05          # 5% max spread (was 10% – tighter to avoid bad fills)
    MIN_ASK_SIZE: float = 5.0
    ENFORCE_DEPTH: bool = True  # if True, require ask size available

    # Entry window
    ENTRY_WINDOW_END_SECONDS: int = 300  # 5 minutes
    ENTRY_WINDOW_STRICT: bool = True

    # Confirmation / debounce
    REQUIRE_CONFIRMATION: bool = True
    CONFIRMATION_DELAY_SECONDS: int = 60
    CONFIRMATION_TTL_SECONDS: int = 180
    PENDING_CONFIRM_PATH: str = "pending_confirmations.json"

    # Exit safety
    MAX_SPREAD_EXIT: float = 0.15
    MAX_HOLD_SECONDS: int = 900  # 15 minutes
    
    # MarketData Adapter
    MARKET_DATA_WS_ENABLED: bool = True
    MARKET_DATA_WS_URL: str = "wss://ws-subscriptions-clob.polymarket.com"
    MARKET_DATA_WS_PING_INTERVAL: int = 10
    MARKET_DATA_WS_PONG_TIMEOUT: int = 30
    MARKET_DATA_WS_RECONNECT_MAX: int = 30
    MARKET_DATA_CACHE_STALE_SECONDS: float = 30.0
    MARKET_DATA_BUS_QUEUE_SIZE: int = 1000
    # RTDS (optional) - real-time data stream provider settings
    MARKET_DATA_RTDS_ENABLED: bool = True
    MARKET_DATA_RTDS_URL: str = "wss://ws-live-data.polymarket.com"
    # Reconcile interval (seconds) for subscribing open trades on startup and periodically
    MARKET_DATA_RECONCILE_SECONDS: int = 30
    # How many consecutive reconcile cycles a token must be missing before unsubscribe
    MARKET_DATA_RECONCILE_MISSING_THRESHOLD: int = 3
    # Debug / admin endpoints toggle and simple token auth
    # Debug endpoints should be exposed only behind VPN/ingress auth; token is a secondary guard.
    DEBUG_ENDPOINTS_ENABLED: bool = False
    DEBUG_ENDPOINTS_TOKEN: str | None = None
    # BTC Up/Down timeframe settings (minutes)
    BTC_UPDOWN_TIMEFRAME_MINUTES: int = 15
    BTC_UPDOWN_ENABLE_5M: bool = True
    # Entry timing gates (seconds)
    BTC_UPDOWN_ENTRY_DEADLINE_SECONDS: int = 60
    BTC_UPDOWN_MIN_TIME_TO_END_SECONDS: int = 30
    BTC_UPDOWN_AUTO_CLOSE_BUFFER_SECONDS: int = 15
    # Feature flag: request best_bid_ask enrichment from provider if available
    MARKET_DATA_CUSTOM_FEATURE_ENABLED: bool = True
    # Debug NDJSON logging for runtime debug sessions (writes NDJSON to DEBUG_NDJSON_LOG_PATH when enabled)
    DEBUG_NDJSON_LOG: bool = False
    DEBUG_NDJSON_LOG_PATH: str = str(Path.cwd() / ".cursor" / "debug.log")
    # Entry / Risk Gates (conservative defaults)
    MAX_ENTRY_SPREAD: float = 0.05
    HARD_REJECT_SPREAD: float = 0.30
    REQUIRE_MARKET_QUALITY_HEALTHY: bool = True
    DISABLE_CONFIDENCE_GE: int = 7
    MIN_TOP_LEVEL_SIZE: float = 0.0
    ENTRY_REQUIRE_FRESH_BOOK: bool = True
    ENTRY_MAX_BOOK_AGE_SECONDS: int = 20
    KILL_SWITCH_ENABLED: bool = True
    KILL_SWITCH_LOOKBACK_CLOSED: int = 20
    KILL_SWITCH_MAX_REALIZED_LOSS: float = -5.0
    KILL_SWITCH_MIN_WINRATE: float = 0.25
    KILL_SWITCH_COOLDOWN_SECONDS: int = 900
    RISK_STATE_PATH: str = "data/risk_state.json"
    # ------------------------------------------------------------------
    # Persistent Risk State
    #
    # RISK_STATE_PATH:
    # Path to JSON file used to persist the kill-switch cooldown state.
    # Default: data/risk_state.json
    #
    # Deployment notes:
    # - Ensure the directory containing RISK_STATE_PATH is writable by the process
    #   (e.g. create `data/` and set permissions, or override path in environment).
    # - Override via environment variable:
    #     export RISK_STATE_PATH=/var/lib/bot/risk_state.json
    #
    # The RiskManager writes the file atomically (temp + rename) and clears it
    # automatically after the cooldown expires.
    # ------------------------------------------------------------------
    # Enforce gate at low-level Polymarket client to prevent bypass.
    ENTRY_GATE_ENFORCE_POLY: bool = True
    # Entry filters (A/B test capable)
    MAX_ENTRY_PRICE: Optional[float] = None
    MIN_EDGE_CENTS: Optional[float] = None
    MAX_SPREAD_PCT: Optional[float] = None
    ENTRY_FILTERS_AB_ENABLED: bool = True
    # Variant-specific conservative defaults (used when routing places trade in variant bucket)
    MAX_SPREAD_PCT_VARIANT: Optional[float] = 0.03
    MIN_EDGE_CENTS_VARIANT: Optional[float] = 0.02
    MAX_ENTRY_PRICE_VARIANT: Optional[float] = None
    # FastExit settings (A/B)
    FAST_EXIT_AB_ENABLED: bool = True
    FAST_EXIT_TIME_STOP_S: int = 90
    FAST_EXIT_STOP_LOSS_CENTS: float = 0.10
    FAST_EXIT_TAKE_PROFIT_CENTS: float = 0.07
    FAST_EXIT_MIN_HOLD_S: int = 10
    FAST_EXIT_MAX_HOLD_S: int = 120
    POSITION_RISK_PCT_PER_TRADE: float = 0.02
    MAX_TOTAL_EXPOSURE_PCT: float = 0.10
    # How long to keep a token subscribed after a signal (seconds)
    SUBSCRIBE_KEEPALIVE_SECONDS: int = 180


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
    # Win-rate upgrade envs
    set_if("WINRATE_UPGRADE_ENABLED", lambda v: parse_bool(v, settings.WINRATE_UPGRADE_ENABLED))
    set_if("ENABLE_MARKET_QUALITY_GATE", lambda v: parse_bool(v, settings.ENABLE_MARKET_QUALITY_GATE))
    set_if("MARKET_QUALITY_MODE", str)
    set_if("REQUIRE_BEST_ASK", lambda v: parse_bool(v, settings.REQUIRE_BEST_ASK))
    set_if("REQUIRE_CONFIRMATION", lambda v: parse_bool(v, settings.REQUIRE_CONFIRMATION))
    set_if("CONFIRMATION_DELAY_SECONDS", lambda v: parse_int(v, settings.CONFIRMATION_DELAY_SECONDS))
    set_if("CONFIRMATION_TTL_SECONDS", lambda v: parse_int(v, settings.CONFIRMATION_TTL_SECONDS))
    set_if("DEBUG_NDJSON_LOG", lambda v: parse_bool(v, settings.DEBUG_NDJSON_LOG))
    set_if("DEBUG_NDJSON_LOG_PATH", str)
    set_if("MAX_SPREAD_ENTRY", lambda v: parse_float(v, settings.MAX_SPREAD_ENTRY))
    set_if("MIN_ASK_SIZE", lambda v: parse_float(v, settings.MIN_ASK_SIZE))
    set_if("ENFORCE_DEPTH", lambda v: parse_bool(v, settings.ENFORCE_DEPTH))
    set_if("ENTRY_WINDOW_END_SECONDS", lambda v: parse_int(v, settings.ENTRY_WINDOW_END_SECONDS))
    set_if("ENTRY_WINDOW_STRICT", lambda v: parse_bool(v, settings.ENTRY_WINDOW_STRICT))
    set_if("MAX_SPREAD_EXIT", lambda v: parse_float(v, settings.MAX_SPREAD_EXIT))
    set_if("MAX_HOLD_SECONDS", lambda v: parse_int(v, settings.MAX_HOLD_SECONDS))
    set_if("PENDING_CONFIRM_PATH", str)
    # MarketData envs
    set_if("MARKET_DATA_WS_ENABLED", lambda v: parse_bool(v, settings.MARKET_DATA_WS_ENABLED))
    set_if("MARKET_DATA_WS_URL", str)
    set_if("MARKET_DATA_WS_PING_INTERVAL", lambda v: parse_int(v, settings.MARKET_DATA_WS_PING_INTERVAL))
    set_if("MARKET_DATA_WS_PONG_TIMEOUT", lambda v: parse_int(v, settings.MARKET_DATA_WS_PONG_TIMEOUT))
    set_if("MARKET_DATA_WS_RECONNECT_MAX", lambda v: parse_int(v, settings.MARKET_DATA_WS_RECONNECT_MAX))
    set_if("MARKET_DATA_CACHE_STALE_SECONDS", lambda v: parse_float(v, settings.MARKET_DATA_CACHE_STALE_SECONDS))
    set_if("MARKET_DATA_BUS_QUEUE_SIZE", lambda v: parse_int(v, settings.MARKET_DATA_BUS_QUEUE_SIZE))
    set_if("MARKET_DATA_RECONCILE_MISSING_THRESHOLD", lambda v: parse_int(v, settings.MARKET_DATA_RECONCILE_MISSING_THRESHOLD))
    set_if("MAX_ENTRY_SPREAD", lambda v: parse_float(v, settings.MAX_ENTRY_SPREAD))
    set_if("DEBUG_ENDPOINTS_ENABLED", lambda v: parse_bool(v, settings.DEBUG_ENDPOINTS_ENABLED))
    set_if("DEBUG_ENDPOINTS_TOKEN", str)
    set_if("MARKET_DATA_CUSTOM_FEATURE_ENABLED", lambda v: parse_bool(v, settings.MARKET_DATA_CUSTOM_FEATURE_ENABLED))
    set_if("HARD_REJECT_SPREAD", lambda v: parse_float(v, settings.HARD_REJECT_SPREAD))
    set_if("REQUIRE_MARKET_QUALITY_HEALTHY", lambda v: parse_bool(v, settings.REQUIRE_MARKET_QUALITY_HEALTHY))
    set_if("DISABLE_CONFIDENCE_GE", lambda v: parse_int(v, settings.DISABLE_CONFIDENCE_GE))
    set_if("MIN_TOP_LEVEL_SIZE", lambda v: parse_float(v, settings.MIN_TOP_LEVEL_SIZE))
    set_if("ENTRY_REQUIRE_FRESH_BOOK", lambda v: parse_bool(v, settings.ENTRY_REQUIRE_FRESH_BOOK))
    set_if("ENTRY_MAX_BOOK_AGE_SECONDS", lambda v: parse_int(v, settings.ENTRY_MAX_BOOK_AGE_SECONDS))
    set_if("KILL_SWITCH_ENABLED", lambda v: parse_bool(v, settings.KILL_SWITCH_ENABLED))
    set_if("KILL_SWITCH_LOOKBACK_CLOSED", lambda v: parse_int(v, settings.KILL_SWITCH_LOOKBACK_CLOSED))
    set_if("KILL_SWITCH_MAX_REALIZED_LOSS", lambda v: parse_float(v, settings.KILL_SWITCH_MAX_REALIZED_LOSS))
    set_if("KILL_SWITCH_MIN_WINRATE", lambda v: parse_float(v, settings.KILL_SWITCH_MIN_WINRATE))
    set_if("KILL_SWITCH_COOLDOWN_SECONDS", lambda v: parse_int(v, settings.KILL_SWITCH_COOLDOWN_SECONDS))
    # Variant-specific env overrides
    set_if("MAX_SPREAD_PCT_VARIANT", lambda v: parse_float(v, settings.MAX_SPREAD_PCT_VARIANT))
    set_if("MIN_EDGE_CENTS_VARIANT", lambda v: parse_float(v, settings.MIN_EDGE_CENTS_VARIANT))
    set_if("MAX_ENTRY_PRICE_VARIANT", lambda v: parse_float(v, settings.MAX_ENTRY_PRICE_VARIANT))
    set_if("SUBSCRIBE_KEEPALIVE_SECONDS", lambda v: parse_int(v, getattr(settings, "SUBSCRIBE_KEEPALIVE_SECONDS", 180)))


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

