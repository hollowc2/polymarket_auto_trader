"""Run backtests for every (strategy, asset, timeframe) combination.

Usage:
    uv run python scripts/run_all_backtests.py

Data files must already exist as data/{asset}_{tf}.parquet.
Missing files are skipped with a warning. Results are written to
backtest_results/{strategy_name}_{asset}_{tf}/ and a combined
backtest_results/summary.json.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pandas as pd
from polymarket_algo.backtest.engine import parameter_sweep, run_backtest, walk_forward_split
from polymarket_algo.strategies import (
    StreakADXStrategy,
    StreakReversalStrategy,
    StreakRSIStrategy,
)

STRATEGIES = [
    StreakReversalStrategy,
    StreakRSIStrategy,
    StreakADXStrategy,
]

TIMEFRAMES = ["5m", "15m", "1h"]
ASSETS = ["btc", "eth", "sol", "xrp"]

STRATEGY_TARGETS = [(cls, asset, tf) for cls in STRATEGIES for asset in ASSETS for tf in TIMEFRAMES]

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
OUT_DIR = Path(__file__).resolve().parents[1] / "backtest_results"


def load_candles(asset: str, timeframe: str) -> pd.DataFrame:
    path = DATA_DIR / f"{asset}_{timeframe}.parquet"
    df = pd.read_parquet(path)
    if "open_time" in df.columns:
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
        df = df.set_index("open_time")
    df = df.sort_index()
    return df


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    summary: list[dict[str, Any]] = []

    for StrategyClass, asset, timeframe in STRATEGY_TARGETS:
        data_path = DATA_DIR / f"{asset}_{timeframe}.parquet"
        if not data_path.exists():
            print(f"[SKIP] Missing data: {data_path.name}")
            continue

        sig = inspect.signature(StrategyClass.__init__)
        if "asset" in sig.parameters:
            strategy = StrategyClass(asset=asset.upper())  # type: ignore[call-arg]
        else:
            strategy = StrategyClass()
        print(f"[RUN ] {strategy.name} / {asset} / {timeframe} ...", end=" ", flush=True)

        candles = load_candles(asset, timeframe)
        if len(candles) < 50:
            print(f"too few candles ({len(candles)}), skipping")
            continue

        train, test = walk_forward_split(candles, train_ratio=0.75)

        sweep_df = parameter_sweep(train, strategy, strategy.param_grid)
        best_row = sweep_df.iloc[0].to_dict()
        best_params: dict[str, Any] = {k: best_row[k] for k in strategy.param_grid}

        result = run_backtest(test, strategy, best_params)

        sub_dir = OUT_DIR / f"{strategy.name}_{asset}_{timeframe}"
        sub_dir.mkdir(exist_ok=True)

        sweep_df.to_csv(sub_dir / "sweep.csv", index=False)
        result.trades.to_csv(sub_dir / "trades.csv", index=False)
        result.pnl_curve.rename("equity").to_csv(sub_dir / "equity.csv", index=True)

        row: dict[str, Any] = {
            "strategy": strategy.name,
            "asset": asset,
            "timeframe": timeframe,
            "best_params": best_params,
            **result.metrics,
        }
        summary.append(row)

        print(
            f"win_rate={result.metrics['win_rate']:.2%}  "
            f"pnl={result.metrics['total_pnl']:+.2f}  "
            f"sharpe={result.metrics['sharpe_ratio']:.2f}  "
            f"trades={result.metrics['trade_count']}"
        )

    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote {len(summary)} results → {summary_path}")


if __name__ == "__main__":
    main()
