# Polymarket BTC 5-Min Copytrade Bot

Copy trades from profitable wallets on Polymarket's BTC 5-minute up/down markets.

> **Disclaimer:** Experimental software. Past performance does not guarantee future results. Start with paper trading.

## Quick Start

```bash
git clone https://github.com/0xrsydn/polymarket-streak-bot.git
cd polymarket-streak-bot
uv sync

cp .env.example .env

# Paper trade (recommended to start)
uv run python copybot_v2.py --paper --wallets 0x1d0034134e339a309700ff2d34e99fa2d48b0313

# View trade history
uv run python history.py --stats
```

## Usage

```bash
# Copy single wallet
uv run python copybot_v2.py --paper --wallets 0x1d00...

# Copy multiple wallets
uv run python copybot_v2.py --paper --wallets 0x1d00...,0x5678...

# Custom bet amount and polling
uv run python copybot_v2.py --paper --amount 10 --poll 0.5 --wallets 0x1d00...

# Disable WebSocket (REST only)
uv run python copybot_v2.py --paper --no-websocket --wallets 0x1d00...
```

**Finding wallets to copy:**
1. Go to [Polymarket Leaderboard](https://polymarket.com/leaderboard)
2. Filter by "Crypto" category
3. Find traders with consistent BTC 5-min P&L
4. Copy wallet address from profile URL

## Features

| Feature | Description |
|---------|-------------|
| Trade detection | 1.5-2s latency with fast polling |
| Orderbook data | WebSocket (~100ms) with REST fallback |
| Order type | Market (FOK) for guaranteed fills |
| Resilience | Circuit breaker + rate limiting |
| Logging | Colorful structured logs |
| Pattern data | 54 fields saved for analysis |

## Realistic Paper Trading

Paper trading simulates real trading conditions:

| Feature | Description |
|---------|-------------|
| **Immediate bankruptcy** | Simulation ends when bankroll < min bet |
| **Chronological settlement** | Markets settle in order (oldest first) |
| **State persistence** | Pending trades survive bot restart |
| **Real costs** | Fees, spread, slippage from live orderbook |
| **Resolution timing** | Tracks actual Chainlink/UMA resolution delay |

### Exit Conditions

| Condition | Exit Code | Message |
|-----------|-----------|---------|
| Bankroll depleted | 1 | `SIMULATION ENDED - INSUFFICIENT FUNDS` |
| Daily loss limit | 0 | `SIMULATION ENDED - DAILY LOSS LIMIT` |
| Ctrl+C | 0 | `Shutdown` |

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
| `COPY_WALLETS` | (empty) | Comma-separated wallets to copy |
| `FAST_POLL_INTERVAL` | `1.5` | Polling interval (seconds) |
| `USE_WEBSOCKET` | `true` | Enable WebSocket for orderbook |
| `REST_TIMEOUT` | `3` | REST API timeout (seconds) |
| `TIMEZONE` | `Asia/Jakarta` | Display timezone |
| `PRIVATE_KEY` | (empty) | Polygon wallet key (live only) |

**Resilience settings:**

| Variable | Default | Description |
|----------|---------|-------------|
| `CIRCUIT_BREAKER_THRESHOLD` | `5` | Failures before circuit opens |
| `CIRCUIT_BREAKER_RECOVERY_TIME` | `60` | Seconds before recovery |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `120` | Max API requests/minute |

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
   uv run python copybot_v2.py --live
   ```

## CLI Flags

```bash
uv run python copybot_v2.py --help
```

| Flag | Description |
|------|-------------|
| `--paper` | Force paper trading mode |
| `--live` | Force live trading mode |
| `--amount USD` | Bet amount per trade |
| `--bankroll USD` | Override starting bankroll |
| `--wallets ADDR` | Comma-separated wallet addresses |
| `--poll SEC` | Poll interval (default: 1.5) |
| `--no-websocket` | Disable WebSocket |
| `--max-bets N` | Daily bet limit |
| `--max-loss USD` | Daily loss limit |

## Paper Trading Costs

Paper trading simulates real costs from Polymarket CLOB API:

| Cost | Source | Example |
|------|--------|---------|
| **Fees** | `clob.polymarket.com/fee-rate` | ~2.5% at 50¢ |
| **Spread** | Real bid-ask from orderbook | ~1¢ typical |
| **Slippage** | Orderbook walking | Depends on size |
| **Copy Delay** | Time since trader's entry | ~0.3%/second |

## Trade History & Analysis

```bash
uv run python history.py --stats      # View statistics
uv run python history.py --limit 50   # Last 50 trades
uv run python history.py --all        # All trades
uv run python history.py --export csv # Export to CSV
```

### Pattern Analysis Data

All trades saved to `trade_history_full.json` with 54 fields:

| Category | Fields | Use Case |
|----------|--------|----------|
| **Time Patterns** | `hour_utc`, `day_of_week`, `minute_of_hour`, `seconds_into_window` | Find best times to trade |
| **Session Tracking** | `session_trade_number`, `session_wins_before`, `bankroll_before` | Track performance decay |
| **Streaks** | `consecutive_wins`, `consecutive_losses` | Mean reversion patterns |
| **Market Context** | `market_bias`, `price_ratio`, `opposite_price` | Entry quality analysis |
| **Execution** | `spread`, `slippage_pct`, `delay_impact_pct`, `copy_delay_ms` | Cost analysis |
| **Resolution** | `resolution_delay_seconds`, `price_at_close`, `final_price` | Market timing |

**Example analysis:**

```python
import json
with open("trade_history_full.json") as f:
    trades = json.load(f)

# Win rate by hour
from collections import defaultdict
hourly = defaultdict(lambda: {"wins": 0, "total": 0})
for t in trades:
    if t["won"] is not None:
        hourly[t["hour_utc"]]["total"] += 1
        if t["won"]:
            hourly[t["hour_utc"]]["wins"] += 1

# Win rate after consecutive losses (mean reversion)
after_losses = [t for t in trades if t["consecutive_losses"] >= 2 and t["won"] is not None]
if after_losses:
    win_rate = sum(1 for t in after_losses if t["won"]) / len(after_losses)
    print(f"Win rate after 2+ losses: {win_rate:.1%}")
```

## Copytrade Edge Cases

**Handled:**

| Scenario | Behavior |
|----------|----------|
| **Spread buy / DCA** | Traders often split orders into multiple fills. All fills share the same `market_ts`, so only the first is copied. |
| **Market closed** | Checks `market.closed` before copying. Skips if already closed. |
| **Market not accepting orders** | Checks `accepting_orders` flag. Skips pre-open or paused markets. |

**Known limitations:**

| Scenario | Behavior | Impact |
|----------|----------|--------|
| **Same market, both directions** | Key is `(wallet, market_ts)` without direction. If trader buys Up then Down on same market, only first is copied. | May miss direction changes |
| **Trader re-enters** | If trader exits and re-enters same 5-min window, second entry is skipped. | May miss re-entry signals |
| **Sell signals** | Only BUY signals are copied. If trader sells early to cut losses, we hold until expiry. | No early exit |
| **Copy delay** | By the time we detect → fetch → execute, price may move 1-5%. v2 reduces this to 1.5-2s. | Worse entry than trader |
| **Multiple wallets same market** | Each wallet has separate key. If two tracked wallets buy same market, we copy both. | Double exposure |
| **API latency** | Activity API may lag 1-10 seconds behind actual trades. | Inherent delay |

## Market Resolution Timing

BTC 5-min markets resolve ~30-90 seconds after the window closes:

```
12:15:00  Window opens (market timestamp)
12:20:00  Window closes
12:20:39  Market resolved (Chainlink + UMA oracle)
```

The bot polls every 1.5s and settles trades within seconds of resolution.

## Architecture

```
├── copybot_v2.py     — Main copytrade loop
├── copytrade.py      — Wallet monitoring + signal generation
├── copytrade_ws.py   — Hybrid WebSocket + REST monitor
├── polymarket.py     — REST API client (Gamma + CLOB)
├── polymarket_ws.py  — WebSocket client (orderbook)
├── trader.py         — Paper/live execution + state
├── resilience.py     — Circuit breaker + rate limiter
├── logging_config.py — Colorful structured logging
├── history.py        — Trade history CLI
└── config.py         — Settings from .env
```

## License

MIT
