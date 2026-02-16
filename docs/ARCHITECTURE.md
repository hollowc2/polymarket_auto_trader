# Architecture

## Overview
The bot monitors Polymarket's BTC 5-minute up/down prediction markets and executes trades based on configurable strategies. Markets resolve every 5 minutes based on BTC price movement.

## Layers

```
Entrypoints (bot.py, copybot_v2.py)
    ↓
Strategies (src/strategies/)        — Signal generation
    ↓
Core (src/core/)                    — Market data, execution
    ↓
Infra (src/infra/)                  — Resilience, logging
```

### Strategies (`src/strategies/`)
- **streak.py** — Detects N consecutive same outcomes, bets reversal. Trigger=4 is the sweet spot (~67-73% reversal rate at ~50/50 odds).
- **copytrade.py** — Polls target wallets via Polymarket data API every 1.5s, generates copy signals.
- **copytrade_ws.py** — WebSocket-based copytrade monitor. Hybrid WS + fast REST polling for ~1.5-2s detection latency.
- **selective_filter.py** — Pre-trade quality gate: checks delay, spread, depth, price movement before executing a copy.

### Core (`src/core/`)
- **polymarket.py** — REST client for Gamma (market discovery) and CLOB (orderbook/prices) APIs. Connection pooling, caching, configurable timeouts.
- **polymarket_ws.py** — WebSocket client for real-time orderbook data (~100ms latency). Connects to `wss://ws-subscriptions-clob.polymarket.com/ws/market`.
- **blockchain.py** — Polygonscan API for on-chain wallet monitoring.
- **trader.py** — Execution layer. Paper trader (logs only) and live trader (submits FOK orders via CLOB API). Quarter-Kelly sizing.

### Infra (`src/infra/`)
- **resilience.py** — Circuit breaker, rate limiter, retry with backoff.
- **logging_config.py** — Structured logging setup.

## Data Flow

### Streak Strategy
1. Gamma API → fetch recent resolved BTC 5-min markets
2. Detect streak of N consecutive same outcomes
3. ~30s before next window → place reversal bet at ~50¢
4. Market resolves → track P&L

### Copytrade
1. Poll target wallet activity (data API, 1.5s interval)
2. Detect new BTC 5-min position
3. Fetch orderbook (WebSocket or REST fallback)
4. Place matching FOK order
5. Track execution quality (delay, spread, slippage)

## External APIs
| API | Auth | Purpose |
|-----|------|---------|
| Gamma API | None | Market discovery (slugs, outcomes) |
| CLOB API (REST) | None (reads) / API key (trades) | Orderbook, prices, order placement |
| CLOB API (WS) | None | Real-time orderbook |
| Polymarket Data API | None | Wallet activity monitoring |
| Polygonscan | API key | On-chain wallet data |

## Market Mechanics
- Slug pattern: `btc-updown-5m-{unix_ts}` every 300s
- Two outcomes per market: Up / Down (binary)
- Trading requires Polygon wallet + EIP-712 derived API credentials
- ~5% Polymarket fee on winnings
