#!/usr/bin/env python3
# DEPRECATED: Use polymarket_algo.* packages instead. This file exists for backward compatibility.
"""
Polymarket BTC 5-Min Copytrade Bot

Monitors specific wallets and copies their BTC 5-min trades.
"""

import argparse
import signal
import sys
import time
from datetime import datetime

from src.config import LOCAL_TZ, TIMEZONE_NAME, Config
from src.core.polymarket import PolymarketClient
from src.core.trader import LiveTrader, PaperTrader, TradingState

# Try to use the faster hybrid monitor if available
try:
    from src.strategies.copytrade_ws import HybridCopytradeMonitor

    USE_HYBRID_MONITOR = True
except ImportError:
    USE_HYBRID_MONITOR = False


running = True


def handle_signal(sig, _frame):
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
        description="Polymarket BTC 5-Min Copytrade Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Environment Variables (.env):
  PAPER_TRADE        Paper trading mode (default: true)
  BET_AMOUNT         Bet amount in USD (default: 5)
  MIN_BET            Minimum bet size (default: 1)
  MAX_DAILY_BETS     Maximum bets per day (default: 50)
  MAX_DAILY_LOSS     Stop trading after this loss (default: 50)
  COPY_WALLETS       Comma-separated wallet addresses to copy
  COPY_POLL_INTERVAL Seconds between polling for new trades (default: 5)
  TIMEZONE           Display timezone (default: Asia/Jakarta)
  PRIVATE_KEY        Polygon wallet private key (required for live)

Current Configuration:
  Mode:              {"PAPER" if Config.PAPER_TRADE else "LIVE"}
  Bet Amount:        ${Config.BET_AMOUNT}
  Min Bet:           ${Config.MIN_BET}
  Max Daily Bets:    {Config.MAX_DAILY_BETS}
  Max Daily Loss:    ${Config.MAX_DAILY_LOSS}
  Poll Interval:     {Config.COPY_POLL_INTERVAL}s
  Timezone:          {TIMEZONE_NAME}
  Wallets:
    {wallet_list}

Realistic Simulation (Paper Mode):
  The paper trading mode simulates real trading costs:
  - Fees:          ~2.5% at 50c (from real API)
  - Spread:        Real bid-ask spread from orderbook
  - Slippage:      Calculated by walking the orderbook
  - Copy Delay:    Price impact of ~0.3% per second of delay

Examples:
  # Paper trade, copy specific wallet
  python copybot.py --paper --wallets 0x1234...

  # Paper trade, copy multiple wallets
  python copybot.py --paper --wallets 0x1234...,0x5678...

  # Paper trade with custom bet amount
  python copybot.py --paper --amount 20 --wallets 0x1234...

  # Paper trade with custom bankroll
  python copybot.py --paper --bankroll 500 --wallets 0x1234...

  # Live trading (requires PRIVATE_KEY in .env)
  python copybot.py --live --wallets 0x1234...

  # Use faster polling
  python copybot.py --paper --poll 2 --wallets 0x1234...

Finding Wallets to Copy:
  1. Go to https://polymarket.com/activity
  2. Find profitable BTC 5-min traders
  3. Click on their profile to get wallet address
  4. Use the address with --wallets

Related Commands:
  python history.py --stats                # View trading statistics
  python history.py --export csv           # Export trade history
  python bot.py --help                     # Streak strategy bot help
""",
    )
    parser.add_argument(
        "--paper",
        action="store_true",
        help=f"Force paper trading mode (current: {Config.PAPER_TRADE})",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Force live trading mode (requires PRIVATE_KEY)",
    )
    parser.add_argument(
        "--amount",
        type=float,
        metavar="USD",
        help=f"Bet amount in USD (default: {Config.BET_AMOUNT})",
    )
    parser.add_argument(
        "--bankroll",
        type=float,
        metavar="USD",
        help="Set starting bankroll (overrides saved state)",
    )
    parser.add_argument(
        "--wallets",
        type=str,
        metavar="ADDR",
        help="Comma-separated wallet addresses to copy",
    )
    parser.add_argument(
        "--poll",
        type=int,
        metavar="SEC",
        help=f"Poll interval in seconds (default: {Config.COPY_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--max-bets",
        type=int,
        metavar="N",
        help=f"Maximum daily bets (default: {Config.MAX_DAILY_BETS})",
    )
    parser.add_argument(
        "--max-loss",
        type=float,
        metavar="USD",
        help=f"Stop after this daily loss (default: {Config.MAX_DAILY_LOSS})",
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
    poll_interval = args.poll or Config.COPY_POLL_INTERVAL

    # Parse wallets
    wallets = Config.COPY_WALLETS
    if args.wallets:
        wallets = [w.strip() for w in args.wallets.split(",") if w.strip()]

    if not wallets:
        print("Error: No wallets to copy.")
        print("Set COPY_WALLETS in .env or use --wallets flag")
        print("\nExample:")
        print("  python copybot.py --paper --wallets 0x1d0034134e339a309700ff2d34e99fa2d48b0313")
        sys.exit(1)

    # Init - use faster hybrid monitor if available
    if USE_HYBRID_MONITOR:
        # Use faster polling (1.5s vs 5s default)
        effective_poll = min(poll_interval, Config.FAST_POLL_INTERVAL)
        monitor = HybridCopytradeMonitor(wallets, poll_interval=effective_poll)
        log(f"Using fast hybrid monitor (poll={effective_poll}s)")
    else:
        from src.strategies.copytrade import CopytradeMonitor

        monitor = CopytradeMonitor(wallets)

    # Use faster client with connection pooling
    client = PolymarketClient(timeout=Config.REST_TIMEOUT)

    # Pre-fetch upcoming markets for faster initial response
    log("Pre-fetching upcoming markets...")
    upcoming = client.get_upcoming_market_timestamps(count=3)
    client.prefetch_markets(upcoming)

    state = TradingState.load()
    if args.bankroll:
        state.bankroll = args.bankroll

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
    log(f"Limits: poll={poll_interval}s, timezone={TIMEZONE_NAME}")
    log("")

    # Track what markets we've already copied
    copied_markets: set[tuple[str, int]] = set()  # (wallet, market_ts)
    # Track pending trades
    pending: list = []
    # Session stats
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

    while running:
        try:
            now = int(time.time())

            # === SETTLE PENDING TRADES ===
            for trade in list(pending):
                market = client.get_market(trade.timestamp)
                if market and market.closed and market.outcome:
                    state.settle_trade(trade, market.outcome)
                    won = trade.direction == market.outcome

                    # Update session stats
                    if won:
                        session_wins += 1
                    else:
                        session_losses += 1
                    session_pnl += trade.pnl

                    # Calculate win rate
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
                        f"| PnL: ${session_pnl:+.2f} | Bankroll: ${state.bankroll:.2f} | Pending: {len(pending) - 1}"
                    )
                    pending.remove(trade)
                    state.save()

            # === CHECK IF WE CAN TRADE ===
            can_trade, reason = state.can_trade()
            if not can_trade:
                # Check if it's a bankroll issue (unrecoverable)
                if "Bankroll too low" in reason or "Max daily loss" in reason:
                    total_settled = session_wins + session_losses
                    win_rate = (session_wins / total_settled * 100) if total_settled > 0 else 0
                    log(f"❌ STOPPING: {reason}")
                    log(
                        f"   Session: {session_wins}W/{session_losses}L ({win_rate:.0f}%) "
                        f"| PnL: ${session_pnl:+.2f} | Final bankroll: ${state.bankroll:.2f}"
                    )
                    break  # Exit the main loop
                else:
                    # Other reasons (max daily bets) - just wait
                    log(f"Cannot trade: {reason}")
                    time.sleep(30)
                    continue

            # === POLL FOR NEW SIGNALS ===
            signals = monitor.poll()

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
                direction = sig.direction.lower()  # "up" or "down"
                # Use configured amount, capped at bankroll (no arbitrary 10% limit)
                amount = min(bet_amount, state.bankroll)
                amount = max(Config.MIN_BET, amount)

                # Calculate copy delay (milliseconds since trader's trade)
                now_ms = int(time.time() * 1000)
                trader_ts_ms = sig.trade_ts * 1000  # actual trade timestamp
                copy_delay_ms = now_ms - trader_ts_ms

                # Get current market price for our entry
                current_price = market.up_price if direction == "up" else market.down_price

                delay_sec = copy_delay_ms / 1000
                log(
                    f"[COPY] {sig.trader_name}: {sig.direction.upper()} @ {sig.price:.2f} (${sig.usdc_amount:.0f}) "
                    f"-> Betting ${amount:.2f} | Delay: {delay_sec:.1f}s"
                )

                trade = trader.place_bet(
                    market=market,
                    direction=direction,
                    amount=amount,
                    confidence=0.6,  # default confidence for copied trades
                    streak_length=0,
                    # Copytrade analysis fields
                    strategy="copytrade",
                    copied_from=sig.wallet,
                    trader_name=sig.trader_name,
                    trader_direction=sig.direction,
                    trader_amount=sig.usdc_amount,
                    trader_price=sig.price,
                    trader_timestamp=sig.trade_ts,  # when trader placed the trade
                    copy_delay_ms=copy_delay_ms,
                )

                # Handle rejected orders (e.g., below minimum size)
                if trade is None:
                    log(f"[skip] Order rejected for {sig.trader_name}")
                    copied_markets.add(key)
                    continue

                state.record_trade(trade)
                copied_markets.add(key)
                pending.append(trade)
                state.save()

                # Show current session status
                total_settled = session_wins + session_losses
                win_rate = (session_wins / total_settled * 100) if total_settled > 0 else 0
                log(
                    f"       Placed #{len(copied_markets)} | Pending: {len(pending)} "
                    f"| Session: {session_wins}W/{session_losses}L ({win_rate:.0f}%) ${session_pnl:+.2f}"
                )

            # === HEARTBEAT ===
            if now % 60 < Config.COPY_POLL_INTERVAL:
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
                            # Get current price for our direction
                            current_price = market.up_price if trade.direction == "up" else market.down_price
                            exec_price = trade.execution_price if trade.execution_price > 0 else trade.entry_price
                            shares = trade.amount / exec_price if exec_price > 0 else 0

                            # Calculate expected value
                            win_prob = current_price
                            gross_win = shares - trade.amount
                            fee_on_win = gross_win * trade.fee_pct if gross_win > 0 else 0
                            net_win = gross_win - fee_on_win
                            ev = (win_prob * net_win) + ((1 - win_prob) * (-trade.amount))
                            unrealized_pnl += ev

                            # Determine if winning or losing
                            implied_winner = "up" if market.up_price > market.down_price else "down"
                            status_icon = "↑" if trade.direction == implied_winner else "↓"
                            pending_status.append(f"{trade.direction[0].upper()}{status_icon}{current_price:.0%}")
                    except Exception:
                        pass

                # Show heartbeat
                log(
                    f"... Pending: {len(pending)} | Copied: {len(copied_markets)} "
                    f"| {stats} | PnL: ${session_pnl:+.2f} | Bank: ${state.bankroll:.2f}"
                )
                # Show pending trade status if any
                if pending_status:
                    log(f"    Pending trades: {', '.join(pending_status)} | Unrealized: ${unrealized_pnl:+.2f}")

                # Show detailed pending status every 5 minutes
                if now % 300 < Config.COPY_POLL_INTERVAL and pending:
                    log("    --- Pending Trade Details ---")
                    for trade in pending:
                        try:
                            market = client.get_market(trade.timestamp)
                            if market:
                                current_price = market.up_price if trade.direction == "up" else market.down_price
                                implied_winner = "up" if market.up_price > market.down_price else "down"
                                likely = "WIN" if trade.direction == implied_winner else "LOSS"
                                exec_price = trade.execution_price if trade.execution_price > 0 else trade.entry_price
                                shares = trade.amount / exec_price if exec_price > 0 else 0

                                # Calculate potential outcomes
                                gross_win = shares - trade.amount
                                fee_on_win = gross_win * trade.fee_pct if gross_win > 0 else 0
                                net_win = gross_win - fee_on_win

                                log(
                                    f"    {trade.direction.upper()} ${trade.amount:.2f} @ {exec_price:.2f} "
                                    f"| Now: {current_price:.0%} (LIKELY {likely}) "
                                    f"| If win: ${net_win:+.2f} | If loss: ${-trade.amount:+.2f}"
                                )
                        except Exception:
                            pass

            time.sleep(Config.COPY_POLL_INTERVAL)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(10)

    # Save state on exit
    state.save()
    log(f"State saved. Bankroll: ${state.bankroll:.2f}")
    log(f"Session: {state.daily_bets} bets, PnL: ${state.daily_pnl:+.2f}")


if __name__ == "__main__":
    main()
