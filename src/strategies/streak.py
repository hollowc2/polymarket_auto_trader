"""Streak reversal strategy logic."""

from dataclasses import dataclass


@dataclass
class Signal:
    """Trading signal from the strategy."""

    should_bet: bool
    direction: str  # "up" or "down" — the side to bet ON
    streak_length: int
    streak_direction: str  # what the streak was (opposite of bet direction)
    confidence: float  # estimated win probability based on historical data
    reason: str


# Historical reversal rates from 570-market backtest (2 days)
REVERSAL_RATES = {
    2: 0.540,
    3: 0.579,
    4: 0.667,
    5: 0.824,
}


def detect_streak(outcomes: list[str]) -> tuple[int, str]:
    """
    Detect the current streak at the end of the outcomes list.
    Returns (streak_length, streak_direction).
    """
    if not outcomes:
        return 0, ""

    current = outcomes[-1]
    streak = 1

    for i in range(len(outcomes) - 2, -1, -1):
        if outcomes[i] == current:
            streak += 1
        else:
            break

    return streak, current


def evaluate(outcomes: list[str], trigger: int = 4) -> Signal:
    """
    Evaluate whether to place a bet based on recent outcomes.

    Args:
        outcomes: List of recent outcomes ("up"/"down"), oldest first
        trigger: Minimum streak length to trigger a bet

    Returns:
        Signal with bet recommendation
    """
    streak_len, streak_dir = detect_streak(outcomes)

    if streak_len < trigger:
        return Signal(
            should_bet=False,
            direction="",
            streak_length=streak_len,
            streak_direction=streak_dir,
            confidence=0,
            reason=f"Streak {streak_len} < trigger {trigger}",
        )

    # Bet AGAINST the streak (reversal)
    bet_direction = "down" if streak_dir == "up" else "up"

    # Use historical reversal rate, cap at streak 5
    confidence = REVERSAL_RATES.get(min(streak_len, 5), REVERSAL_RATES[5])

    return Signal(
        should_bet=True,
        direction=bet_direction,
        streak_length=streak_len,
        streak_direction=streak_dir,
        confidence=confidence,
        reason=f"Streak of {streak_len}x {streak_dir} detected. "
        f"Historical reversal rate: {confidence:.1%}. "
        f"Betting {bet_direction}.",
    )


def kelly_size(
    confidence: float, odds: float, bankroll: float, fraction: float = 0.25
) -> float:
    """
    Calculate bet size using fractional Kelly criterion.

    Args:
        confidence: Estimated win probability (0-1)
        odds: Decimal odds (e.g., 2.0 for even money at 50¢)
        bankroll: Current bankroll
        fraction: Kelly fraction (0.25 = quarter Kelly, conservative)

    Returns:
        Recommended bet size in USD
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
