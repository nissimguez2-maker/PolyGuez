from __future__ import annotations
from typing import Optional, Union, List
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class Trade(BaseModel):
    id: int
    taker_order_id: str
    market: str
    asset_id: str
    side: str
    size: str
    fee_rate_bps: str
    price: str
    status: str
    match_time: str
    last_update: str
    outcome: str
    maker_address: str
    owner: str
    transaction_hash: str
    bucket_index: str
    maker_orders: list[str]
    type: str


class SimpleMarket(BaseModel):
    id: int
    question: str
    # start: str
    end: str
    description: str
    active: bool
    # deployed: Optional[bool]
    funded: bool
    # orderMinSize: float
    # orderPriceMinTickSize: float
    rewardsMinSize: float
    rewardsMaxSpread: float
    # volume: Optional[float]
    spread: float
    outcomes: str
    outcome_prices: str
    clob_token_ids: Optional[str]


class ClobReward(BaseModel):
    id: str  # returned as string in api but really an int?
    conditionId: str
    assetAddress: str
    rewardsAmount: float  # only seen 0 but could be float?
    rewardsDailyRate: int  # only seen ints but could be float?
    startDate: str  # yyyy-mm-dd formatted date string
    endDate: str  # yyyy-mm-dd formatted date string


class Tag(BaseModel):
    id: str
    label: Optional[str] = None
    slug: Optional[str] = None
    forceShow: Optional[bool] = None  # missing from current events data
    createdAt: Optional[str] = None  # missing from events data
    updatedAt: Optional[str] = None  # missing from current events data
    _sync: Optional[bool] = None


class PolymarketEvent(BaseModel):
    id: str  # "11421"
    ticker: Optional[str] = None
    slug: Optional[str] = None
    title: Optional[str] = None
    startDate: Optional[str] = None
    creationDate: Optional[str] = (
        None  # fine in market event but missing from events response
    )
    endDate: Optional[str] = None
    image: Optional[str] = None
    icon: Optional[str] = None
    active: Optional[bool] = None
    closed: Optional[bool] = None
    archived: Optional[bool] = None
    new: Optional[bool] = None
    featured: Optional[bool] = None
    restricted: Optional[bool] = None
    liquidity: Optional[float] = None
    volume: Optional[float] = None
    reviewStatus: Optional[str] = None
    createdAt: Optional[str] = None  # 2024-07-08T01:06:23.982796Z,
    updatedAt: Optional[str] = None  # 2024-07-15T17:12:48.601056Z,
    competitive: Optional[float] = None
    volume24hr: Optional[float] = None
    enableOrderBook: Optional[bool] = None
    liquidityClob: Optional[float] = None
    _sync: Optional[bool] = None
    commentCount: Optional[int] = None
    # markets: list[str, 'Market'] # forward reference Market defined below - TODO: double check this works as intended
    markets: Optional[list[Market]] = None
    tags: Optional[list[Tag]] = None
    cyom: Optional[bool] = None
    showAllOutcomes: Optional[bool] = None
    showMarketImages: Optional[bool] = None


class Market(BaseModel):
    id: int
    question: Optional[str] = None
    conditionId: Optional[str] = None
    slug: Optional[str] = None
    resolutionSource: Optional[str] = None
    endDate: Optional[str] = None
    liquidity: Optional[float] = None
    startDate: Optional[str] = None
    image: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    outcome: Optional[list] = None
    outcomePrices: Optional[list] = None
    volume: Optional[float] = None
    active: Optional[bool] = None
    closed: Optional[bool] = None
    marketMakerAddress: Optional[str] = None
    createdAt: Optional[str] = None  # date type worth enforcing for dates?
    updatedAt: Optional[str] = None
    new: Optional[bool] = None
    featured: Optional[bool] = None
    submitted_by: Optional[str] = None
    archived: Optional[bool] = None
    resolvedBy: Optional[str] = None
    restricted: Optional[bool] = None
    groupItemTitle: Optional[str] = None
    groupItemThreshold: Optional[int] = None
    questionID: Optional[str] = None
    enableOrderBook: Optional[bool] = None
    orderPriceMinTickSize: Optional[float] = None
    orderMinSize: Optional[int] = None
    volumeNum: Optional[float] = None
    liquidityNum: Optional[float] = None
    endDateIso: Optional[str] = None  # iso format date = None
    startDateIso: Optional[str] = None
    hasReviewedDates: Optional[bool] = None
    volume24hr: Optional[float] = None
    clobTokenIds: Optional[list] = None
    umaBond: Optional[int] = None  # returned as string from api?
    umaReward: Optional[int] = None  # returned as string from api?
    volume24hrClob: Optional[float] = None
    volumeClob: Optional[float] = None
    liquidityClob: Optional[float] = None
    acceptingOrders: Optional[bool] = None
    negRisk: Optional[bool] = None
    commentCount: Optional[int] = None
    _sync: Optional[bool] = None
    events: Optional[list[PolymarketEvent]] = None
    ready: Optional[bool] = None
    deployed: Optional[bool] = None
    funded: Optional[bool] = None
    deployedTimestamp: Optional[str] = None  # utc z datetime string
    acceptingOrdersTimestamp: Optional[str] = None  # utc z datetime string,
    cyom: Optional[bool] = None
    competitive: Optional[float] = None
    pagerDutyNotificationEnabled: Optional[bool] = None
    reviewStatus: Optional[str] = None  # deployed, draft, etc.
    approved: Optional[bool] = None
    clobRewards: Optional[list[ClobReward]] = None
    rewardsMinSize: Optional[int] = (
        None  # would make sense to allow float but we'll see
    )
    rewardsMaxSpread: Optional[float] = None
    spread: Optional[float] = None


class ComplexMarket(BaseModel):
    id: int
    condition_id: str
    question_id: str
    tokens: Union[str, str]
    rewards: str
    minimum_order_size: str
    minimum_tick_size: str
    description: str
    category: str
    end_date_iso: str
    game_start_time: str
    question: str
    market_slug: str
    min_incentive_size: str
    max_incentive_spread: str
    active: bool
    closed: bool
    seconds_delay: int
    icon: str
    fpmm: str
    name: str
    description: Union[str, None] = None
    price: float
    tax: Union[float, None] = None


class SimpleEvent(BaseModel):
    id: int
    ticker: str
    slug: str
    title: str
    description: str
    end: str
    active: bool
    closed: bool
    archived: bool
    restricted: bool
    new: bool
    featured: bool
    restricted: bool
    markets: str


class Source(BaseModel):
    id: Optional[str]
    name: Optional[str]


class Article(BaseModel):
    source: Optional[Source]
    author: Optional[str]
    title: Optional[str]
    description: Optional[str]
    url: Optional[str]
    urlToImage: Optional[str]
    publishedAt: Optional[str]
    content: Optional[str]


# ---------------------------------------------------------------------------
# PolyGuez Momentum — new models
# ---------------------------------------------------------------------------

class PolyGuezConfig(BaseModel):
    # Capital & sizing
    max_capital_pct: float = Field(default=0.10, description="Max capital at risk as fraction of USDC balance")
    min_capital_floor: float = Field(default=3.0, description="Minimum capital floor in USDC")
    position_size_pct: float = Field(default=0.30, description="Position size as fraction of max capital at risk")

    # Risk
    max_daily_loss: Optional[float] = Field(default=None, description="Override daily loss limit in USDC (None = auto from capital)")
    max_open_positions: int = Field(default=1)

    # Signal thresholds
    velocity_threshold: float = Field(default=0.05, description="Min BTC price velocity magnitude ($/sec)")
    min_edge: float = Field(default=0.03, description="Min difference between fair value estimate and CLOB price")
    max_spread: float = Field(default=0.10, description="Max CLOB spread to allow entry")
    reversal_threshold: float = Field(default=0.08, description="Velocity reversal magnitude for emergency exit")

    # Entry window edge multipliers
    early_window_seconds: int = Field(default=60)
    mid_window_seconds: int = Field(default=150)
    early_edge_multiplier: float = Field(default=1.0)
    mid_edge_multiplier: float = Field(default=1.5)
    late_edge_multiplier: float = Field(default=2.5)

    # Cooldown
    cooldown_win_rate_no_cooldown: float = Field(default=0.60, description="Win rate above which no cooldown after win")
    cooldown_win_rate_short: float = Field(default=0.50, description="Win rate above which 1 cycle cooldown after loss")
    cooldown_cycles_short: int = Field(default=1)
    cooldown_cycles_long: int = Field(default=2)
    cooldown_tightened_multiplier: float = Field(default=1.5, description="Multiplier for velocity/edge after losing streak")
    cooldown_startup_trades: int = Field(default=5, description="Conservative mode until this many trades")

    # LLM
    llm_timeout: float = Field(default=15.0, description="LLM confirmation timeout in seconds")
    llm_enabled: bool = Field(default=True, description="Enable LLM confirmation layer")
    llm_provider: str = Field(default="openai", description="Active LLM provider: openai, anthropic, groq")
    llm_model_openai: str = Field(default="gpt-4o-mini")
    llm_model_anthropic: str = Field(default="claude-3-5-haiku-20241022")
    llm_model_groq: str = Field(default="llama-3.1-70b-versatile")

    # Data providers
    data_providers: List[str] = Field(default=["news", "tavily"], description="Enabled data provider names")
    data_provider_timeout: float = Field(default=3.0, description="Per-provider fetch timeout in seconds")

    # Market discovery
    market_slug_pattern: str = Field(default="btc-updown-5m", description="Slug pattern to match 5-min BTC markets")
    market_question_pattern: str = Field(default="", description="Optional question regex pattern for market matching")

    # CLOB polling
    clob_poll_interval: float = Field(default=1.0, description="Seconds between CLOB orderbook polls")

    # Mode: dry-run, paper, live
    mode: str = Field(default="dry-run")

    # BTC feed
    binance_ws_url: str = Field(default="wss://stream.binance.com:9443/ws/btcusdt@trade")
    coinbase_ws_url: str = Field(default="wss://ws-feed.exchange.coinbase.com")
    btc_feed_connect_timeout: float = Field(default=5.0)
    btc_buffer_min_seconds: float = Field(default=30.0)

    # Dashboard
    dashboard_secret: str = Field(default="", description="Shared secret for dashboard auth")


class TradeRecord(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    market_id: str = ""
    market_question: str = ""
    side: str = ""  # YES or NO
    entry_price: float = 0.0
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    duration_seconds: Optional[float] = None
    signal_strength: Optional[float] = None
    llm_verdict: str = ""  # GO, NO-GO, REDUCE-SIZE, timeout-default, disabled
    llm_reason: str = ""
    llm_provider: str = ""
    outcome: str = ""  # win, loss, skipped, emergency-exit
    reason: str = ""


class SignalState(BaseModel):
    btc_velocity: float = 0.0
    btc_price: float = 0.0
    yes_price: float = 0.0
    no_price: float = 0.0
    spread: float = 0.0
    elapsed_seconds: float = 0.0
    direction: str = ""  # up or down
    estimated_fair_value: float = 0.0
    edge: float = 0.0
    required_edge: float = 0.0

    # Per-condition booleans
    velocity_ok: bool = False
    edge_ok: bool = False
    spread_ok: bool = False
    no_position: bool = False
    cooldown_ok: bool = False
    daily_loss_ok: bool = False
    balance_ok: bool = False
    position_limit_ok: bool = False

    @property
    def all_conditions_met(self) -> bool:
        return all([
            self.velocity_ok, self.edge_ok, self.spread_ok,
            self.no_position, self.cooldown_ok, self.daily_loss_ok,
            self.balance_ok, self.position_limit_ok,
        ])


class PositionState(BaseModel):
    side: str = ""  # YES or NO
    entry_price: float = 0.0
    entry_time: str = ""
    market_id: str = ""
    token_id: str = ""
    size_usdc: float = 0.0


class RollingStats(BaseModel):
    trades: List[TradeRecord] = Field(default_factory=list)
    daily_pnl: float = 0.0
    daily_pnl_reset_utc: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    cooldown_until: Optional[str] = None  # ISO timestamp or None
    max_capital_at_risk: float = 0.0  # recalculated each cycle

    @property
    def last_n_trades(self) -> List[TradeRecord]:
        return self.trades[-10:] if self.trades else []

    @property
    def win_rate(self) -> float:
        recent = self.last_n_trades
        if not recent:
            return 0.0
        wins = sum(1 for t in recent if t.outcome == "win")
        return wins / len(recent)

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades if t.pnl is not None)

    @property
    def total_trades(self) -> int:
        return len([t for t in self.trades if t.outcome in ("win", "loss", "emergency-exit")])

    @property
    def total_wins(self) -> int:
        return len([t for t in self.trades if t.outcome == "win"])

    @property
    def total_losses(self) -> int:
        return len([t for t in self.trades if t.outcome in ("loss", "emergency-exit")])

    @property
    def total_skips(self) -> int:
        return len([t for t in self.trades if t.outcome == "skipped"])

    @property
    def biggest_win(self) -> float:
        wins = [t.pnl for t in self.trades if t.pnl is not None and t.pnl > 0]
        return max(wins) if wins else 0.0

    @property
    def biggest_loss(self) -> float:
        losses = [t.pnl for t in self.trades if t.pnl is not None and t.pnl < 0]
        return min(losses) if losses else 0.0


class DashboardSnapshot(BaseModel):
    # Status
    mode: str = "dry-run"
    btc_feed_connected: bool = False
    clob_connected: bool = False
    gamma_connected: bool = False
    usdc_balance: float = 0.0
    max_capital_at_risk: float = 0.0
    position_size_ceiling: float = 0.0
    daily_pnl: float = 0.0
    killed: bool = False
    kill_timestamp: Optional[str] = None

    # Live market
    current_market_question: str = ""
    current_market_expiry: Optional[str] = None
    btc_price: float = 0.0
    btc_velocity: float = 0.0
    btc_direction: str = ""
    yes_price: float = 0.0
    no_price: float = 0.0
    clob_spread: float = 0.0
    entry_window_elapsed: float = 0.0
    entry_window_total: float = 300.0

    # Signal
    signal: Optional[SignalState] = None

    # LLM
    llm_verdict: str = ""
    llm_reason: str = ""
    llm_response_time: Optional[float] = None

    # Position
    position: Optional[PositionState] = None
    unrealized_pnl: float = 0.0
    time_to_expiry: float = 0.0

    # Stats
    rolling_stats: Optional[RollingStats] = None
    cooldown_active: bool = False
    cooldown_remaining_seconds: float = 0.0

    # Config (for the config panel)
    config: Optional[PolyGuezConfig] = None
