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
    end: str
    description: str
    active: bool
    funded: bool
    rewardsMinSize: float
    rewardsMaxSpread: float
    spread: float
    outcomes: str
    outcome_prices: str
    clob_token_ids: Optional[str]


class ClobReward(BaseModel):
    id: str
    conditionId: str
    assetAddress: str
    rewardsAmount: float
    rewardsDailyRate: int
    startDate: str
    endDate: str


class Tag(BaseModel):
    id: str
    label: Optional[str] = None
    slug: Optional[str] = None
    forceShow: Optional[bool] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    _sync: Optional[bool] = None


class PolymarketEvent(BaseModel):
    id: str
    ticker: Optional[str] = None
    slug: Optional[str] = None
    title: Optional[str] = None
    startDate: Optional[str] = None
    creationDate: Optional[str] = None
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
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    competitive: Optional[float] = None
    volume24hr: Optional[float] = None
    enableOrderBook: Optional[bool] = None
    liquidityClob: Optional[float] = None
    _sync: Optional[bool] = None
    commentCount: Optional[int] = None
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
    createdAt: Optional[str] = None
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
    endDateIso: Optional[str] = None
    startDateIso: Optional[str] = None
    hasReviewedDates: Optional[bool] = None
    volume24hr: Optional[float] = None
    clobTokenIds: Optional[list] = None
    umaBond: Optional[int] = None
    umaReward: Optional[int] = None
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
    deployedTimestamp: Optional[str] = None
    acceptingOrdersTimestamp: Optional[str] = None
    cyom: Optional[bool] = None
    competitive: Optional[float] = None
    pagerDutyNotificationEnabled: Optional[bool] = None
    reviewStatus: Optional[str] = None
    approved: Optional[bool] = None
    clobRewards: Optional[list[ClobReward]] = None
    rewardsMinSize: Optional[int] = None
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
# PolyGuez Momentum — models
# ---------------------------------------------------------------------------

class PolyGuezConfig(BaseModel):
    max_capital_pct: float = Field(default=0.10)
    min_capital_floor: float = Field(default=3.0)
    position_size_pct: float = Field(default=0.30)
    max_daily_loss: Optional[float] = Field(default=None)
    max_open_positions: int = Field(default=1)
    velocity_threshold: float = Field(default=0.05)
    min_edge: float = Field(default=0.03)
    max_spread: float = Field(default=0.10)
    min_oracle_gap: float = Field(default=15.0)

    # FIX 1: Split reversal_threshold into two fields
    reversal_velocity_threshold: float = Field(default=0.08, description="$/sec for velocity-based emergency exit fallback")
    reversal_chainlink_threshold: float = Field(default=50.0, description="$ of BTC price move for Chainlink-based emergency exit")

    # FIX 2: CLOB depth hard gate
    min_clob_depth: float = Field(default=50.0, description="Min ask-side depth in token units within $0.05 of best price")

    # FIX 3: Settlement retry
    settlement_max_retries: int = Field(default=4)
    settlement_retry_delay: float = Field(default=3.0)

    early_window_seconds: int = Field(default=60)
    mid_window_seconds: int = Field(default=150)
    early_edge_multiplier: float = Field(default=1.0)
    mid_edge_multiplier: float = Field(default=1.5)
    late_edge_multiplier: float = Field(default=2.5)
    cooldown_win_rate_no_cooldown: float = Field(default=0.60)
    cooldown_win_rate_short: float = Field(default=0.50)
    cooldown_cycles_short: int = Field(default=1)
    cooldown_cycles_long: int = Field(default=2)
    cooldown_tightened_multiplier: float = Field(default=1.5)
    cooldown_startup_trades: int = Field(default=5)
    llm_timeout: float = Field(default=2.0)
    llm_enabled: bool = Field(default=True)
    llm_provider: str = Field(default="groq")
    llm_model_openai: str = Field(default="gpt-4o-mini")
    llm_model_anthropic: str = Field(default="claude-3-5-haiku-20241022")
    llm_model_groq: str = Field(default="llama-3.3-70b-versatile")
    data_providers: List[str] = Field(default=["news", "tavily"])
    data_provider_timeout: float = Field(default=3.0)
    market_slug_pattern: str = Field(default="btc-updown-5m")
    market_question_pattern: str = Field(default="Bitcoin Up or Down")
    clob_poll_interval: float = Field(default=0.35)
    mode: str = Field(default="dry-run")
    rtds_ws_url: str = Field(default="wss://ws-live-data.polymarket.com")
    binance_ws_url: str = Field(default="wss://stream.binance.com:9443/ws/btcusdt@trade")
    coinbase_ws_url: str = Field(default="wss://ws-feed.exchange.coinbase.com")
    btc_feed_connect_timeout: float = Field(default=5.0)
    btc_buffer_min_seconds: float = Field(default=10.0)
    clob_ws_enabled: bool = Field(default=False, description="Enable CLOB WebSocket (experimental, may get rejected)")

    # FIX 4: Chainlink on-chain fallback
    chainlink_onchain_fallback: bool = Field(default=True)
    chainlink_onchain_poll_interval: float = Field(default=2.0)
    chainlink_onchain_rpc_url: str = Field(default="https://polygon.drpc.org")

    # P2B parsing hardening
    p2b_sanity_min: float = Field(default=10000.0, description="Min plausible BTC price for P2B")
    p2b_sanity_max: float = Field(default=500000.0, description="Max plausible BTC price for P2B")
    p2b_consecutive_failure_halt: int = Field(default=50, description="Halt after N consecutive P2B parse failures")
    min_terminal_edge: float = Field(default=0.05, description="Min edge at terminal probability for entry")
    conviction_min_delta: float = Field(default=40.0, description="Min $ delta between Chainlink and P2B for conviction")

    dashboard_secret: str = Field(default="")


class TradeRecord(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    market_id: str = ""
    market_question: str = ""
    side: str = ""
    entry_price: float = 0.0
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    duration_seconds: Optional[float] = None
    signal_strength: Optional[float] = None
    llm_verdict: str = ""
    llm_reason: str = ""
    llm_provider: str = ""
    outcome: str = ""  # win, loss, skipped, emergency-exit, pending
    reason: str = ""


class SignalState(BaseModel):
    btc_velocity: float = 0.0
    btc_price: float = 0.0
    chainlink_price: float = 0.0
    binance_chainlink_gap: float = 0.0
    yes_price: float = 0.0
    no_price: float = 0.0
    spread: float = 0.0
    elapsed_seconds: float = 0.0
    direction: str = ""  # delta-based (v2 primary)
    momentum_direction: str = ""  # velocity-based (v1 legacy)
    estimated_fair_value: float = 0.0
    edge: float = 0.0
    required_edge: float = 0.0
    gap_favors_position: bool = False
    velocity_ok: bool = False
    oracle_gap_ok: bool = False
    clob_mispricing_ok: bool = False
    edge_ok: bool = False
    spread_ok: bool = False
    no_position: bool = False
    cooldown_ok: bool = False
    daily_loss_ok: bool = False
    balance_ok: bool = False
    position_limit_ok: bool = False
    depth_ok: bool = False  # FIX 2
    price_feed_ok: bool = True  # FIX 4: stale feed hard blocker

    # P2B enrichment fields
    p2b_source: str = ""
    p2b_value: Optional[float] = None
    p2b_cross_check_passed: Optional[bool] = None
    p2b_cross_check_divergence: Optional[float] = None
    strike_delta: float = 0.0
    terminal_probability: float = 0.0
    terminal_edge: float = 0.0
    terminal_edge_ok: bool = False
    delta_magnitude_ok: bool = False

    @property
    def all_conditions_met(self) -> bool:
        """V2 entry conditions — phase/strike/edge based."""
        return all([
            # Feed health gate
            self.price_feed_ok,          # At least one price source alive
            # V2 core gates
            self.terminal_edge_ok,       # Terminal probability edge above minimum
            self.delta_magnitude_ok,     # Strike delta large enough for conviction
            self.edge_ok,                # Fair value edge (now based on terminal prob)
            # Execution gates
            self.spread_ok,              # CLOB spread acceptable
            self.depth_ok,               # Order book has sufficient depth
            # Risk gates
            self.no_position,            # Not already in a position
            self.cooldown_ok,            # Not in cooldown
            self.daily_loss_ok,          # Haven't hit daily loss limit
            self.balance_ok,             # Have enough capital
            self.position_limit_ok,      # Under position limit
        ])


class PositionState(BaseModel):
    side: str = ""
    entry_price: float = 0.0
    entry_time: str = ""
    market_id: str = ""
    token_id: str = ""
    size_usdc: float = 0.0
    price_to_beat: float = 0.0


class RollingStats(BaseModel):
    trades: List[TradeRecord] = Field(default_factory=list)
    daily_pnl: float = 0.0
    daily_pnl_reset_utc: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    cooldown_until: Optional[str] = None
    max_capital_at_risk: float = 0.0
    simulated_balance: float = 100.0  # Persistent dry-run balance, starts at $100
    p2b_skips: int = 0

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
    current_market_question: str = ""
    current_market_expiry: Optional[str] = None
    btc_price: float = 0.0
    chainlink_price: float = 0.0
    chainlink_source: str = ""  # FIX 4
    binance_chainlink_gap: float = 0.0
    gap_direction: str = ""
    price_to_beat: float = 0.0
    chainlink_vs_price_to_beat: float = 0.0
    btc_velocity: float = 0.0
    btc_direction: str = ""
    yes_price: float = 0.0
    no_price: float = 0.0
    clob_spread: float = 0.0
    clob_depth: float = 0.0  # FIX 2
    entry_window_elapsed: float = 0.0
    entry_window_total: float = 300.0
    signal: Optional[SignalState] = None
    llm_verdict: str = ""
    llm_reason: str = ""
    llm_response_time: Optional[float] = None
    position: Optional[PositionState] = None
    unrealized_pnl: float = 0.0
    time_to_expiry: float = 0.0
    rolling_stats: Optional[RollingStats] = None
    cooldown_active: bool = False
    cooldown_remaining_seconds: float = 0.0
    # P2B dashboard fields
    p2b_source: str = ""
    p2b_parse_success: bool = False
    p2b_cross_check_passed: Optional[bool] = None
    p2b_cross_check_divergence: Optional[float] = None
    strike_delta: float = 0.0
    terminal_probability: float = 0.0
    terminal_edge: float = 0.0
    p2b_consecutive_failures: int = 0
    config: Optional[PolyGuezConfig] = None
