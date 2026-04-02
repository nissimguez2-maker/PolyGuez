class Prompter:

    def momentum_confirmation(
        self,
        velocity: float,
        direction: str,
        yes_price: float,
        no_price: float,
        spread: float,
        elapsed_seconds: float,
        win_rate: float,
        recent_trades_summary: str,
        context_data: str,
        chainlink_price: float = 0.0,
        binance_chainlink_gap: float = 0.0,
        gap_direction: str = "unknown",
        price_to_beat: float = 0.0,
        clob_depth_summary: str = "",
        strike_delta: float = 0.0,
        terminal_probability: float = 0.0,
        terminal_edge: float = 0.0,
        binance_price: float = 0.0,
    ) -> str:
        strike_section = f"""
STRIKE ANALYSIS (primary signal):
- Price to Beat (strike): ${price_to_beat:.2f}
- Current Chainlink: ${chainlink_price:.2f}
- Strike delta: ${strike_delta:+.2f} ({"above" if strike_delta > 0 else "below"} strike)
- Terminal probability (selected side): {terminal_probability:.1%}
- Terminal edge: {terminal_edge:.4f}
NOTE: Terminal probability estimates the chance the current leading side wins at expiry.
Edge = terminal probability minus the token price you'd pay. Higher edge = more attractive entry."""

        oracle_section = ""
        if chainlink_price > 0:
            oracle_section = f"""
ORACLE GAP (key edge signal):
- Binance spot: ${binance_price:.2f} (leads)
- Chainlink oracle: ${chainlink_price:.2f} (follows with delay)
- Gap: ${binance_chainlink_gap:+.2f} ({"favors " + direction if (binance_chainlink_gap > 0) == (direction == "up") else "AGAINST " + direction})
- Gap trend: {gap_direction}
- Price to beat (market open Chainlink): ${price_to_beat:.2f}
- Chainlink vs price to beat: ${chainlink_price - price_to_beat:+.2f}
NOTE: Markets resolve against Chainlink, NOT Binance. The edge is the latency gap."""

        depth_section = ""
        if clob_depth_summary:
            depth_section = f"""
CLOB ORDER BOOK DEPTH:
{clob_depth_summary}
NOTE: Thin depth = higher slippage risk. Asymmetric depth may signal informed flow."""

        return f"""You are a risk-aware trading confirmation system for 5-minute BTC binary markets on Polymarket. The strategy uses late-window convergence: it waits until the outcome is statistically near-certain, then enters if the CLOB token price hasn't caught up.

A deterministic momentum signal has ALREADY fired. Your job is to CONFIRM or VETO.
{strike_section}

CURRENT STATE:
- BTC 30s velocity: {velocity:.6f} $/sec ({direction})
- YES token price: {yes_price:.4f} | NO token price: {no_price:.4f}
- CLOB spread: {spread:.4f}
- Time elapsed in market: {elapsed_seconds:.0f}s of 300s
- Rolling win rate (last 10): {win_rate:.1%}
{oracle_section}
{depth_section}
RECENT TRADE HISTORY:
{recent_trades_summary}

EXTERNAL CONTEXT:
{context_data}

RULES:
- The deterministic signal passed all conditions including: terminal probability > threshold, terminal edge > minimum, delta magnitude sufficient, and all v1 safety gates.
- The bot enters in the last 60 seconds when the outcome is statistically decided.
- If strike delta is large and stable, and terminal edge is significant, respond GO.
- If you see news suggesting an imminent reversal that could flip the outcome in the remaining seconds, respond NO-GO.
- If the oracle gap is narrowing rapidly (Chainlink catching up to Binance), the edge may shrink — consider REDUCE-SIZE.
- If depth is thin relative to position size, consider REDUCE-SIZE.
- If terminal probability is above 95% and edge is above 0.10, the case for GO is very strong.

Respond with EXACTLY one line in this format:
VERDICT: <GO|NO-GO|REDUCE-SIZE> | REASON: <one sentence>"""
