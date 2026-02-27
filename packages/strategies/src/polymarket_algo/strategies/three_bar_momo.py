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

        # Body direction: close > open → 1, close < open → -1, doji → 0
        body = candles["close"] - candles["open"]
        direction = body.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        body_pct = body.abs() / candles["close"]
        volumes = candles["volume"]

        signal = pd.Series(0, index=candles.index, dtype=int)
        size = pd.Series(0.0, index=candles.index)

        for i in range(bars - 1, len(candles)):
            window_dir = direction.iloc[i - bars + 1 : i + 1]
            window_vol = volumes.iloc[i - bars + 1 : i + 1]
            window_body = body_pct.iloc[i - bars + 1 : i + 1]

            dir_val = window_dir.iloc[0]
            # All bars same non-zero direction
            if dir_val == 0 or not (window_dir == dir_val).all():
                continue

            # Strictly increasing volume
            if not all(window_vol.iloc[j] > window_vol.iloc[j - 1] for j in range(1, bars)):
                continue

            # Optional minimum body size filter
            if min_body_pct > 0 and not (window_body >= min_body_pct).all():
                continue

            # Volume-scaled size (capped)
            vol_ratio = window_vol.iloc[-1] / window_vol.iloc[0]
            signal.iloc[i] = dir_val
            size.iloc[i] = size_val * min(vol_ratio, size_cap)

        return pd.DataFrame({"signal": signal, "size": size}, index=candles.index)
