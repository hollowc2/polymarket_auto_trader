#!/usr/bin/env python3
"""
Polymarket BTC 5-Min Copytrade Bot v2

Enhanced version with:
- WebSocket for real-time orderbook data (~100ms latency)
- Fast REST polling for wallet activity (1-2s vs 5s)
- Connection pooling and shorter timeouts
- Market pre-fetching and token ID caching
- Better error handling and graceful degradation
- Circuit breaker for API failure protection
- Rate limiting to prevent hitting API limits
- Structured logging for production debugging
"""

import argparse
import signal
import sys
import time
from datetime import datetime

from config import Config, LOCAL_TZ, TIMEZONE_NAME
from copytrade import CopySignal
from copytrade_ws import HybridCopytradeMonitor
from logging_config import get_logger, StructuredLogger
from polymarket import PolymarketClient
from polymarket_ws import MarketDataCache
from resilience import CircuitBreaker, RateLimiter, HealthCheck, CircuitOpenError, categorize_error, ErrorCategory
from trader import LiveTrader, PaperTrader, TradingState

running = True
log = get_logger("copybot")


def handle_signal(sig, frame):
    global running
    log.info("shutdown_requested", signal=sig)
    running = False


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
    # Initialize resilience components
    api_circuit = CircuitBreaker(name="polymarket_api")
    rate_limiter = RateLimiter()
    health = HealthCheck()

    # Fast REST client with connection pooling
    client = PolymarketClient(timeout=Config.REST_TIMEOUT)

    # Register health checks
    health.register("api", lambda: {"healthy": True, "timeout": Config.REST_TIMEOUT})
    health.register("circuit_breaker", lambda: {
        "healthy": api_circuit.state.value != "open",
        "state": api_circuit.state.value,
        "failures": api_circuit._failures,
    })

    # Pre-fetch upcoming markets (silent)
    upcoming = client.get_upcoming_market_timestamps(count=5)
    client.prefetch_markets(upcoming)

    # Market data cache with optional WebSocket
    market_cache: MarketDataCache | None = None
    if use_websocket:
        try:
            market_cache = MarketDataCache(use_websocket=True)
            market_cache.start()
            time.sleep(1)  # Wait for connection

            # Register WebSocket health check
            health.register("websocket", lambda: {
                "healthy": market_cache.ws_connected if market_cache else False,
                "stats": market_cache.stats if market_cache else {},
            })
        except Exception as e:
            log.warning("websocket_init_failed", error=str(e))
            use_websocket = False

    # Fast hybrid monitor (REST polling for activity)
    monitor = HybridCopytradeMonitor(wallets, poll_interval=poll_interval)

    # Register monitor health check
    health.register("monitor", lambda: {
        "healthy": True,
        "polls": monitor.polls,
        "avg_latency_ms": monitor.avg_poll_latency_ms,
    })

    # Load trading state
    state = TradingState.load()
    if args.bankroll:
        state.bankroll = args.bankroll

    # Initialize trader
    if paper_mode:
        trader = PaperTrader(market_cache=market_cache)
    else:
        trader = LiveTrader(market_cache=market_cache)

    # Startup banner
    mode_str = "PAPER" if paper_mode else "LIVE"
    ws_str = "✓" if use_websocket else "✗"
    log.status_line(f"═══ Copybot v2 ({mode_str}) ═══")
    log.status_line(f"Amount: ${bet_amount:.2f} | Bankroll: ${state.bankroll:.2f} | Poll: {poll_interval}s | WS: {ws_str}")
    log.status_line(f"Tracking {len(wallets)} wallet(s)")
    for w in wallets:
        log.status_line(f"  └─ {w[:10]}...{w[-6:]}")

    # Track what markets we've already copied (initialize from state to avoid duplicates)
    copied_markets: set[tuple[str, int]] = set()
    for t in state.trades:
        if t.copied_from and t.timestamp:
            copied_markets.add((t.copied_from, t.timestamp))

    # Initialize pending from unsettled trades in state (survives restart)
    pending: list = [t for t in state.trades if t.outcome is None]
    if pending:
        log.status_line(f"Resuming {len(pending)} unsettled trade(s) from previous session")
    if copied_markets:
        log.status_line(f"Loaded {len(copied_markets)} previously copied market(s)")

    session_wins = 0
    session_losses = 0
    session_pnl = 0.0

    # Show recent trades from copied wallets
    for wallet in wallets:
        recent = monitor.get_latest_btc_5m_trades(wallet, limit=1)
        for sig in recent:
            log.status_line(f"  Recent: {sig.trader_name} {sig.side} {sig.direction.upper()} @ {sig.price:.2f} (${sig.usdc_amount:.2f})")
    print()  # Blank line before main loop

    # Stats tracking
    last_stats_time = time.time()
    polls_since_stats = 0

    bankrupt = False  # Flag for immediate exit on bankruptcy

    while running and not bankrupt:
        try:
            now = int(time.time())
            poll_start = time.time()

            # === SETTLE PENDING TRADES ===
            # Sort by timestamp to settle in chronological order (oldest markets first)
            pending.sort(key=lambda t: t.timestamp)

            # BTC 5-min markets resolve ~30-90 seconds after window closes
            for trade in list(pending):
                try:
                    # Use circuit breaker for API calls
                    if not api_circuit.allow_request():
                        log.warning("circuit_open", action="settle_trade")
                        break

                    # Check rate limit
                    if not rate_limiter.allow_request():
                        wait = rate_limiter.time_until_allowed()
                        log.debug("rate_limited", wait_time=wait)
                        time.sleep(min(wait, 0.5))
                        continue

                    # IMPORTANT: use_cache=False to get fresh resolution status
                    market = client.get_market(trade.timestamp, use_cache=False)
                    api_circuit.record_success()

                    if market and market.closed and market.outcome:
                        state.settle_trade(trade, market.outcome, market=market)
                        won = trade.direction == market.outcome

                        if won:
                            session_wins += 1
                        else:
                            session_losses += 1
                        session_pnl += trade.pnl

                        log.trade_settled(
                            market=trade.market_slug,
                            direction=trade.direction,
                            outcome=market.outcome,
                            pnl=trade.pnl,
                            won=won,
                            fee_pct=trade.fee_pct if won else 0,
                            bankroll=state.bankroll,
                            pending=len(pending) - 1,
                            wins=session_wins,
                            losses=session_losses,
                        )
                        pending.remove(trade)
                        state.save()

                        # === IMMEDIATE BANKRUPTCY CHECK ===
                        # Just like real trading: if you can't afford the next bet, you're done
                        if state.bankroll < Config.MIN_BET:
                            log.status_line("")
                            log.status_line("╔════════════════════════════════════════╗")
                            log.status_line("║  SIMULATION ENDED - INSUFFICIENT FUNDS ║")
                            log.status_line("╠════════════════════════════════════════╣")
                            log.status_line(f"║  Final Bankroll: ${state.bankroll:.2f}".ljust(41) + "║")
                            log.status_line(f"║  Minimum Required: ${Config.MIN_BET:.2f}".ljust(41) + "║")
                            log.status_line(f"║  Session P&L: ${session_pnl:+.2f}".ljust(41) + "║")
                            log.status_line(f"║  Record: {session_wins}W / {session_losses}L".ljust(41) + "║")
                            log.status_line("╚════════════════════════════════════════╝")
                            bankrupt = True
                            break  # Exit the for loop

                except CircuitOpenError:
                    log.warning("circuit_open", action="settle_trade")
                    break
                except Exception as e:
                    api_circuit.record_failure()
                    category = categorize_error(e)
                    if category == ErrorCategory.FATAL:
                        log.error("settle_error_fatal", error=str(e))
                    else:
                        log.warning("settle_error_retry", error=str(e))

            # Exit immediately if bankrupt
            if bankrupt:
                break

            # === CHECK IF WE CAN TRADE ===
            can_trade, reason = state.can_trade()
            if not can_trade:
                if "Bankroll too low" in reason:
                    log.status_line("")
                    log.status_line("╔════════════════════════════════════════╗")
                    log.status_line("║  SIMULATION ENDED - INSUFFICIENT FUNDS ║")
                    log.status_line("╚════════════════════════════════════════╝")
                    log.status_line(f"Bankroll ${state.bankroll:.2f} < Min bet ${Config.MIN_BET:.2f}")
                    break
                elif "Max daily loss" in reason:
                    log.status_line("")
                    log.status_line("╔════════════════════════════════════════╗")
                    log.status_line("║  SIMULATION ENDED - DAILY LOSS LIMIT   ║")
                    log.status_line("╚════════════════════════════════════════╝")
                    log.status_line(f"Daily P&L: ${state.daily_pnl:.2f} exceeded -${Config.MAX_DAILY_LOSS:.2f} limit")
                    break
                elif "Max daily bets" in reason:
                    log.status_line(f"Daily bet limit reached ({Config.MAX_DAILY_BETS}), waiting for reset...")
                    time.sleep(30)
                    continue
                else:
                    time.sleep(30)
                    continue

            # === CHECK CIRCUIT BREAKER ===
            if api_circuit.state.value == "open":
                log.warning("circuit_open_wait", recovery_time=Config.CIRCUIT_BREAKER_RECOVERY_TIME)
                time.sleep(5)
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
                    log.debug("skip_sell", trader=sig.trader_name, direction=sig.direction)
                    copied_markets.add(key)
                    continue

                try:
                    # Check rate limit before API call
                    if not rate_limiter.allow_request():
                        wait = rate_limiter.time_until_allowed()
                        log.debug("rate_limited", wait_time=wait)
                        time.sleep(min(wait, 0.5))

                    # Check circuit breaker
                    if not api_circuit.allow_request():
                        log.warning("circuit_open", action="get_market")
                        break

                    # Check if market is still tradeable
                    market = client.get_market(sig.market_ts)
                    api_circuit.record_success()

                    if not market:
                        log.debug("skip_market_not_found", market_ts=sig.market_ts)
                        copied_markets.add(key)
                        continue

                    if market.closed:
                        log.debug("skip_market_closed", market=market.slug)
                        copied_markets.add(key)
                        continue

                    if not market.accepting_orders:
                        log.debug("skip_not_accepting", market=market.slug)
                        copied_markets.add(key)
                        continue

                except CircuitOpenError:
                    log.warning("circuit_open", action="get_market")
                    break
                except Exception as e:
                    api_circuit.record_failure()
                    log.error("market_fetch_error", error=str(e))
                    continue

                # === COPY THE TRADE ===
                direction = sig.direction.lower()

                # Strict bankroll check - can't bet more than you have
                if state.bankroll < Config.MIN_BET:
                    log.status_line("")
                    log.status_line("╔════════════════════════════════════════╗")
                    log.status_line("║  SIMULATION ENDED - INSUFFICIENT FUNDS ║")
                    log.status_line("╚════════════════════════════════════════╝")
                    log.status_line(f"Cannot place ${Config.MIN_BET:.2f} bet with ${state.bankroll:.2f} bankroll")
                    bankrupt = True
                    break

                # Bet the requested amount, but never more than bankroll
                amount = min(bet_amount, state.bankroll)
                if amount < Config.MIN_BET:
                    log.warning("skip_insufficient_funds",
                        requested=bet_amount, available=state.bankroll, minimum=Config.MIN_BET)
                    copied_markets.add(key)
                    continue

                # Calculate copy delay
                now_ms = int(time.time() * 1000)
                trader_ts_ms = sig.trade_ts * 1000
                copy_delay_ms = now_ms - trader_ts_ms

                log.copy_signal(
                    trader=sig.trader_name,
                    direction=direction,
                    amount=sig.usdc_amount,
                    price=sig.price,
                    delay_ms=copy_delay_ms,
                    our_amount=amount,
                )

                # === SESSION TRACKING FOR PATTERN ANALYSIS ===
                session_trade_number = len(copied_markets) + 1

                # Calculate consecutive wins/losses from recent settled trades
                consecutive_wins = 0
                consecutive_losses = 0
                for t in reversed(state.trades):
                    if t.outcome is None:
                        continue  # Skip pending
                    if t.won:
                        if consecutive_losses == 0:
                            consecutive_wins += 1
                        else:
                            break
                    else:
                        if consecutive_wins == 0:
                            consecutive_losses += 1
                        else:
                            break

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
                    # Session tracking
                    session_trade_number=session_trade_number,
                    session_wins_before=session_wins,
                    session_losses_before=session_losses,
                    session_pnl_before=session_pnl,
                    bankroll_before=state.bankroll,
                    consecutive_wins=consecutive_wins,
                    consecutive_losses=consecutive_losses,
                )

                if trade is None:
                    log.warning("order_rejected", trader=sig.trader_name)
                    copied_markets.add(key)
                    continue

                state.record_trade(trade)
                copied_markets.add(key)
                pending.append(trade)
                state.save()

                log.trade_placed(
                    trade_num=len(copied_markets),
                    pending=len(pending),
                    wins=session_wins,
                    losses=session_losses,
                    pnl=session_pnl,
                )

            # Exit main loop if bankrupt during signal processing
            if bankrupt:
                break

            # === HEARTBEAT (every ~60s) ===
            if time.time() - last_stats_time >= 60:
                # Calculate unrealized PnL for pending trades
                unrealized_pnl = 0.0
                pending_info = []
                for trade in pending:
                    try:
                        if rate_limiter.allow_request():
                            # use_cache=False for fresh prices during heartbeat
                            market = client.get_market(trade.timestamp, use_cache=False)
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

                                # Track for pending display
                                implied_winner = "up" if market.up_price > market.down_price else "down"
                                pending_info.append({
                                    "direction": trade.direction,
                                    "current_prob": current_price,
                                    "likely_win": trade.direction == implied_winner,
                                })
                    except Exception:
                        pass

                # Compact heartbeat log
                log.heartbeat(
                    pending=len(pending),
                    wins=session_wins,
                    losses=session_losses,
                    pnl=session_pnl,
                    bankroll=state.bankroll,
                    unrealized=unrealized_pnl,
                    ws_connected=market_cache.ws_connected if market_cache else False,
                )

                # Show pending trades on separate line if any
                if pending_info:
                    log.pending_trades(pending_info)

                last_stats_time = time.time()
                polls_since_stats = 0

                # Pre-fetch upcoming markets periodically
                try:
                    if api_circuit.allow_request():
                        upcoming = client.get_upcoming_market_timestamps(count=3)
                        client.prefetch_markets(upcoming)
                        api_circuit.record_success()
                except Exception as e:
                    api_circuit.record_failure()
                    log.debug("prefetch_error", error=str(e))

            # === SLEEP ===
            # Calculate how long the poll took and sleep the remainder
            poll_duration = time.time() - poll_start
            sleep_time = max(0.1, poll_interval - poll_duration)
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            break
        except Exception as e:
            category = categorize_error(e)
            if category == ErrorCategory.FATAL:
                log.error("fatal_error", error=str(e))
                break
            else:
                log.warning("recoverable_error", error=str(e), category=category.value)
                time.sleep(5)

    # Cleanup
    print()  # Blank line
    if bankrupt:
        log.status_line("═══ SIMULATION TERMINATED ═══")
    else:
        log.status_line("═══ Shutdown ═══")

    if market_cache:
        market_cache.stop()

    state.save()

    total = session_wins + session_losses
    win_rate = (session_wins / total * 100) if total > 0 else 0
    log.status_line(f"Session: {session_wins}W/{session_losses}L ({win_rate:.0f}%) | PnL: ${session_pnl:+.2f}")
    log.status_line(f"Final bankroll: ${state.bankroll:.2f}")

    # Exit with error code if bankrupt (like a real trading system would)
    if bankrupt:
        log.status_line("Exit code: 1 (insufficient funds)")
        sys.exit(1)


if __name__ == "__main__":
    main()
