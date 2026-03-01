from __future__ import annotations

from typing import Any

import pandas as pd


class ThreeBarMoMoStrategy:
    name = "3bar_momo"
    description = "Momentum: N consecutive bars same direction with strictly increasing volume"
    timeframe = "5m"

    @property
    def default_params(self) -> dict[str, Any]:
        return {
            "bars": 3,           # consecutive qualifying bars required
            "size": 15.0,        # base bet in USD
            "size_cap": 2.0,     # max multiplier for vol-scaled size
            "min_body_pct": 0.0, # min candle body as % of close (0 = off)
        }

    @property
    def param_grid(self) -> dict[str, list[Any]]:
        return {
            "bars": [2, 3, 4, 5],
            "size": [10.0, 15.0, 20.0],
            "size_cap": [1.5, 2.0, 3.0],
            "min_body_pct": [0.0, 0.001, 0.002, 0.005],
        }

    def evaluate(self, candles: pd.DataFrame, **params: Any) -> pd.DataFrame:
        config = {**self.default_params, **params}
        bars = int(config["bars"])
        size_val = float(config["size"])
        size_cap = float(config["size_cap"])
        min_body_pct = float(config["min_body_pct"])

        body = candles["close"] - candles["open"]
        # Vectorized direction: 1 (bullish), -1 (bearish), 0 (doji)
        direction = (body > 0).astype(int) - (body < 0).astype(int)
        body_pct = body.abs() / candles["close"]
        volumes = candles["volume"]

        # All N bars same direction (non-zero)
        all_bullish = (
            (direction == 1)
            .rolling(bars, min_periods=bars)
            .min()
            .fillna(0)
            .astype(bool)
        )
        all_bearish = (
            (direction == -1)
            .rolling(bars, min_periods=bars)
            .min()
            .fillna(0)
            .astype(bool)
        )

        # Strictly increasing volume: bars-1 consecutive positive diffs
        if bars > 1:
            all_vol_increasing = (
                (volumes.diff() > 0)
                .rolling(bars - 1, min_periods=bars - 1)
                .min()
                .fillna(0)
                .astype(bool)
            )
        else:
            all_vol_increasing = pd.Series(True, index=candles.index)

        # Optional minimum body size filter
        if min_body_pct > 0:
            body_ok = (
                (body_pct >= min_body_pct)
                .rolling(bars, min_periods=bars)
                .min()
                .fillna(0)
                .astype(bool)
            )
        else:
            body_ok = pd.Series(True, index=candles.index)

        # Volume ratio: last bar / first bar in the window, capped
        vol_first = volumes.shift(bars - 1)
        vol_ratio = (volumes / vol_first).clip(upper=size_cap).fillna(1.0)

        bullish = all_bullish & all_vol_increasing & body_ok
        bearish = all_bearish & all_vol_increasing & body_ok

        signal = bullish.astype(int) - bearish.astype(int)
        size = pd.Series(0.0, index=candles.index)
        size[signal != 0] = size_val * vol_ratio[signal != 0]

        return pd.DataFrame({"signal": signal, "size": size}, index=candles.index)
