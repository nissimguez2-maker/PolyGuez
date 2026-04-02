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
            True,  # balance_ok (already checked)
            True,  # cooldown_ok (already checked)
        ])
        return (
            f"Trade signal: {direction}. "
            f"Conditions met: {conditions_met}/10. "
            f"Price above strike by ${strike_delta:+.2f}. "
            f"Terminal prob {terminal_probability:.0%}, edge {terminal_edge:+.3f}. "
            f"Approve? Reply GO or NO only."
        )
