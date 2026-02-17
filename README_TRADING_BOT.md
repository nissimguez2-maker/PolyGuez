# Polymarket Trading Bot - Enhanced

Autonomous trading bot for Polymarket with risk management, resilience, and observability.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables (see below)
cp .env.example .env
# Edit .env with your keys

# Run tests
pytest tests/test_integration.py -v

# Start trading (paper mode by default)
python -m agents.application.trader_integrated
```

## Environment Variables

### Required
```bash
# API Keys
OPENAI_API_KEY=sk-...
POLYGON_WALLET_PRIVATE_KEY=0x...

# Optional: Anthropic fallback
ANTHROPIC_API_KEY=sk-ant-...
```

### Risk Management (Block A)
```bash
# Enable/disable all risk checks
RISK_ENABLED=1

# Position Sizing
MAX_RISK_PCT_PER_TRADE=2.0        # Max 2% equity per trade
MAX_TOTAL_EXPOSURE_PCT=15.0       # Max 15% total exposure

# Guardrails
DAILY_LOSS_LIMIT_PCT=5.0          # Stop trading after 5% daily loss
MAX_CONCURRENT_POSITIONS=5        # Max 5 open positions

# Fast Exit
MAX_SLIPPAGE_BPS=100              # Exit if 1% against entry
MAX_SPREAD_BPS=200                # Don't enter if spread > 2%
```

### Resilience (Block B)
```bash
# Enable/disable circuit breaker + retry
RESILIENCE_ENABLED=1

# Per-service thresholds (optional)
# Uses defaults if not set
```

### Telemetry (Block C)
```bash
# Enable metrics collection and HTTP server
TELEMETRY_ENABLED=1
METRICS_PORT=9090                 # Port for /metrics endpoint
```

### Model Selection (Block D)
```bash
# Primary and fallback models
DEFAULT_MODEL=gpt-4               # or gpt-3.5-turbo, claude-3-opus
FALLBACK_MODEL=gpt-3.5-turbo      # Used on 429/5xx errors
```

## How to Run

### 1. Basic (with all features)
```bash
export RISK_ENABLED=1
export RESILIENCE_ENABLED=1
export TELEMETRY_ENABLED=1
export DEFAULT_MODEL=gpt-3.5-turbo

python -m agents.application.trader_integrated
```

### 2. With Metrics Endpoint
```bash
export TELEMETRY_ENABLED=1
export METRICS_PORT=9090

python -m agents.application.trader_integrated &

# In another terminal:
curl http://localhost:9090/metrics       # Prometheus format
curl http://localhost:9090/metrics/json  # JSON format
curl http://localhost:9090/health        # Health check
```

### 3. Risk-Only Mode (no telemetry)
```bash
export RISK_ENABLED=1
export TELEMETRY_ENABLED=0
export RESILIENCE_ENABLED=0

python -m agents.application.trader_integrated
```

## How to Verify

### 1. Check Tests Pass
```bash
pytest tests/test_integration.py -v

# Expected output:
# test_integration.py::TestCircuitBreakerTransitions::test_closed_to_open_on_failures PASSED
# test_integration.py::TestCircuitBreakerTransitions::test_open_rejects_calls PASSED
# ...
```

### 2. Verify Metrics Endpoint
```bash
# Start bot
cd /root/.openclaw/workspace
python -c "from agents.application.trader_integrated import IntegratedTrader; t = IntegratedTrader()" &

# Check metrics
curl -s http://localhost:9090/metrics | head -20

# Expected output:
# # HELP trades_attempted_total Counter
# # TYPE trades_attempted_total counter
# trades_attempted_total 0
# ...
```

### 3. Verify Circuit Breaker
```bash
# Watch logs for circuit breaker messages
# After 3 API failures, should see:
# "Circuit polymarket is OPEN"

# Check circuit metrics:
curl -s http://localhost:9090/metrics/json | jq '.circuit_breakers'
```

### 4. Verify Risk Blocking
```bash
# Set very restrictive limits
export MAX_RISK_PCT_PER_TRADE=0.1
export DAILY_LOSS_LIMIT_PCT=0.01

# Run bot - should see:
# "[RISK] Trade BLOCKED: Position size too large..."
# "[RISK] Trade BLOCKED: Daily loss limit hit..."
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    IntegratedTrader                         │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Executor   │  │  RiskManager │  │   Metrics    │      │
│  │  (LLM calls) │  │  (Position   │  │  (Telemetry) │      │
│  │              │  │   sizing)    │  │              │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │               │
│  ┌──────▼───────┐  ┌──────▼───────┐        │               │
│  │Retry Handler │  │ Circuit      │        │               │
│  │(Exponential  │  │ Breaker      │        │               │
│  │ Backoff)     │  │(Fail-fast)   │        │               │
│  └──────┬───────┘  └──────┬───────┘        │               │
│         │                 │                 │               │
│  ┌──────▼─────────────────▼─────────────────▼───────┐      │
│  │              External APIs                       │      │
│  │  Polymarket  |  Gamma  |  OpenAI/Anthropic      │      │
│  └──────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

## File Changes

### New Files
- `agents/risk/` - Risk management (A)
- `agents/resilience/` - Circuit breaker + retry (B)
- `agents/telemetry/` - Metrics collection (C)
- `agents/llm/` - Model selection (D)
- `agents/application/executor_enhanced.py` - Integrated executor
- `agents/application/trader_integrated.py` - Full integration
- `tests/test_integration.py` - Unit tests

### Modified Files
- None (backwards compatible)

## Monitoring

### Key Metrics
| Metric | Description |
|--------|-------------|
| `trades_attempted_total` | Total trade attempts |
| `trades_placed_total` | Successfully executed |
| `trades_blocked_total` | Blocked by risk (with reason) |
| `trades_failed_total` | Failed after retries |
| `circuit_breaker_open_total` | Circuit breaker trips |
| `api_retries_total` | Retry attempts |
| `cycle_latency_ms` | End-to-end cycle time |

### Alerting Thresholds
- `daily_loss_pct > 5%` - Trading halted
- `circuit_breaker_open` - API issues
- `trades_failed_total` increasing - System problems

## Troubleshooting

### Circuit Breaker Keeps Opening
```bash
# Check API health
export RESILIENCE_ENABLED=0  # Temporarily disable
# Fix underlying issue
export RESILIENCE_ENABLED=1
```

### Too Many Trades Blocked
```bash
# Relax risk limits (adjust as needed)
export MAX_RISK_PCT_PER_TRADE=5.0
export MAX_TOTAL_EXPOSURE_PCT=25.0
```

### Metrics Not Showing
```bash
# Check telemetry enabled
export TELEMETRY_ENABLED=1
export METRICS_PORT=9090

# Verify port not in use
lsof -i :9090
```

## 5m-Ready Mode (Market Data + Execution)

For reliable 5-minute timeframe trading with WebSocket data and smart execution:

### Enable Market Data Features
```bash
# Core flags (all default OFF)
export WS_ENABLED=1              # Enable WebSocket market data
export L2_ENABLED=1              # Enable Level-2 orderbook
export EXECUTION_ENABLED=1       # Enable smart execution engine

# WebSocket config
export MARKET_DATA_HEALTH_PORT=9091  # Health endpoint port

# Liquidity thresholds
export MAX_SPREAD_BPS=100        # Max 1% spread
export MIN_DEPTH_1BP=1000        # Min $1000 at 1bp
export MIN_DEPTH_5BP=5000        # Min $5000 at 5bp
export MAX_BOOK_AGE_S=5          # Max 5s stale data

# Execution config
export EXEC_ORDER_TYPE=smart     # maker/taker/smart
export EXEC_MAX_SLIPPAGE_BPS=50  # Max 0.5% slippage
export EXEC_ICEBERG_THRESHOLD=1000  # Split orders >$1000
```

### Conservative Defaults (Recommended Start)
```bash
export WS_ENABLED=1
export L2_ENABLED=1
export EXECUTION_ENABLED=1
export MAX_SPREAD_BPS=200        # 2% (relaxed)
export MIN_DEPTH_1BP=500         # $500
export MIN_DEPTH_5BP=2000        # $2000
export MAX_BOOK_AGE_S=10         # 10s (relaxed)
```

### How to Run (5m Mode)
```bash
# 1. Set flags
export WS_ENABLED=1
export L2_ENABLED=1
export EXECUTION_ENABLED=1

# 2. Start bot
python -m agents.application.trader_market_data

# 3. Verify health
curl http://localhost:9091/market-data/health
curl http://localhost:9091/market-data/status

# 4. Check metrics
curl http://localhost:9090/metrics
```

### How to Verify
```bash
# WebSocket connected?
curl -s http://localhost:9091/market-data/health | jq '.websocket.connected'

# Subscriptions active?
curl -s http://localhost:9091/market-data/health | jq '.websocket.active_subscriptions'

# Quotes fresh?
curl -s http://localhost:9091/market-data/status | jq '.quotes'

# Execution working?
# Look for: [EXECUTION] Success: filled=$X @ $Y
```

### Fallback Behavior
If WS/L2 unavailable, bot automatically falls back to HTTP/Gamma:
- No crash
- Slower updates (polling)
- Less precise execution

## License

See LICENSE.md
