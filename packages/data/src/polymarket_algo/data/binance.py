from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://api.binance.com/api/v3/klines"

# Gate.io fallback (global availability, real exchange OHLCV)
GATEIO_BASE_URL = "https://api.gateio.ws/api/v4/spot/candlesticks"
GATEIO_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h", "1d": "1d",
}
GATEIO_MAX_LIMIT = 1000

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVALS = ["15m", "1h", "4h"]
START = datetime(2022, 1, 1, tzinfo=UTC)
MAX_LIMIT = 1000


def _gateio_symbol(symbol: str) -> str:
    """Convert Binance-style symbol (BTCUSDT) to Gate.io style (BTC_USDT)."""
    if symbol.endswith("USDT"):
        return symbol[:-4] + "_USDT"
    if symbol.endswith("BTC"):
        return symbol[:-3] + "_BTC"
    raise ValueError(f"Cannot convert symbol to Gate.io format: {symbol!r}")


def _gateio_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Fetch OHLCV from Gate.io spot API, returning the same schema as fetch_klines.

    Gate.io row format (ascending): [timestamp_sec, quote_vol, close, high, low, open, base_vol, is_closed]
    """
    gate_interval = GATEIO_INTERVAL_MAP.get(interval)
    if gate_interval is None:
        raise ValueError(f"Unsupported interval for Gate.io fallback: {interval!r}")

    gate_symbol = _gateio_symbol(symbol)
    rows: list[list] = []
    cursor_sec = start_ms // 1000
    end_sec = end_ms // 1000

    while cursor_sec < end_sec:
        params = {
            "currency_pair": gate_symbol,
            "interval": gate_interval,
            "from": cursor_sec,
            "to": end_sec,
            "limit": GATEIO_MAX_LIMIT,
        }
        resp = requests.get(GATEIO_BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if not data:
            break

        rows.extend(data)

        last_ts = int(data[-1][0])
        if last_ts <= cursor_sec:
            break
        cursor_sec = last_ts + 1
        time.sleep(0.1)

    if not rows:
        return pd.DataFrame()

    # Parse: [ts_sec, quote_vol, close, high, low, open, base_vol, is_closed]
    df = pd.DataFrame(rows, columns=[
        "open_time_sec", "quote_asset_volume", "close", "high", "low", "open", "volume", "is_closed",
    ])
    df = df.drop_duplicates(subset=["open_time_sec"]).sort_values("open_time_sec").reset_index(drop=True)

    for col in ["open", "high", "low", "close", "volume", "quote_asset_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["open_time"] = pd.to_datetime(
        pd.to_numeric(df["open_time_sec"]) * 1000, unit="ms", utc=True
    )

    # Fill columns not provided by Gate.io so the schema matches Binance output
    df["close_time"] = pd.NaT
    df["number_of_trades"] = pd.array([pd.NA] * len(df), dtype="Int64")
    df["taker_buy_base_asset_volume"] = float("nan")
    df["taker_buy_quote_asset_volume"] = float("nan")
    df["ignore"] = float("nan")

    return df[[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore",
    ]]


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows: list[list] = []
    cursor = start_ms

    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": MAX_LIMIT,
        }
        try:
            resp = requests.get(BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 451:
                print("[data] Binance geo-blocked (451) — falling back to Gate.io", flush=True)
                return _gateio_klines(symbol, interval, start_ms, end_ms)
            raise

        data = resp.json()
        if not data:
            break

        rows.extend(data)
        last_open_time = data[-1][0]
        if last_open_time <= cursor:
            break
        cursor = last_open_time + 1
        time.sleep(0.1)

    df = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base_asset_volume",
            "taker_buy_quote_asset_volume",
            "ignore",
        ],
    )
    if df.empty:
        return df

    df = df.drop_duplicates(subset=["open_time"]).sort_values("open_time").reset_index(drop=True)
    num_cols = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
        "taker_buy_base_asset_volume",
        "taker_buy_quote_asset_volume",
    ]
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    trades_numeric = pd.to_numeric(df["number_of_trades"], errors="coerce")
    df["number_of_trades"] = pd.Series(trades_numeric, index=df.index).astype("Int64")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df


def main() -> None:
    start_ms = int(START.timestamp() * 1000)
    end_ms = int(datetime.now(tz=UTC).timestamp() * 1000)

    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    for symbol in SYMBOLS:
        asset = symbol.replace("USDT", "").lower()
        for interval in INTERVALS:
            print(f"Fetching {symbol} {interval}...")
            df = fetch_klines(symbol, interval, start_ms, end_ms)
            out = data_dir / f"{asset}_{interval}.parquet"
            df.to_parquet(out, index=False)
            print(f"Saved {len(df):,} candles -> {out}")


if __name__ == "__main__":
    main()
