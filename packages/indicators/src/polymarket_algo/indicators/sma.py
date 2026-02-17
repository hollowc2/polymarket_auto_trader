from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int = 20) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=period, min_periods=period).mean()
