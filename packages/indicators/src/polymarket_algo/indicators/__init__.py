from .bollinger import bollinger_bands
from .ema import ema
from .macd import macd
from .rsi import rsi
from .sma import sma


class EMAIndicator:
    name = "ema"

    def compute(self, series, **params):
        return ema(series, period=int(params.get("period", 20)))


class SMAIndicator:
    name = "sma"

    def compute(self, series, **params):
        return sma(series, period=int(params.get("period", 20)))


class RSIIndicator:
    name = "rsi"

    def compute(self, series, **params):
        return rsi(series, period=int(params.get("period", 14)))


class MACDIndicator:
    name = "macd"

    def compute(self, series, **params):
        return macd(
            series,
            int(params.get("fast_period", 12)),
            int(params.get("slow_period", 26)),
            int(params.get("signal_period", 9)),
        )


class BollingerIndicator:
    name = "bollinger"

    def compute(self, series, **params):
        return bollinger_bands(series, int(params.get("period", 20)), float(params.get("std_dev", 2.0)))
