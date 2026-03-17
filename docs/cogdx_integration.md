# CogDx Integration: Reasoning Verification for Trading Agents

## Overview

This connector provides optional cognitive diagnostics for trading pipelines. Agents can verify their reasoning for logical fallacies and calibration issues before executing trades.

**Note:** This is an optional third-party integration. All verification is opt-in and the trading pipeline functions normally if the service is unavailable.

## Why This Matters

Prediction market agents make high-stakes decisions based on probabilistic reasoning. Common failure modes include:

- **Anchoring bias**: Over-weighting initial price as a signal
- **Confirmation bias**: Seeking evidence that confirms existing position
- **Overconfidence**: Stated certainty exceeding actual accuracy
- **Logical fallacies**: Invalid reasoning chains leading to incorrect conclusions

External verification can catch these issues before they become losses.

## Quick Start

```python
from agents.connectors.cogdx import verify_trade_reasoning

# In your trade pipeline
reasoning = agent.source_best_trade(market)

if verify_trade_reasoning(reasoning):
    polymarket.execute_market_order(market, amount)
else:
    print("Trade reasoning flagged - manual review recommended")
```

## Full Client Usage

```python
from agents.connectors.cogdx import CogDxClient

client = CogDxClient()

# Analyze reasoning for fallacies
result = client.analyze_reasoning("""
The market is trading at 0.65, but I believe the true probability is 0.80.
My research shows strong evidence for YES outcome.
Therefore I should buy YES at current price.
""")

print(result)
# {
#   "logical_validity": 0.85,
#   "status": "valid",
#   "flaws_detected": [],
#   "recommendations": ["No obvious fallacies detected"]
# }

# Pre-trade verification gate (fails closed on errors)
gate = client.verify_before_trade(reasoning, min_validity=0.7)

if gate["approved"]:
    execute_trade()
elif gate["recommendation"] == "review":
    flag_for_human_review()
else:
    skip_trade()
```

## Calibration Audits

Track prediction accuracy over time:

```python
predictions = [
    {"prompt": "Will X happen?", "response": "Yes (75%)", "confidence": 0.75},
    {"prompt": "Will Y happen?", "response": "No (60%)", "confidence": 0.60},
]

audit = client.calibration_audit(
    agent_id="my-polymarket-agent",
    predictions=predictions
)

print(audit["calibration_score"])  # 0.0-1.0, higher = better calibrated
```

## Environment Variables

```bash
# Wallet-based credits
COGDX_WALLET=0x...

# Or pass directly to client
client = CogDxClient(wallet="0x...")
```

## Safety Design

- **Fails closed**: If the API is unavailable, `verify_before_trade` returns `approved: False` (does not auto-approve unverified trades)
- **Optional**: The integration is entirely opt-in and can be disabled without affecting core trading logic
- **No data retention**: Reasoning traces are processed and discarded; not stored beyond the request
- **Graceful degradation**: If you choose not to use verification, trades proceed normally

## API Reference

Endpoint: `https://api.cerebratech.ai`

See API documentation for full endpoint details and authentication.
