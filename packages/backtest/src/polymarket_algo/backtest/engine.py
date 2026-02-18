from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import product
from typing import Any, TypeGuard, cast

import numpy as np
import pandas as pd
from polymarket_algo.core import Strategy

StrategyCallable = Callable[..., pd.Series | pd.DataFrame]
StrategyLike = Strategy | StrategyCallable


def _has_evaluate(strategy: StrategyLike) -> TypeGuard[Strategy]:
    """Return True if strategy is an object with a callable .evaluate() method."""
    return callable(getattr(strategy, "evaluate", None))


@dataclass
class BacktestResult:
    metrics: dict[str, Any]
    trades: pd.DataFrame
    pnl_curve: pd.Series


def _max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    drawdown = equity_curve - running_max
    return float(drawdown.min()) if not drawdown.empty else 0.0


def _evaluate_strategy_output(
    candles: pd.DataFrame,
    strategy: StrategyLike,
    strategy_params: dict[str, Any],
) -> pd.Series | pd.DataFrame:
    if _has_evaluate(strategy):
        return strategy.evaluate(candles, **strategy_params)
    return cast(StrategyCallable, strategy)(candles, **strategy_params)


def run_backtest(
    candles: pd.DataFrame,
    strategy: StrategyLike,
    strategy_params: dict[str, Any] | None = None,
    buy_price: float = 0.50,
    win_payout: float = 0.95,
) -> BacktestResult:
    strategy_params = strategy_params or {}

    out = _evaluate_strategy_output(candles, strategy, strategy_params)
    if isinstance(out, pd.DataFrame):
        signals = out["signal"].astype(int)
        size = out["size"].astype(float) if "size" in out.columns else pd.Series(15.0, index=candles.index)
    else:
        signals = out.astype(int)
        size = pd.Series(15.0, index=candles.index)

    next_close = candles["close"].shift(-1)
    outcome_up = (next_close > candles["close"]).astype(int)

    active = (signals != 0) & outcome_up.notna()
    direction_up = signals == 1
    wins = (direction_up & (outcome_up == 1)) | ((signals == -1) & (outcome_up == 0))

    per_share_pnl = np.where(wins, win_payout - buy_price, -buy_price)
    per_share_pnl = pd.Series(per_share_pnl, index=candles.index)

    trade_pnl = (per_share_pnl * size).where(active, 0.0)
    pnl_curve = trade_pnl.cumsum()

    trades = pd.DataFrame(
        {
            "timestamp": candles.index,
            "signal": signals,
            "size": size,
            "entry_close": candles["close"],
            "next_close": next_close,
            "is_win": wins.where(active, False),
            "pnl": trade_pnl,
        }
    )
    trades = trades.loc[active]

    trade_count = int(active.sum())
    win_rate = float(trades["is_win"].mean()) if trade_count else 0.0
    total_pnl = float(trade_pnl.sum())
    returns = trade_pnl.loc[active]
    sharpe = (
        float((returns.mean() / returns.std(ddof=0)) * np.sqrt(len(returns)))
        if trade_count and returns.std(ddof=0) > 0
        else 0.0
    )

    metrics = {
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "max_drawdown": _max_drawdown(pnl_curve),
        "sharpe_ratio": sharpe,
        "trade_count": trade_count,
    }

    return BacktestResult(metrics=metrics, trades=trades, pnl_curve=pnl_curve)


def parameter_sweep(
    candles: pd.DataFrame,
    strategy: StrategyLike,
    param_grid: dict[str, list[Any]],
) -> pd.DataFrame:
    keys = list(param_grid.keys())
    rows: list[dict[str, Any]] = []

    for values in product(*[param_grid[k] for k in keys]):
        params = dict(zip(keys, values, strict=False))
        result = run_backtest(candles, strategy, params)
        rows.append({**params, **result.metrics})

    return pd.DataFrame(rows).sort_values(by=["win_rate", "total_pnl"], ascending=False).reset_index(drop=True)


def walk_forward_split(candles: pd.DataFrame, train_ratio: float = 0.75) -> tuple[pd.DataFrame, pd.DataFrame]:
    split_idx = int(len(candles) * train_ratio)
    train = candles.iloc[:split_idx].copy()
    test = candles.iloc[split_idx:].copy()
    return train, test
