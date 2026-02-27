"""Bet sizing utilities — Kelly criterion and historical reversal rates."""

from dataclasses import dataclass

# Measured reversal rates — 2-year Binance 5m BTCUSDT backtest (210,240 candles)
# 95% Wilson CI: ±0.3% at trigger=2, ±0.6% at trigger=4, ±3.0% at trigger=8
# Previous values (from 570-market, 2-day Polymarket sample) were significantly
# overstated: trigger=4 was 0.667, trigger=5 was 0.824 — both now confirmed wrong.
REVERSAL_RATES: dict[int, float] = {
    2: 0.518,
    3: 0.527,
    4: 0.537,
    5: 0.533,
    6: 0.540,
    7: 0.550,
    8: 0.562,
}


@dataclass
class BetDecision:
    """Result of evaluating a strategy signal for execution."""

    should_bet: bool
    direction: str  # "up" or "down" — the side to bet ON
    size: float  # USD amount
    confidence: float  # estimated win probability (0-1)
    reason: str


def kelly_size(
    confidence: float,
    odds: float,
    bankroll: float,
    fraction: float = 0.25,
) -> float:
    """Calculate bet size using fractional Kelly criterion.

    Args:
        confidence: Estimated win probability (0-1)
        odds: Decimal odds (e.g., 2.0 for even money at 50 cents)
        bankroll: Current bankroll in USD
        fraction: Kelly fraction (0.25 = quarter Kelly, conservative)

    Returns:
        Recommended bet size in USD (minimum $1 if positive edge)
    """
    if confidence <= 0 or odds <= 1:
        return 0

    # Kelly formula: f* = (bp - q) / b
    # where b = odds - 1, p = win prob, q = 1 - p
    b = odds - 1
    p = confidence
    q = 1 - p

    kelly = (b * p - q) / b
    if kelly <= 0:
        return 0

    return max(1, round(bankroll * kelly * fraction, 2))
