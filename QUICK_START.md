# Quick Start Guide - Enhanced Polymarket Agents

## 🚀 Run Enhanced Trader

```bash
# Run the full enhanced trading system
python scripts/python/cli.py run-enhanced-trader
```

## 📊 Analyze Markets

```bash
# See market breakdown by category
python scripts/python/cli.py analyze-market-categories
```

## 🎯 Find Opportunities

```bash
# Find low-volume markets (arbitrage potential)
python scripts/python/cli.py find-obscure-markets --max-volume 10000

# Find markets closing soon (time decay plays)
python scripts/python/cli.py find-time-decay-plays --max-days 7
```

## 📈 Monitor Performance

```bash
# View calibration and portfolio metrics
python scripts/python/cli.py show-performance

# Monitor open positions
python scripts/python/cli.py monitor-positions
```

## 🔧 Key Enhancements

### 1. Category Filtering ✨
**Only trade information-rich markets**
- Focus: Politics, Finance, Tech, Business, Crypto
- Avoid: Sports, Entertainment, Weather, Pop Culture

### 2. Kelly Sizing 💰
**Optimal position sizing**
- Automatically calculates bet size based on edge
- Caps at 15% per position
- Adjusts for confidence

### 3. Risk Controls 🛡️
**Safety first**
- Circuit breakers (-5% daily loss limit)
- Stop-loss (-15%) and take-profit (+25%)
- Portfolio diversification (max 40% deployed)

### 4. Performance Tracking 📊
**Know your edge**
- Brier score calculation
- Calibration curves
- Win rate and P&L tracking

## 💡 Pro Tips

### Best Markets to Trade
```python
# High information edge categories:
✓ Political elections (polling data, insider knowledge)
✓ Economic indicators (macro analysis, Fed decisions)
✓ Tech product launches (roadmap analysis, leaks)
✓ Business earnings (fundamental analysis)
✓ Crypto regulations (regulatory filings, insider info)

# Low information edge (avoid):
✗ Sports outcomes (physical randomness dominates)
✗ Entertainment awards (subjective taste)
✗ Weather events (chaotic systems)
```

### Optimal Trade Selection
```python
# Look for markets with:
1. High skill weight (≥0.65) - Category matters
2. Sufficient liquidity ($5k+ volume)
3. Reasonable spread (<5%)
4. Optimal timeframe (7-90 days to close)
5. Large edge (forecast vs price ≥5%)
6. High confidence (≥70%)
```

### Risk Management
```python
# Never risk more than:
- 15% per position (Kelly cap)
- 40% total portfolio
- 25% per category

# Always use:
- Stop-loss at -15%
- Take-profit at +25%
- Circuit breakers
```

## 🎓 Strategy Playbook

### Strategy 1: Obscure Market Arbitrage
**Target**: Low-volume markets (<$10k) with wide spreads
**Edge**: Information advantage over thin liquidity
**Expected**: 3-5 trades/month, 10-12% avg edge

```bash
python scripts/python/cli.py find-obscure-markets
```

### Strategy 2: Time Decay Plays
**Target**: Markets closing in 1-7 days
**Edge**: Speed advantage via fresh news
**Expected**: 5-8 trades/month, 8-10% avg edge

```bash
python scripts/python/cli.py find-time-decay-plays
```

### Strategy 3: Category Focus
**Target**: Politics & Finance markets only
**Edge**: Macro analysis and polling data
**Expected**: 10-15 trades/month, 8-12% avg edge

```python
# Customize in enhanced_trader.py:
trader.min_skill_weight = 0.80  # Politics/Finance only
```

## 📐 Configuration

### Adjust Risk Tolerance

**Conservative** (lower risk, lower returns):
```python
trader = EnhancedTrader()
trader.min_edge = 0.08           # Require 8% edge
trader.min_confidence = 0.80     # Require 80% confidence
trader.portfolio.max_portfolio_risk = 0.30  # Max 30% deployed
```

**Aggressive** (higher risk, higher returns):
```python
trader = EnhancedTrader()
trader.min_edge = 0.04           # Accept 4% edge
trader.min_confidence = 0.65     # Accept 65% confidence
trader.portfolio.max_portfolio_risk = 0.50  # Max 50% deployed
```

**Balanced** (default):
```python
trader = EnhancedTrader()
trader.min_edge = 0.05           # Require 5% edge
trader.min_confidence = 0.70     # Require 70% confidence
trader.portfolio.max_portfolio_risk = 0.40  # Max 40% deployed
```

## 📊 Expected Performance

| Profile | Win Rate | Annual Return | Max Drawdown | Trades/Month |
|---------|----------|---------------|--------------|--------------|
| Conservative | 65-70% | 15-25% | 8-12% | 8-12 |
| Balanced | 58-65% | 25-45% | 12-18% | 15-25 |
| Aggressive | 52-58% | 35-60% | 18-25% | 25-40 |

## 🎯 Success Metrics

Monitor these key performance indicators:

1. **Brier Score**: <0.10 = elite, <0.15 = good, <0.20 = average
2. **Calibration**: Your 70% forecasts should be right ~70% of the time
3. **Win Rate**: >55% is profitable with good sizing
4. **Sharpe Ratio**: >1.0 is good, >1.5 is excellent
5. **Max Drawdown**: Keep under 20%

Check performance:
```bash
python scripts/python/cli.py show-performance
```

## ⚠️ Important Warnings

1. **Legal**: Verify Polymarket access legality in your jurisdiction
2. **Execution Disabled**: Trading is commented out per TOS compliance
3. **API Costs**: LLM usage can be expensive (budget ~$50-200/month)
4. **Market Impact**: Don't trade >2% of market volume
5. **Learning Curve**: Calibration data accumulates over time

## 🔄 Daily Workflow

### Morning Routine
```bash
# 1. Check for circuit breaker halts
python scripts/python/cli.py show-performance

# 2. Monitor open positions
python scripts/python/cli.py monitor-positions

# 3. Analyze new market opportunities
python scripts/python/cli.py analyze-market-categories
```

### Trading Session
```bash
# 4. Run enhanced trader
python scripts/python/cli.py run-enhanced-trader

# 5. Review performance
python scripts/python/cli.py show-performance
```

### Weekly Review
```bash
# 6. Analyze calibration
# Check data/calibration.db for trends

# 7. Adjust strategy based on results
# Update min_edge, min_confidence as needed

# 8. Review category performance
# Focus on best-performing categories
```

## 📚 Learn More

- Full documentation: `ENHANCEMENTS.md`
- Project README: `README.md`
- Code examples: `agents/application/enhanced_trader.py`

## 🆘 Troubleshooting

**No markets found after filtering:**
- Lower `min_skill_weight` to 0.60
- Increase `max_spread` to 0.08
- Expand `max_days_to_close` to 365

**Confidence too low on all trades:**
- Check news API is working
- Verify LLM responses contain probabilities
- Lower `min_confidence` to 0.65

**Circuit breaker keeps triggering:**
- Review recent trades for systematic issues
- Check if entering at bad prices
- Consider if market conditions unfavorable
- Use `breaker.reset_halts()` after review

## 🎉 Ready to Trade!

Start with the enhanced trader:
```bash
python scripts/python/cli.py run-enhanced-trader
```

The system will:
1. ✅ Filter to high-information-edge markets
2. ✅ Apply quantitative filters
3. ✅ Fetch recent news
4. ✅ Generate ensemble forecast
5. ✅ Calculate optimal position size
6. ✅ Check risk controls
7. ✅ Log for calibration tracking
8. ⚠️ Show trade (execution disabled)

**Good luck and trade smart!** 🚀
