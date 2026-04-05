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
        conditions_met = sum([
            terminal_probability > 0.75,
            terminal_edge > 0.05,
            abs(strike_delta) > 10,
            spread < 0.05,
            abs(binance_chainlink_gap) > 5,
            velocity != 0,
            elapsed_seconds > 200,
            win_rate >= 0.5 or win_rate == 0,
        ])
        return (
            f"BTC 5-min binary option trade — direction: {direction.upper()}.\n"
            f"Binance BTC: ${binance_price:,.2f} | Chainlink: ${chainlink_price:,.2f} | "
            f"Strike (P2B): ${price_to_beat:,.2f}\n"
            f"Strike delta: ${strike_delta:+.2f} | Terminal prob: {terminal_probability:.1%} | "
            f"Edge: {terminal_edge:+.4f}\n"
            f"CLOB: YES={yes_price:.3f} NO={no_price:.3f} spread={spread:.4f}\n"
            f"Velocity: {velocity:+.6f} $/tick | Elapsed: {elapsed_seconds:.0f}s/300s\n"
            f"Binance-Chainlink gap: ${binance_chainlink_gap:+.2f}\n"
            f"Recent win rate: {win_rate:.0%} | Signal quality: {conditions_met}/8\n"
            f"Order book: {clob_depth_summary}\n"
            f"Should this trade execute?"
        )
