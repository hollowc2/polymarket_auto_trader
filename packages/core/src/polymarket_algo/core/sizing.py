"""Bet sizing utilities — Kelly criterion and historical reversal rates."""

from dataclasses import dataclass

# Measured reversal rates per timeframe — 2-year Binance BTCUSDT backtest (210k candles).
# 95% Wilson CI for reference:
#   5m : ±0.3% at trigger=2, ±0.6% at trigger=4, ±3.0% at trigger=8
#   15m: ±0.5% at trigger=2, ±1.2% at trigger=4, ±6.7% at trigger=8
#   1h : ±1.1% at trigger=2, ±2.3% at trigger=4, ±10.4% at trigger=8 (thin at high triggers)
# Note: 1h trigger≥7 drops below 50% — Kelly will correctly size those to 0.
REVERSAL_RATES: dict[str, dict[int, float]] = {
    "5m": {
        2: 0.518,
        3: 0.527,
        4: 0.537,
        5: 0.533,
        6: 0.540,
        7: 0.550,
        8: 0.562,
    },
    "15m": {
        2: 0.537,
        3: 0.556,
        4: 0.568,
        5: 0.579,
        6: 0.603,
        7: 0.598,
        8: 0.615,
    },
    "1h": {
        2: 0.541,
        3: 0.548,
        4: 0.557,
        5: 0.546,
        6: 0.533,
        7: 0.479,
        8: 0.482,
    },
}

# Best trigger per timeframe — highest train Sharpe with a reliable sample size.
# 5m : trigger=4 (Sharpe 3.19, 18k train trades)
# 15m: trigger=6 (Sharpe 6.01,  919 train trades)
# 1h : trigger=4 (Sharpe 2.76, 1.3k train trades, only trigger that survives test)
DEFAULT_TRIGGERS: dict[str, int] = {"5m": 4, "15m": 6, "1h": 4}


def get_reversal_rate(timeframe: str, trigger: int) -> float:
    """Return the measured win rate for a timeframe + trigger combination.

    Falls back to the "5m" table if the timeframe is unknown, and clamps
    trigger to the highest key in the table.
    """
    rates = REVERSAL_RATES.get(timeframe, REVERSAL_RATES["5m"])
    return rates[min(trigger, max(rates))]


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
