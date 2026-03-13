# CogDx Integration: Reasoning Verification for Trading Agents

## Overview

This integration adds optional cognitive diagnostics to the Polymarket trading pipeline. Before executing trades, agents can verify their reasoning for logical fallacies and calibration issues.

## Why This Matters

Prediction market agents make high-stakes decisions based on probabilistic reasoning. Common failure modes include:

- **Anchoring bias**: Over-weighting initial price as a signal
- **Confirmation bias**: Seeking evidence that confirms existing position
- **Overconfidence**: Stated certainty exceeding actual accuracy
- **Logical fallacies**: Invalid reasoning chains leading to incorrect conclusions

CogDx provides external verification to catch these issues before they become losses.

## Quick Start

```python
from agents.connectors.cogdx import verify_trade_reasoning

# In your trade pipeline
reasoning = agent.source_best_trade(market)

if verify_trade_reasoning(reasoning, coupon="MERCURY-PILOT-2026"):
    polymarket.execute_market_order(market, amount)
else:
    print("Trade reasoning flagged - manual review recommended")
```

## Full Client Usage

```python
from agents.connectors.cogdx import CogDxClient

client = CogDxClient(coupon="MERCURY-PILOT-2026")

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

# Pre-trade verification gate
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
    # ... more predictions with actual outcomes
]

audit = client.calibration_audit(
    agent_id="my-polymarket-agent",
    predictions=predictions
)

print(audit["calibration_score"])  # 0.0-1.0, higher = better calibrated
```

## Environment Variables

```bash
# Option 1: Pilot coupon (free trial)
COGDX_COUPON=MERCURY-PILOT-2026

# Option 2: Wallet-based credits
COGDX_WALLET=0x...

# Option 3: Pass directly to client
client = CogDxClient(coupon="MERCURY-PILOT-2026")
```

## Pricing

| Endpoint | Cost |
|----------|------|
| `/reasoning_trace_analysis` | $0.03 |
| `/calibration_audit` | $0.06 |
| `/bias_scan` | $0.10 |

Free pilot: `MERCURY-PILOT-2026` provides $5 credit (~80 reasoning checks).

## API Reference

Full documentation: https://api.cerebratech.ai

## About Cerebratech

Cerebratech provides cognitive diagnostics for AI agents, built by computational cognitive scientists. Our tools help agents verify they're reasoning correctly before making consequential decisions.

Contact: cerebratech.eth | https://cerebratech.ai
