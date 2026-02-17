import pandas as pd


class RSIReversalStrategy:
    name = "rsi_reversal"
    description = "Buy oversold, sell overbought"
    timeframe = "15m"

    @property
    def default_params(self):
        return {"period": 14, "oversold": 30.0, "overbought": 70.0, "size": 10.0}

    @property
    def param_grid(self):
        return {"period": [10, 14], "oversold": [25.0, 30.0], "overbought": [70.0, 75.0]}

    def evaluate(self, candles: pd.DataFrame, **params) -> pd.DataFrame:
        p = {**self.default_params, **params}
        close = candles["close"]
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / int(p["period"]), adjust=False, min_periods=int(p["period"])).mean()
        avg_loss = loss.ewm(alpha=1 / int(p["period"]), adjust=False, min_periods=int(p["period"])).mean()
        rs = avg_gain / avg_loss.replace(0, pd.NA)
        rsi = (100 - (100 / (1 + rs))).fillna(100)

        signal = pd.Series(0, index=candles.index, dtype=int)
        signal[rsi < float(p["oversold"])] = 1
        signal[rsi > float(p["overbought"])] = -1
        size = pd.Series(float(p["size"]), index=candles.index)
        size[signal == 0] = 0.0
        return pd.DataFrame({"signal": signal, "size": size}, index=candles.index)
