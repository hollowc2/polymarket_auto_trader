from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from backtest_engine import parameter_sweep, run_backtest, walk_forward_split
from strategies.candle_direction import candle_direction_strategy

PARAM_GRID = {
    "ema_fast": [8, 12, 16],
    "ema_slow": [21, 26, 34],
    "rsi_period": [10, 14],
    "rsi_overbought": [65, 70],
    "rsi_oversold": [30, 35],
    "macd_fast": [8, 12],
    "macd_slow": [21, 26],
    "macd_signal": [9],
}

TARGETS = [
    ("btc", "5m"),
    ("eth", "5m"),
    ("eth", "1h"),
    ("btc", "1h"),
    ("eth", "4h"),
    ("btc", "4h"),
]


def load_candles(asset: str, timeframe: str) -> pd.DataFrame:
    path = Path("data") / f"{asset}_{timeframe}.parquet"
    df = pd.read_parquet(path)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    df = df.set_index("open_time").sort_index()
    return df


def main() -> None:
    out_dir = Path("backtest_results")
    out_dir.mkdir(exist_ok=True)

    summary: list[dict] = []

    for asset, timeframe in TARGETS:
        candles = load_candles(asset, timeframe)
        train, test = walk_forward_split(candles, train_ratio=0.75)

        sweep_df = parameter_sweep(train, candle_direction_strategy, PARAM_GRID)
        best_row = sweep_df.iloc[0].to_dict()
        best_params = {k: best_row[k] for k in PARAM_GRID.keys()}

        test_result = run_backtest(test, candle_direction_strategy, best_params)

        sweep_path = out_dir / f"sweep_{asset}_{timeframe}.csv"
        trades_path = out_dir / f"trades_{asset}_{timeframe}.csv"
        equity_path = out_dir / f"equity_{asset}_{timeframe}.csv"

        sweep_df.to_csv(sweep_path, index=False)
        test_result.trades.to_csv(trades_path, index=False)
        test_result.pnl_curve.rename("equity").to_csv(equity_path, index=True)

        row = {
            "asset": asset,
            "timeframe": timeframe,
            "best_params": best_params,
            **test_result.metrics,
        }
        summary.append(row)

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    for row in summary:
        print(
            f"{row['asset'].upper()} {row['timeframe']} | "
            f"win_rate={row['win_rate']:.2%} "
            f"pnl={row['total_pnl']:.2f} "
            f"trades={row['trade_count']} "
            f"best_params={row['best_params']}"
        )


if __name__ == "__main__":
    main()
