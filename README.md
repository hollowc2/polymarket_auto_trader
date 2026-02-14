# Polymarket BTC 5-Min Trading Bot

Two strategies for trading BTC 5-minute up/down markets on Polymarket:

1. **Copytrade** — Copy trades from profitable wallets in real-time
2. **Streak Reversal** — Bet against consecutive streaks (mean reversion)

> **Disclaimer:** This is experimental. Past performance does not guarantee future results. Use at your own risk. Start with paper trading.

## Quick Start

```bash
# Clone and setup
git clone https://github.com/0xrsydn/polymarket-streak-bot.git
cd polymarket-streak-bot
uv sync

# Copy .env and configure
cp .env.example .env

# Copytrade v2 (recommended - low-latency with resilience)
uv run python copybot_v2.py --paper --wallets 0x1d0034134e339a309700ff2d34e99fa2d48b0313

# Streak reversal strategy
uv run python bot.py --paper --trigger 4

# View trade history
uv run python history.py --stats
```

## Strategies

### Copytrade v2 (`copybot_v2.py`) — Recommended

Production-grade copytrade bot with low-latency optimizations and resilience features.

```bash
# Copy single wallet (recommended)
uv run python copybot_v2.py --paper --wallets 0x1d00...

# Copy multiple wallets
uv run python copybot_v2.py --paper --wallets 0x1d00...,0x5678...

# Custom settings with fast polling
uv run python copybot_v2.py --paper --amount 10 --poll 0.5 --wallets 0x1d00...

# Disable WebSocket (REST only)
uv run python copybot_v2.py --paper --no-websocket --wallets 0x1d00...
```

**v2 Improvements over v1:**

| Feature | v1 (`copybot.py`) | v2 (`copybot_v2.py`) |
|---------|-------------------|----------------------|
| Trade detection | 5-15s | 1.5-2s |
| Orderbook data | REST (~1s) | WebSocket (~100ms) |
| Order type | Limit (GTC) | Market (FOK) |
| API failures | Retry blindly | Circuit breaker |
| Rate limiting | None | Sliding window |
| Logging | Basic prints | Structured logs |

### Copytrade v1 (`copybot.py`)

Original copytrade bot. Still functional but v2 is recommended.

```bash
uv run python copybot.py --paper --wallets 0x1d00...
```

**Finding wallets to copy:**
1. Go to [Polymarket Leaderboard](https://polymarket.com/leaderboard)
2. Filter by "Crypto" category
3. Find traders with consistent BTC 5-min P&L
4. Copy wallet address from profile URL

### Streak Reversal (`bot.py`)

Bets against streaks of consecutive outcomes. After N ups in a row, bet down (and vice versa).

```bash
# Trigger on 4-streak (default)
uv run python bot.py --paper

# Trigger on 5-streak (more conservative)
uv run python bot.py --paper --trigger 5

# Custom bet amount
uv run python bot.py --paper --amount 10
```

## Realistic Paper Trading

Paper trading simulates real costs from Polymarket CLOB API:

| Cost | Source | Example |
|------|--------|---------|
| **Fees** | `clob.polymarket.com/fee-rate` | ~2.5% at 50¢ price |
| **Spread** | Real bid-ask from orderbook | ~1¢ typical |
| **Slippage** | Orderbook walking | Depends on size |
| **Copy Delay** | Time since trader's entry | ~0.3%/second |

All costs are deducted from your simulated bankroll, so paper P&L reflects realistic expectations.

## Trade History

Full trade history is recorded with fees, slippage, timestamps, and outcomes.

```bash
# View statistics
uv run python history.py --stats

# Show last 50 trades
uv run python history.py --limit 50

# Show all trades
uv run python history.py --all

# Export to CSV/JSON
uv run python history.py --export csv
uv run python history.py --export json
```

## Configuration

Create `.env` from template:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `PAPER_TRADE` | `true` | Set `false` for live trading |
| `BET_AMOUNT` | `5` | USD per trade |
| `MIN_BET` | `1` | Minimum bet size |
| `MAX_DAILY_BETS` | `50` | Stop after N bets/day |
| `MAX_DAILY_LOSS` | `50` | Stop if daily loss exceeds |
| `STREAK_TRIGGER` | `4` | Streak length to trigger (bot.py) |
| `ENTRY_SECONDS_BEFORE` | `30` | Seconds before window to enter |
| `COPY_WALLETS` | (empty) | Comma-separated wallets to copy |
| `COPY_POLL_INTERVAL` | `5` | Seconds between activity checks |
| `TIMEZONE` | `Asia/Jakarta` | Display timezone |
| `PRIVATE_KEY` | (empty) | Polygon wallet key (live only) |

**v2 Copytrade Settings:**

| Variable | Default | Description |
|----------|---------|-------------|
| `FAST_POLL_INTERVAL` | `1.5` | Fast polling interval (seconds) |
| `USE_WEBSOCKET` | `true` | Enable WebSocket for orderbook data |
| `REST_TIMEOUT` | `3` | REST API timeout (seconds) |
| `SIGNATURE_TYPE` | `0` | Wallet type: 0=EOA/MetaMask, 1=Magic/proxy |
| `FUNDER_ADDRESS` | (empty) | Funder address (required for proxy wallets) |

**Resilience Settings:**

| Variable | Default | Description |
|----------|---------|-------------|
| `CIRCUIT_BREAKER_THRESHOLD` | `5` | Failures before circuit opens |
| `CIRCUIT_BREAKER_RECOVERY_TIME` | `60` | Seconds before recovery attempt |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `120` | Max API requests per minute |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |

## Live Trading

1. Get a Polygon wallet with USDC
2. Configure `.env`:
   ```bash
   PRIVATE_KEY=0x_your_private_key
   PAPER_TRADE=false
   COPY_WALLETS=0x1d0034134e339a309700ff2d34e99fa2d48b0313

   # For EOA/MetaMask wallets (default)
   SIGNATURE_TYPE=0

   # For Magic/proxy wallets
   # SIGNATURE_TYPE=1
   # FUNDER_ADDRESS=0x_your_funder_address
   ```
3. Run:
   ```bash
   uv run python copybot_v2.py --live  # Recommended
   # or
   uv run python copybot.py --live
   # or
   uv run python bot.py --live
   ```

## CLI Reference

All bots have comprehensive `--help`:

```bash
uv run python copybot_v2.py --help  # Recommended
uv run python copybot.py --help
uv run python bot.py --help
uv run python history.py --help
```

**Common flags:**

| Flag | Description |
|------|-------------|
| `--paper` | Force paper trading mode |
| `--live` | Force live trading mode |
| `--amount USD` | Bet amount per trade |
| `--bankroll USD` | Override starting bankroll |
| `--max-bets N` | Daily bet limit |
| `--max-loss USD` | Daily loss limit |

**Copybot v2 flags:**

| Flag | Description |
|------|-------------|
| `--wallets ADDR` | Comma-separated wallet addresses |
| `--poll SEC` | Poll interval in seconds (default: 1.5) |
| `--no-websocket` | Disable WebSocket (REST only) |

**Copybot v1 flags:**

| Flag | Description |
|------|-------------|
| `--wallets ADDR` | Comma-separated wallet addresses |
| `--poll SEC` | Poll interval in seconds (default: 5) |

**Bot-specific:**

| Flag | Description |
|------|-------------|
| `--trigger N` | Streak length to trigger bet |

## Architecture

```
├── copybot_v2.py     — Copytrade v2 main loop (recommended)
├── copybot.py        — Copytrade v1 main loop
├── copytrade.py      — Wallet monitoring + signal generation
├── copytrade_ws.py   — Hybrid WebSocket + REST monitor
├── bot.py            — Streak reversal main loop
├── strategy.py       — Streak detection + Kelly sizing
├── polymarket.py     — REST API client (Gamma + CLOB)
├── polymarket_ws.py  — WebSocket client (orderbook + user)
├── trader.py         — Paper/live execution + state
├── resilience.py     — Circuit breaker + rate limiter
├── logging_config.py — Structured logging
├── history.py        — Trade history CLI
├── config.py         — Settings from .env
└── backtest.py       — Offline backtesting
```

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `data-api.polymarket.com/activity` | Wallet trade activity |
| `gamma-api.polymarket.com/markets` | Market discovery + outcomes |
| `clob.polymarket.com/book` | Orderbook + prices |
| `clob.polymarket.com/fee-rate` | Fee rates |

## Risk Management

The bot enforces:
- Minimum bet size ($5 on Polymarket)
- Max 10% of bankroll per trade
- Daily loss limit stops trading
- Daily bet count limit

**Recommended sizing:**

| Bankroll | Bet Size | Risk % |
|----------|----------|--------|
| $50 | $2-5 | 4-10% |
| $100 | $5-10 | 5-10% |
| $500+ | $10-25 | 2-5% |

## Copytrade Edge Cases

**Handled:**

| Scenario | Behavior |
|----------|----------|
| **Spread buy / DCA** | Traders using bots often split orders into multiple fills. All fills share the same `market_ts`, so only the first is copied. Deduplication via `copied_markets` set. |
| **Market closed** | Checks `market.closed` before attempting to copy. Skips if already closed. |
| **Market not accepting orders** | Checks `accepting_orders` flag. Skips pre-open or paused markets. |

**Known limitations:**

| Scenario | Current Behavior | Impact |
|----------|------------------|--------|
| **Same market, both directions** | Key is `(wallet, market_ts)` without direction. If trader buys Up then switches to Down on same market, only first is copied. | May miss direction changes |
| **Trader re-enters** | If trader exits and re-enters same 5-min window, second entry is skipped. | May miss re-entry signals |
| **Sell signals** | Only BUY signals are copied. If trader sells their position early to cut losses, we hold until expiry. | No early exit capability |
| **Copy delay** | By the time we detect → fetch price → execute, price may have moved 1-5%. Logged as `copy_delay_ms`. v2 reduces this to 1.5-2s with fast polling. | Worse entry than original trader |
| **Multiple wallets same market** | Each wallet has separate key. If two tracked wallets buy same market, we copy both. | Potential double exposure |
| **API latency** | Activity API may lag 1-10 seconds behind actual trades. | Inherent delay in copy strategy |

## Production Features (v2)

### Circuit Breaker

Prevents cascading failures when the Polymarket API is down or degraded:

- **CLOSED**: Normal operation, requests pass through
- **OPEN**: Too many failures (default: 5), requests blocked for recovery period (default: 60s)
- **HALF_OPEN**: Testing recovery, allows limited requests

```
[23:35:17] WARNING circuit_breaker | name=api state=open failures=5
```

### Rate Limiting

Sliding window rate limiter prevents hitting API limits:

- Default: 120 requests/minute
- Automatically pauses when approaching limit
- Logged when requests are throttled

### Structured Logging

All logs use consistent `key=value` format for easy parsing:

```
[23:35:17] INFO  order_placed | order_id=abc123 amount=5.00 price=0.52 latency_ms=45
[23:35:18] INFO  trade_settled | market=btc-updown-5m-123 direction=up outcome=up pnl=4.50 won=true
[23:35:48] INFO  heartbeat | pending=2 wins=5 losses=2 win_rate=71% pnl=12.50 bankroll=112.50
```

### Health Checks

Component health monitoring:

- API connectivity
- WebSocket connection
- Circuit breaker state
- Rate limiter utilization

## License

MIT
