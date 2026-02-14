#!/usr/bin/env python3
"""
Polymarket BTC 5-Min Copytrade Bot v2

Enhanced version with:
- WebSocket for real-time orderbook data (~100ms latency)
- Fast REST polling for wallet activity (1-2s vs 5s)
- Connection pooling and shorter timeouts
- Market pre-fetching and token ID caching
- Better error handling and graceful degradation
"""

import argparse
import signal
import sys
import time
from datetime import datetime

from config import Config, LOCAL_TZ, TIMEZONE_NAME
from copytrade import CopySignal
from copytrade_ws import HybridCopytradeMonitor
from polymarket import PolymarketClient
from polymarket_ws import MarketDataCache
from trader import LiveTrader, PaperTrader, TradingState

running = True


def handle_signal(sig, frame):
    global running
    print("\n[copybot] Shutting down gracefully...")
    running = False


def log(msg: str):
    ts = datetime.now(LOCAL_TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def main():
    global running
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Format wallet list for help text
    wallet_list = "\n    ".join(Config.COPY_WALLETS) if Config.COPY_WALLETS else "(none configured)"

    parser = argparse.ArgumentParser(
        description="Polymarket BTC 5-Min Copytrade Bot v2 (Low-Latency)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Environment Variables (.env):
  PAPER_TRADE        Paper trading mode (default: true)
  BET_AMOUNT         Bet amount in USD (default: 5)
  MIN_BET            Minimum bet size (default: 1)
  MAX_DAILY_BETS     Maximum bets per day (default: 50)
  MAX_DAILY_LOSS     Stop trading after this loss (default: 50)
  COPY_WALLETS       Comma-separated wallet addresses to copy
  FAST_POLL_INTERVAL Fast polling interval in seconds (default: 1.5)
  USE_WEBSOCKET      Enable WebSocket for orderbook data (default: true)
  REST_TIMEOUT       REST API timeout in seconds (default: 3)
  TIMEZONE           Display timezone (default: Asia/Jakarta)
  PRIVATE_KEY        Polygon wallet private key (required for live)

Current Configuration:
  Mode:              {'PAPER' if Config.PAPER_TRADE else 'LIVE'}
  Bet Amount:        ${Config.BET_AMOUNT}
  Min Bet:           ${Config.MIN_BET}
  Max Daily Bets:    {Config.MAX_DAILY_BETS}
  Max Daily Loss:    ${Config.MAX_DAILY_LOSS}
  Poll Interval:     {Config.FAST_POLL_INTERVAL}s (fast mode)
  REST Timeout:      {Config.REST_TIMEOUT}s
  WebSocket:         {'Enabled' if Config.USE_WEBSOCKET else 'Disabled'}
  Timezone:          {TIMEZONE_NAME}
  Wallets:
    {wallet_list}

v2 Improvements:
  - WebSocket orderbook data: ~100ms latency (vs ~1s REST)
  - Fast polling: {Config.FAST_POLL_INTERVAL}s (vs 5s default)
  - Connection pooling: Reuses HTTP connections
  - Market pre-fetching: Caches token IDs in advance
  - Graceful degradation: Falls back to REST if WS fails

Examples:
  # Paper trade with fast polling
  python copybot_v2.py --paper --wallets 0x1234...

  # Disable WebSocket (REST only)
  python copybot_v2.py --paper --no-websocket --wallets 0x1234...

  # Custom poll interval (0.5s = very fast)
  python copybot_v2.py --paper --poll 0.5 --wallets 0x1234...
"""
    )
    parser.add_argument(
        "--paper", action="store_true",
        help=f"Force paper trading mode (current: {Config.PAPER_TRADE})"
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Force live trading mode (requires PRIVATE_KEY)"
    )
    parser.add_argument(
        "--amount", type=float, metavar="USD",
        help=f"Bet amount in USD (default: {Config.BET_AMOUNT})"
    )
    parser.add_argument(
        "--bankroll", type=float, metavar="USD",
        help="Set starting bankroll (overrides saved state)"
    )
    parser.add_argument(
        "--wallets", type=str, metavar="ADDR",
        help="Comma-separated wallet addresses to copy"
    )
    parser.add_argument(
        "--poll", type=float, metavar="SEC",
        help=f"Poll interval in seconds (default: {Config.FAST_POLL_INTERVAL})"
    )
    parser.add_argument(
        "--no-websocket", action="store_true",
        help="Disable WebSocket (REST only mode)"
    )
    parser.add_argument(
        "--max-bets", type=int, metavar="N",
        help=f"Maximum daily bets (default: {Config.MAX_DAILY_BETS})"
    )
    parser.add_argument(
        "--max-loss", type=float, metavar="USD",
        help=f"Stop after this daily loss (default: {Config.MAX_DAILY_LOSS})"
    )
    args = parser.parse_args()

    # Determine trading mode
    if args.live:
        paper_mode = False
    elif args.paper:
        paper_mode = True
    else:
        paper_mode = Config.PAPER_TRADE

    bet_amount = args.amount or Config.BET_AMOUNT
    poll_interval = args.poll or Config.FAST_POLL_INTERVAL
    use_websocket = Config.USE_WEBSOCKET and not args.no_websocket

    # Parse wallets
    wallets = Config.COPY_WALLETS
    if args.wallets:
        wallets = [w.strip() for w in args.wallets.split(",") if w.strip()]

    if not wallets:
        print("Error: No wallets to copy.")
        print("Set COPY_WALLETS in .env or use --wallets flag")
        print("\nExample:")
        print("  python copybot_v2.py --paper --wallets 0x1d0034134e339a309700ff2d34e99fa2d48b0313")
        sys.exit(1)

    # === INITIALIZATION ===
    log("Initializing v2 copytrade bot...")

    # Fast REST client with connection pooling
    client = PolymarketClient(timeout=Config.REST_TIMEOUT)

    # Pre-fetch upcoming markets
    log("Pre-fetching upcoming BTC 5-min markets...")
    upcoming = client.get_upcoming_market_timestamps(count=5)
    prefetched = client.prefetch_markets(upcoming)
    log(f"  Cached {prefetched}/{len(upcoming)} markets")

    # Market data cache with optional WebSocket
    market_cache: MarketDataCache | None = None
    if use_websocket:
        try:
            market_cache = MarketDataCache(use_websocket=True)
            market_cache.start()
            time.sleep(1)  # Wait for connection
            if market_cache.ws_connected:
                log("  WebSocket connected for orderbook data")
            else:
                log("  WebSocket connection pending...")
        except Exception as e:
            log(f"  WebSocket init failed: {e}, using REST only")
            use_websocket = False

    # Fast hybrid monitor (REST polling for activity)
    monitor = HybridCopytradeMonitor(wallets, poll_interval=poll_interval)

    # Load trading state
    state = TradingState.load()
    if args.bankroll:
        state.bankroll = args.bankroll

    # Initialize trader
    if paper_mode:
        trader = PaperTrader()
        log("Paper trading mode (realistic simulation)")
    else:
        trader = LiveTrader()
        log("LIVE trading mode - Real money!")

    log(f"Copying {len(wallets)} wallet(s):")
    for w in wallets:
        log(f"  {w}")
    log(f"Config: amount=${bet_amount:.2f}, bankroll=${state.bankroll:.2f}")
    log(f"Timing: poll={poll_interval}s, timeout={Config.REST_TIMEOUT}s, ws={'on' if use_websocket else 'off'}")
    log("")

    # Track what markets we've already copied
    copied_markets: set[tuple[str, int]] = set()  # (wallet, market_ts)
    pending: list = []
    session_wins = 0
    session_losses = 0
    session_pnl = 0.0

    # Show recent trades from copied wallets
    log("Recent BTC 5-min trades from copied wallets:")
    for wallet in wallets:
        recent = monitor.get_latest_btc_5m_trades(wallet, limit=3)
        for sig in recent:
            log(f"  {sig.trader_name}: {sig.side} {sig.direction} @ {sig.price:.2f} (${sig.usdc_amount:.2f})")
    log("")

    # Stats tracking
    last_stats_time = time.time()
    polls_since_stats = 0

    while running:
        try:
            now = int(time.time())
            poll_start = time.time()

            # === SETTLE PENDING TRADES ===
            for trade in list(pending):
                market = client.get_market(trade.timestamp)
                if market and market.closed and market.outcome:
                    state.settle_trade(trade, market.outcome)
                    won = trade.direction == market.outcome

                    if won:
                        session_wins += 1
                    else:
                        session_losses += 1
                    session_pnl += trade.pnl

                    total_settled = session_wins + session_losses
                    win_rate = (session_wins / total_settled * 100) if total_settled > 0 else 0

                    emoji = "✓ WIN" if won else "✗ LOSS"
                    fee_info = f" (fee: {trade.fee_pct:.1%})" if won and trade.fee_pct > 0 else ""
                    log(
                        f"[{emoji}] {trade.direction.upper()} @ {trade.execution_price:.2f} -> {market.outcome.upper()} "
                        f"| PnL: ${trade.pnl:+.2f}{fee_info}"
                    )
                    log(
                        f"       Session: {session_wins}W/{session_losses}L ({win_rate:.0f}%) "
                        f"| PnL: ${session_pnl:+.2f} | Bankroll: ${state.bankroll:.2f} | Pending: {len(pending)-1}"
                    )
                    pending.remove(trade)
                    state.save()

            # === CHECK IF WE CAN TRADE ===
            can_trade, reason = state.can_trade()
            if not can_trade:
                if "Bankroll too low" in reason or "Max daily loss" in reason:
                    total_settled = session_wins + session_losses
                    win_rate = (session_wins / total_settled * 100) if total_settled > 0 else 0
                    log(f"❌ STOPPING: {reason}")
                    log(
                        f"   Session: {session_wins}W/{session_losses}L ({win_rate:.0f}%) "
                        f"| PnL: ${session_pnl:+.2f} | Final bankroll: ${state.bankroll:.2f}"
                    )
                    break
                else:
                    time.sleep(30)
                    continue

            # === POLL FOR NEW SIGNALS (Fast polling) ===
            signals = monitor.poll()
            polls_since_stats += 1

            for sig in signals:
                # Skip if already copied this market from this wallet
                key = (sig.wallet, sig.market_ts)
                if key in copied_markets:
                    continue

                # Skip SELL signals (we only copy buys for now)
                if sig.side != "BUY":
                    log(f"[skip] {sig.trader_name} SELL {sig.direction} (only copying BUYs)")
                    copied_markets.add(key)
                    continue

                # Check if market is still tradeable
                market = client.get_market(sig.market_ts)
                if not market:
                    log(f"[skip] Market not found for ts={sig.market_ts}")
                    copied_markets.add(key)
                    continue

                if market.closed:
                    log(f"[skip] Market already closed: {market.slug}")
                    copied_markets.add(key)
                    continue

                if not market.accepting_orders:
                    log(f"[skip] Market not accepting orders: {market.slug}")
                    copied_markets.add(key)
                    continue

                # === COPY THE TRADE ===
                direction = sig.direction.lower()
                amount = min(bet_amount, state.bankroll)
                amount = max(Config.MIN_BET, amount)

                # Calculate copy delay
                now_ms = int(time.time() * 1000)
                trader_ts_ms = sig.trade_ts * 1000
                copy_delay_ms = now_ms - trader_ts_ms

                delay_sec = copy_delay_ms / 1000
                log(
                    f"[COPY] {sig.trader_name}: {sig.direction.upper()} @ {sig.price:.2f} (${sig.usdc_amount:.0f}) "
                    f"-> Betting ${amount:.2f} | Delay: {delay_sec:.1f}s"
                )

                trade = trader.place_bet(
                    market=market,
                    direction=direction,
                    amount=amount,
                    confidence=0.6,
                    streak_length=0,
                    strategy="copytrade",
                    copied_from=sig.wallet,
                    trader_name=sig.trader_name,
                    trader_direction=sig.direction,
                    trader_amount=sig.usdc_amount,
                    trader_price=sig.price,
                    trader_timestamp=sig.trade_ts,
                    copy_delay_ms=copy_delay_ms,
                )

                if trade is None:
                    log(f"[skip] Order rejected for {sig.trader_name}")
                    copied_markets.add(key)
                    continue

                state.record_trade(trade)
                copied_markets.add(key)
                pending.append(trade)
                state.save()

                total_settled = session_wins + session_losses
                win_rate = (session_wins / total_settled * 100) if total_settled > 0 else 0
                log(
                    f"       Placed #{len(copied_markets)} | Pending: {len(pending)} "
                    f"| Session: {session_wins}W/{session_losses}L ({win_rate:.0f}%) ${session_pnl:+.2f}"
                )

            # === HEARTBEAT (every ~30s) ===
            if time.time() - last_stats_time >= 30:
                total_settled = session_wins + session_losses
                win_rate = (session_wins / total_settled * 100) if total_settled > 0 else 0
                stats = f"{session_wins}W/{session_losses}L" if total_settled > 0 else "no trades yet"

                # Calculate unrealized PnL for pending trades
                unrealized_pnl = 0.0
                pending_status = []
                for trade in pending:
                    try:
                        market = client.get_market(trade.timestamp)
                        if market:
                            current_price = market.up_price if trade.direction == "up" else market.down_price
                            exec_price = trade.execution_price if trade.execution_price > 0 else trade.entry_price
                            shares = trade.amount / exec_price if exec_price > 0 else 0

                            win_prob = current_price
                            gross_win = shares - trade.amount
                            fee_on_win = gross_win * trade.fee_pct if gross_win > 0 else 0
                            net_win = gross_win - fee_on_win
                            ev = (win_prob * net_win) + ((1 - win_prob) * (-trade.amount))
                            unrealized_pnl += ev

                            implied_winner = "up" if market.up_price > market.down_price else "down"
                            status_icon = "↑" if trade.direction == implied_winner else "↓"
                            pending_status.append(f"{trade.direction[0].upper()}{status_icon}{current_price:.0%}")
                    except Exception:
                        pass

                # Build status line
                ws_status = ""
                if use_websocket and market_cache:
                    ws_status = f" | WS: {'✓' if market_cache.ws_connected else '✗'}"

                log(
                    f"... Pending: {len(pending)} | Copied: {len(copied_markets)} "
                    f"| {stats} | PnL: ${session_pnl:+.2f} | Bank: ${state.bankroll:.2f}"
                    f"{ws_status} | Polls: {polls_since_stats} ({monitor.avg_poll_latency_ms:.0f}ms avg)"
                )

                if pending_status:
                    log(f"    Pending trades: {', '.join(pending_status)} | Unrealized: ${unrealized_pnl:+.2f}")

                last_stats_time = time.time()
                polls_since_stats = 0

                # Pre-fetch upcoming markets periodically
                upcoming = client.get_upcoming_market_timestamps(count=3)
                client.prefetch_markets(upcoming)

            # === SLEEP ===
            # Calculate how long the poll took and sleep the remainder
            poll_duration = time.time() - poll_start
            sleep_time = max(0.1, poll_interval - poll_duration)
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(5)

    # Cleanup
    if market_cache:
        market_cache.stop()

    state.save()
    log(f"State saved. Bankroll: ${state.bankroll:.2f}")
    log(f"Session: {state.daily_bets} bets, PnL: ${state.daily_pnl:+.2f}")
    log(f"Monitor stats: {monitor.stats}")


if __name__ == "__main__":
    main()
