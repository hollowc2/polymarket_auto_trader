# Polymarket Trading Toolkit

Composable, extensible toolkit for backtesting and live execution on Polymarket.

> Disclaimer: Experimental software. Use paper trading first.

## Architecture

```text
scripts/ (CLI)
   |
   v
packages/
  core        -> types/config/plugin discovery
  data        -> Binance fetch + storage
  indicators  -> EMA/SMA/RSI/MACD/Bollinger
  strategies  -> streak/copytrade/candle-direction/filter
  backtest    -> engine + metrics + reports
  executor    -> polymarket client/ws/trader/blockchain/resilience
```

## Quick Start

```bash
git clone https://github.com/0xrsydn/polymarket-streak-bot.git
cd polymarket-streak-bot
uv sync
cp .env.example .env
```

## Backtesting Quick Start

```bash
uv run python scripts/fetch_data.py
uv run python scripts/backtest.py
```

## Live Trading Quick Start

```bash
# streak bot
uv run python scripts/bot.py --paper

# copytrade bot
uv run python scripts/copybot.py --paper --wallets 0x1d0034134e339a309700ff2d34e99fa2d48b0313
```

## Plugin System

Discovery supports:
- Python entry points:
  - `polymarket_algo.strategies`
  - `polymarket_algo.indicators`
- Local drop-ins: `~/.polymarket-algo/plugins/*.py`

## Create Your Own Strategy Plugin

See `examples/custom_strategy`:

```bash
cd examples/custom_strategy
uv pip install -e .
```

This registers `rsi_reversal` via entry points.

## Copytrade Notes (reorganized)

- Copytrade engine remains available through existing runtime modules.
- Supports wallet monitoring, low-latency polling/WebSocket hybrid flow, realistic paper trading, and on-chain enrichment.
- Use existing env vars in `.env` (`COPY_WALLETS`, `FAST_POLL_INTERVAL`, `USE_WEBSOCKET`, `POLYGONSCAN_API_KEY`, etc.).

## Testing

```bash
uv run pytest
```
