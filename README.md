# 🎰 Polymarket BTC 5-Min Streak Reversal Bot

A simple bot that exploits mean reversion in Polymarket's BTC 5-minute up/down prediction markets.

## Strategy

Polymarket offers binary markets every 5 minutes: will BTC go up or down? The bot detects **streaks** — consecutive same outcomes — and bets on reversal.

**Why it works:** After 4+ consecutive same outcomes, historical data shows a ~67-73% reversal rate, while the market prices both sides at 50/50 (even odds). That's free edge.

| Streak Length | Reversal Rate | Sample Size |
|--------------|---------------|-------------|
| 3 | 57.9% | 121 |
| 4 | 66.7% | 51 |
| 5 | 82.4% | 17 |

**Backtest (288 markets, $10 bets):**
- Trigger=4: 26 bets, 73.1% win rate, +$110 PnL, $10 max drawdown
- Trigger=5: 7 bets, 100% win rate, +$66 PnL, $0 max drawdown

> ⚠️ **Disclaimer:** This is experimental. Only 2 days of historical data exist (markets launched Feb 12, 2026). Past performance ≠ future results. Use at your own risk. Start with paper trading.

## Quick Start

```bash
# Clone and setup
git clone https://github.com/0xrsydn/polymarket-streak-bot.git
cd polymarket-streak-bot
uv sync

# Paper trade (no real money)
cp .env.example .env
uv run python bot.py --paper

# Backtest against historical data
uv run python backtest.py
```

## Live Trading Setup

1. Get a Polygon wallet with USDC
2. Set your private key in `.env`:
   ```
   PRIVATE_KEY=0x_your_key
   PAPER_TRADE=false
   ```
3. Run: `uv run python bot.py`

## Configuration

Edit `.env` to tune:

| Variable | Default | Description |
|----------|---------|-------------|
| `STREAK_TRIGGER` | 4 | Bet after N consecutive same outcomes |
| `BET_AMOUNT` | 5 | USD per bet (min $5 on Polymarket) |
| `MAX_DAILY_BETS` | 50 | Stop after N bets per day |
| `MAX_DAILY_LOSS` | 50 | Stop if daily loss exceeds this |
| `ENTRY_SECONDS_BEFORE` | 30 | Enter N seconds before window opens |
| `PAPER_TRADE` | true | Set false for live trading |

## Architecture

```
├── bot.py          — Main loop: monitors markets, detects streaks, places bets
├── polymarket.py   — Polymarket API client (Gamma + CLOB)
├── strategy.py     — Streak detection + Kelly criterion sizing
├── trader.py       — Paper & live order execution + state management
├── backtest.py     — Backtest against historical data
├── config.py       — Settings from .env
└── .env.example    — Template config
```

## How It Works

1. **Monitor** — Fetches recent resolved BTC 5-min market outcomes
2. **Detect** — Checks for streaks (N consecutive up or down)
3. **Signal** — If streak ≥ trigger, generate bet-against signal
4. **Time** — Waits until ~30s before next window opens (get 50¢ odds)
5. **Execute** — Places bet on the reversal side
6. **Settle** — Tracks outcome, updates bankroll

## Data Collection

Historical data used for backtesting is in the sibling `polymarket-research/` directory. To collect fresh data yourself:

```bash
# Pull last 24h of resolved markets
curl -s "https://gamma-api.polymarket.com/events?slug=btc-updown-5m-{UNIX_TIMESTAMP}"
```

Markets follow the slug pattern `btc-updown-5m-{timestamp}` at 300-second intervals.

## License

MIT
