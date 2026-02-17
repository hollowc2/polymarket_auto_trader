from __future__ import annotations

import pandas as pd
from polymarket_algo.indicators import ema, macd, rsi


def candle_direction_strategy(
    candles: pd.DataFrame,
    ema_fast: int = 12,
    ema_slow: int = 26,
    rsi_period: int = 14,
    rsi_overbought: float = 70.0,
    rsi_oversold: float = 30.0,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
) -> pd.DataFrame:
    """
    Returns DataFrame with:
    - signal: 1 (up), -1 (down), 0 (no trade)
    - size: position size in shares (15 default, 20 strong alignment)
    """
    close = candles["close"]

    ema_fast_line = ema(close, ema_fast)
    ema_slow_line = ema(close, ema_slow)
    macd_df = macd(close, fast_period=macd_fast, slow_period=macd_slow, signal_period=macd_signal)
    rsi_values = rsi(close, period=rsi_period)

    bullish_ema = ema_fast_line > ema_slow_line
    bearish_ema = ema_fast_line < ema_slow_line

    bullish_macd = macd_df["macd"] > macd_df["signal"]
    bearish_macd = macd_df["macd"] < macd_df["signal"]

    bullish_rsi = rsi_values > rsi_oversold
    bearish_rsi = rsi_values < rsi_overbought

    long_cond = bullish_ema & bullish_macd & bullish_rsi
    short_cond = bearish_ema & bearish_macd & bearish_rsi

    signal = pd.Series(0, index=candles.index, dtype=int)
    signal.loc[long_cond] = 1
    signal.loc[short_cond] = -1

    strong_long = long_cond & (macd_df["histogram"] > 0) & (rsi_values.between(50, 65))
    strong_short = short_cond & (macd_df["histogram"] < 0) & (rsi_values.between(35, 50))

    size = pd.Series(15.0, index=candles.index)
    size.loc[(strong_long | strong_short) & (signal != 0)] = 20.0
    size.loc[signal == 0] = 0.0

    return pd.DataFrame({"signal": signal, "size": size}, index=candles.index)
