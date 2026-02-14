# AGENTS.md — Polymarket Streak Bot

## Project Overview
A Python bot that trades BTC 5-min up/down markets on Polymarket using either:
1. **Streak reversal strategy** — bet against streaks of consecutive outcomes
2. **Copytrade strategy** — copy trades from specific wallet addresses

## Architecture
- `bot.py` — Main event loop for streak strategy. Monitors markets, checks streaks, places bets.
- `copybot.py` — Main event loop for copytrade (v1). Monitors wallets, copies BTC 5-min trades.
- `copybot_v2.py` — **Low-latency copytrade bot (v2)**. Uses WebSocket + fast polling.
- `copytrade.py` — Original copytrade logic. Polls data-api.polymarket.com for wallet activity.
- `copytrade_ws.py` — **Fast copytrade monitor**. Hybrid WebSocket + 1.5s REST polling.
- `polymarket.py` — API client with connection pooling, caching, and configurable timeouts.
- `polymarket_ws.py` — **WebSocket client** for real-time orderbook data (~100ms latency).
- `strategy.py` — Streak strategy logic. Streak detection, signal generation, Kelly criterion bet sizing.
- `trader.py` — Execution layer. Paper trader (logs only) and live trader (submits orders).
- `config.py` — Reads `.env`, exposes typed config.
- `backtest.py` — Offline backtest against historical JSON data.

## Key Decisions
- **Trigger=4** is the sweet spot: good balance of trade frequency and win rate
- Entry at ~50¢ (before window opens) maximizes edge
- Quarter-Kelly sizing for conservative bankroll management
- Graceful degradation: if a market fetch fails, skip and continue

## Data
- Polymarket BTC 5-min markets: slug pattern `btc-updown-5m-{unix_ts}` every 300s
- Gamma API for market discovery (no auth)
- CLOB API for orderbook/prices (no auth for reads)
- Trading requires Polygon wallet + EIP-712 derived API creds

## Dev
```bash
uv sync                          # install deps
uv run python bot.py --paper     # paper trade (streak strategy)
uv run python backtest.py        # backtest streak strategy

# Copytrade v1 (original)
uv run python copybot.py --paper --wallets 0x1d0034134e339a309700ff2d34e99fa2d48b0313

# Copytrade v2 (low-latency, recommended)
uv run python copybot_v2.py --paper --wallets 0x1d0034134e339a309700ff2d34e99fa2d48b0313
```

## Copytrade Config (.env)
```
COPY_WALLETS=0x1d0034134e339a309700ff2d34e99fa2d48b0313,0xanotherWallet
COPY_POLL_INTERVAL=5

# v2 Low-Latency Settings
FAST_POLL_INTERVAL=1.5     # Fast polling (seconds)
USE_WEBSOCKET=true          # Enable WebSocket for orderbook data
REST_TIMEOUT=3              # REST API timeout (seconds)
```

## Copytrade v2 (Low-Latency Mode)
The v2 copytrade bot (`copybot_v2.py`) includes major performance improvements:

### Latency Improvements
| Component | v1 Latency | v2 Latency |
|-----------|-----------|-----------|
| Trade detection | 5-15s | 1.5-2s |
| Orderbook data | ~1s (REST) | ~100ms (WebSocket) |
| REST timeout | 10s | 3s |

### Features
- **WebSocket orderbook**: Real-time orderbook data via `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- **Fast polling**: 1.5s polling interval (vs 5s default)
- **Connection pooling**: Reuses HTTP connections for faster requests
- **Market pre-fetching**: Caches token IDs for upcoming windows
- **Graceful degradation**: Falls back to REST if WebSocket fails

### Usage
```bash
# v2 with all optimizations
uv run python copybot_v2.py --paper --wallets 0x1d0034134e339a309700ff2d34e99fa2d48b0313

# v2 without WebSocket (REST only)
uv run python copybot_v2.py --paper --no-websocket --wallets 0x...

# v2 with custom poll interval (0.5s = aggressive)
uv run python copybot_v2.py --paper --poll 0.5 --wallets 0x...
```

## Caveats
- Only ~2 days of historical data (markets launched Feb 12 2026)
- Streak reversal is a known mean-reversion pattern but may not persist
- Polymarket fees (~5%) eat into margins
- Thin liquidity on some windows
