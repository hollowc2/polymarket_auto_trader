# Polymarket Trading Toolkit

Composable, extensible toolkit for backtesting and live execution on Polymarket.

> Disclaimer: Experimental software. Use paper trading first.

## Architecture

```text
packages/
  core        → types, config, plugin registry, DataFeed protocol
  data        → Binance fetch + CSV/Parquet storage
  indicators  → EMA, SMA, RSI, MACD, Bollinger Bands
  strategies  → streak reversal, copytrade, candle direction, selective filter
  backtest    → engine + parameter sweep + walk-forward + metrics
  executor    → Polymarket CLOB client, WebSocket feeds, trader, blockchain utils

scripts/      → CLI entry points (bot.py, copybot.py, backtest.py, fetch_data.py)
examples/     → custom strategy plugin example
```

### DataFeed Protocol

The `DataFeed` protocol enables pluggable market data sources. The built-in `PolymarketDataFeed` wraps the Polymarket WebSocket — future feeds (Binance, Chainlink) implement the same interface:

```python
from polymarket_algo.core import DataFeed, PriceTick

# Any feed conforming to DataFeed protocol works
feed.subscribe("my-market-id", token_ids=["0xabc..."])
feed.on_tick(lambda tick: print(f"{tick.symbol}: {tick.price}"))
feed.start()
```

## Setup

### With Nix (recommended)

```bash
git clone https://github.com/0xrsydn/polymarket-crypto-toolkit.git
cd polymarket-crypto-toolkit
nix develop    # drops you into a shell with python, uv, ruff, ty, prek
               # auto-runs: uv sync, prek install
cp .env.example .env
```

### Without Nix

Requires: Python 3.13+, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/0xrsydn/polymarket-crypto-toolkit.git
cd polymarket-crypto-toolkit
uv sync --all-packages
cp .env.example .env

# Install git hooks (optional, requires prek)
prek install
```

## Usage

### Backtesting

```bash
# Fetch historical data
uv run python scripts/fetch_data.py

# Run backtest with parameter sweep
uv run python scripts/backtest.py
```

### Live Trading

```bash
# Streak reversal bot (paper mode)
uv run python scripts/bot.py --paper

# Copytrade bot (paper mode)
uv run python scripts/copybot.py --paper --wallets 0xYourTargetWallet
```

## Plugin System

Strategies and indicators are discovered via:

- **Entry points:** `polymarket_algo.strategies` / `polymarket_algo.indicators`
- **Local drop-ins:** `~/.polymarket-algo/plugins/*.py`
- **Plugin registry:** `PluginRegistry` unifies both discovery methods

### Create a Custom Strategy

See `examples/custom_strategy/`:

```bash
cd examples/custom_strategy
uv pip install -e .
```

This registers `rsi_reversal` as a discoverable strategy via entry points.

## Development

### Dev Dependencies

Dev tools (`ruff`, `ty`, `pytest`) are managed by uv as dev dependencies. Nix users also get them via the devshell — hooks use whichever is on PATH.

### Git Hooks (via prek)

- **Pre-commit:** `ruff check` + `ruff format`
- **Pre-push:** `ty` typecheck

Hooks are installed automatically in `nix develop`, or manually via `prek install`.

### Running Tests

```bash
uv run pytest -v
```

### Project Structure

```text
packages/core/        → Protocol types (Strategy, Indicator, DataFeed, PriceTick), config, plugin registry
packages/data/        → Binance OHLCV data fetcher + storage backends
packages/indicators/  → Pure numpy/pandas indicator implementations
packages/strategies/  → Strategy implementations conforming to Strategy protocol
packages/backtest/    → Backtest engine with parameter sweep + walk-forward validation
packages/executor/    → Polymarket execution layer (REST + WebSocket + blockchain)
```

Each package is independently installable via uv workspaces.

## Vibe-Coded 🤖

This project was fully vibe-coded by **Dexter**, an [OpenClaw](https://github.com/openclaw/openclaw) AI agent running on NixOS — from architecture implementation to code reviews, testing, and documentation. System design, architectural decisions, and creative direction by [@0xrsydn](https://github.com/0xrsydn).

## License

MIT
