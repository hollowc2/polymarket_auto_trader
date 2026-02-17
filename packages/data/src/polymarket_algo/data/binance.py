from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://api.binance.com/api/v3/klines"
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVALS = ["15m", "1h", "4h"]
START = datetime(2022, 1, 1, tzinfo=UTC)
MAX_LIMIT = 1000


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
        resp = requests.get(BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
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

    df["number_of_trades"] = pd.to_numeric(df["number_of_trades"], errors="coerce").astype("Int64")
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
