"""Bet sizing utilities — Kelly criterion and historical reversal rates."""

from dataclasses import dataclass

# Historical reversal rates from 570-market backtest (2 days)
REVERSAL_RATES: dict[int, float] = {
    2: 0.540,
    3: 0.579,
    4: 0.667,
    5: 0.824,
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
