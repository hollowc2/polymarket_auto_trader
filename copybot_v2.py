#!/usr/bin/env python3
# DEPRECATED: Use polymarket_algo.* packages instead. This file exists for backward compatibility.
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
import os
import queue
import re
import signal
import sys
import time
from datetime import datetime, timedelta

from src.config import LOCAL_TZ, TIMEZONE_NAME, Config
from src.core.polymarket import DelayImpactModel, PolymarketClient
from src.core.polymarket_ws import MarketDataCache, TradeEvent
from src.core.trader import LiveTrader, PaperTrader, TradingState
from src.infra.logging_config import get_logger
from src.infra.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    ErrorCategory,
    HealthCheck,
    RateLimiter,
    categorize_error,
)
from src.strategies.copytrade import CopySignal
from src.strategies.copytrade_ws import HybridCopytradeMonitor
from src.strategies.selective_filter import SelectiveFilter

# Pattern for BTC 5-min markets
BTC_5M_PATTERN = re.compile(r"^btc-updown-5m-(\d+)$")

running = True
log = get_logger("copybot")


def handle_signal(sig, _frame):
    global running
    log.info("shutdown_requested", signal=sig)
    running = False


def estimate_execution_from_book(book: dict, side: str, amount_usd: float, copy_delay_ms: int = 0):
    """Estimate execution details from a pre-fetched orderbook snapshot."""
    bids = book.get("bids", []) if book else []
    asks = book.get("asks", []) if book else []

    if not bids or not asks:
        return {
            "execution_price": 0.5,
            "spread": 0.0,
            "slippage_pct": 0.0,
            "fill_pct": 100.0,
            "delay_impact_pct": 0.0,
            "delay_breakdown": None,
            "best_bid": 0.0,
            "best_ask": 0.0,
            "depth_at_best": 0.0,
        }

    asks_sorted = sorted(asks, key=lambda x: float(x["price"]))
    bids_sorted = sorted(bids, key=lambda x: float(x["price"]), reverse=True)

    best_ask = float(asks_sorted[0]["price"])
    best_bid = float(bids_sorted[0]["price"])
    spread = best_ask - best_bid

    levels = asks_sorted if side == "BUY" else bids_sorted
    best_level = levels[0]
    depth_at_best = float(best_level["price"]) * float(best_level["size"])

    remaining_usd = amount_usd
    total_shares = 0.0
    total_cost = 0.0

    for level in levels:
        price = float(level["price"])
        size = float(level["size"])
        level_value = price * size
        if remaining_usd <= 0:
            break
        if level_value >= remaining_usd:
            shares_to_take = remaining_usd / price
            total_shares += shares_to_take
            total_cost += remaining_usd
            remaining_usd = 0
        else:
            total_shares += size
            total_cost += level_value
            remaining_usd -= level_value

    filled_amount = amount_usd - remaining_usd
    fill_pct = (filled_amount / amount_usd * 100) if amount_usd > 0 else 100.0

    if total_shares <= 0:
        execution_price = (best_ask + best_bid) / 2
        slippage_pct = 0.0
    else:
        execution_price = total_cost / total_shares
        ref_price = best_ask if side == "BUY" else best_bid
        if ref_price > 0:
            if side == "BUY":
                slippage_pct = (execution_price - ref_price) / ref_price * 100
            else:
                slippage_pct = (ref_price - execution_price) / ref_price * 100
        else:
            slippage_pct = 0.0

    delay_impact_pct = 0.0
    delay_breakdown = None
    if copy_delay_ms > 0:
        delay_model = DelayImpactModel()
        delay_impact_pct, delay_breakdown = delay_model.calculate_impact(
            delay_ms=copy_delay_ms,
            order_size=amount_usd,
            depth_at_best=depth_at_best,
            spread=spread,
            side=side,
        )
        if side == "BUY":
            execution_price *= 1 + delay_impact_pct / 100
        else:
            execution_price *= 1 - delay_impact_pct / 100
        execution_price = max(0.01, min(0.99, execution_price))

    return {
        "execution_price": execution_price,
        "spread": spread,
        "slippage_pct": max(0.0, slippage_pct),
        "fill_pct": fill_pct,
        "delay_impact_pct": delay_impact_pct,
        "delay_breakdown": delay_breakdown,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "depth_at_best": depth_at_best,
    }


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
  Mode:              {"PAPER" if Config.PAPER_TRADE else "LIVE"}
  Bet Amount:        ${Config.BET_AMOUNT}
  Min Bet:           ${Config.MIN_BET}
  Max Daily Bets:    {Config.MAX_DAILY_BETS}
  Max Daily Loss:    ${Config.MAX_DAILY_LOSS}
  Poll Interval:     {Config.FAST_POLL_INTERVAL}s (fast mode)
  REST Timeout:      {Config.REST_TIMEOUT}s
  WebSocket:         {"Enabled" if Config.USE_WEBSOCKET else "Disabled"}
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
        type=float,
        metavar="SEC",
        help=f"Poll interval in seconds (default: {Config.FAST_POLL_INTERVAL})",
    )
    parser.add_argument("--no-websocket", action="store_true", help="Disable WebSocket (REST only mode)")
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
    parser.add_argument(
        "--retry",
        type=int,
        metavar="N",
        default=0,
        help="Retry N times on bankrupt (resets bankroll each retry)",
    )
    parser.add_argument(
        "--selective",
        action="store_true",
        help=f"Enable selective trade filter (default: {Config.SELECTIVE_FILTER})",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        metavar="SEC",
        help=f"Selective filter max copy delay in seconds (default: {Config.SELECTIVE_MAX_DELAY_MS / 1000:.1f})",
    )
    parser.add_argument(
        "--min-fill",
        type=float,
        metavar="PRICE",
        help=f"Selective filter minimum fill price (default: {Config.SELECTIVE_MIN_FILL_PRICE})",
    )
    parser.add_argument(
        "--max-fill",
        type=float,
        metavar="PRICE",
        help=f"Selective filter maximum fill price (default: {Config.SELECTIVE_MAX_FILL_PRICE})",
    )
    # Internal: tracks current retry attempt (for subprocess restarts)
    parser.add_argument("--_retry_count", type=int, default=0, help=argparse.SUPPRESS)
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

    selective_enabled = Config.SELECTIVE_FILTER or args.selective
    selective_overrides = {}
    if args.max_delay is not None:
        selective_overrides["max_delay_ms"] = int(args.max_delay * 1000)
    if args.min_fill is not None:
        selective_overrides["min_fill_price"] = args.min_fill
    if args.max_fill is not None:
        selective_overrides["max_fill_price"] = args.max_fill
    selective_filter = SelectiveFilter(config=selective_overrides) if selective_enabled else None

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
    health.register(
        "circuit_breaker",
        lambda: {
            "healthy": api_circuit.state.value != "open",
            "state": api_circuit.state.value,
            "failures": api_circuit._failures,
        },
    )

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
            health.register(
                "websocket",
                lambda: {
                    "healthy": market_cache.ws_connected if market_cache else False,
                    "stats": market_cache.stats if market_cache else {},
                },
            )
        except Exception as e:
            log.warning("websocket_init_failed", error=str(e))
            use_websocket = False

    # Fast hybrid monitor (REST polling for activity)
    monitor = HybridCopytradeMonitor(wallets, poll_interval=poll_interval)

    # Signal queue for thread-safe delivery from WebSocket callbacks
    signal_queue: queue.Queue[CopySignal] = queue.Queue()

    # Wire up WebSocket trade callback for immediate polling
    if market_cache:

        def on_btc_trade(trade: TradeEvent):
            """Callback when WebSocket detects a trade on BTC 5-min market."""
            # Check if this is a BTC 5-min market
            if trade.market_id and BTC_5M_PATTERN.match(trade.market_id):
                # Trigger immediate poll to detect the trade details
                signals = monitor.trigger_immediate_poll(trade.market_id)
                for sig in signals:
                    signal_queue.put(sig)
                    log.debug(
                        "ws_triggered_signal",
                        market=trade.market_id,
                        trader=sig.trader_name,
                        direction=sig.direction,
                        latency_ms=int((time.time() - trade.timestamp) * 1000) if trade.timestamp else 0,
                    )

        market_cache.on_trade(on_btc_trade)
        log.debug("websocket_callback_registered")

    # Register monitor health check
    health.register(
        "monitor",
        lambda: {
            "healthy": True,
            "polls": monitor.polls,
            "triggered_polls": monitor._triggered_polls,
            "avg_latency_ms": monitor.avg_poll_latency_ms,
        },
    )

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
    log.status_line(
        f"Amount: ${bet_amount:.2f} | Bankroll: ${state.bankroll:.2f} | Poll: {poll_interval}s | WS: {ws_str}"
    )
    if selective_filter:
        log.status_line(
            f"Selective: ON | delay<={selective_filter.max_delay_ms / 1000:.1f}s | fill={selective_filter.min_fill_price:.2f}-{selective_filter.max_fill_price:.2f}"
        )
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
            log.status_line(
                f"  Recent: {sig.trader_name} {sig.side} {sig.direction.upper()} @ {sig.price:.2f} (${sig.usdc_amount:.2f})"
            )
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
                    bankrupt = True
                    break
                elif "Max daily loss" in reason:
                    log.status_line("")
                    log.status_line("╔════════════════════════════════════════╗")
                    log.status_line("║  SIMULATION ENDED - DAILY LOSS LIMIT   ║")
                    log.status_line("╚════════════════════════════════════════╝")
                    log.status_line(f"Daily P&L: ${state.daily_pnl:.2f} exceeded -${Config.MAX_DAILY_LOSS:.2f} limit")
                    break
                elif "Max daily bets" in reason:
                    # Calculate seconds until midnight in local timezone
                    now = datetime.now(LOCAL_TZ)
                    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    midnight = midnight + timedelta(days=1)
                    seconds_until_reset = (midnight - now).total_seconds()
                    hours, remainder = divmod(int(seconds_until_reset), 3600)
                    minutes = remainder // 60
                    log.status_line(
                        f"Daily bet limit reached ({Config.MAX_DAILY_BETS}). Sleeping {hours}h {minutes}m until midnight reset..."
                    )
                    time.sleep(seconds_until_reset)
                    state.daily_bets = 0  # Reset counter after sleep
                    state.daily_pnl = 0.0
                    log.status_line("Daily limit reset. Resuming trading...")
                    continue
                else:
                    time.sleep(30)
                    continue

            # === CHECK CIRCUIT BREAKER ===
            if api_circuit.state.value == "open":
                log.warning(
                    "circuit_open_wait",
                    recovery_time=Config.CIRCUIT_BREAKER_RECOVERY_TIME,
                )
                time.sleep(5)
                continue

            # === POLL FOR NEW SIGNALS (Fast polling) ===
            signals = monitor.poll()
            polls_since_stats += 1

            # === CHECK FOR WEBSOCKET-TRIGGERED SIGNALS ===
            # These are signals found by immediate polls triggered by WebSocket events
            while True:
                try:
                    ws_signal = signal_queue.get_nowait()
                    # Avoid duplicates - check if already in signals
                    is_duplicate = any(
                        s.wallet == ws_signal.wallet and s.market_ts == ws_signal.market_ts for s in signals
                    )
                    if not is_duplicate:
                        signals.append(ws_signal)
                        log.debug(
                            "ws_signal_added",
                            trader=ws_signal.trader_name,
                            market_ts=ws_signal.market_ts,
                        )
                except queue.Empty:
                    break

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
                    log.warning(
                        "skip_insufficient_funds",
                        requested=bet_amount,
                        available=state.bankroll,
                        minimum=Config.MIN_BET,
                    )
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

                # Pre-query orderbook and estimate execution (shared by filter + trader)
                token_id = market.up_token_id if direction == "up" else market.down_token_id
                precomputed_execution = None
                if token_id:
                    try:
                        if market_cache:
                            book = market_cache.get_orderbook(token_id)
                        else:
                            book = client.get_orderbook(token_id)

                        exec_est = estimate_execution_from_book(
                            book=book,
                            side="BUY",
                            amount_usd=amount,
                            copy_delay_ms=copy_delay_ms,
                        )
                        entry_price = market.up_price if direction == "up" else market.down_price
                        price_movement_pct = 0.0
                        if entry_price > 0:
                            price_movement_pct = ((exec_est["execution_price"] - entry_price) / entry_price) * 100

                        precomputed_execution = {
                            **exec_est,
                            "entry_price": entry_price,
                            "price_movement_pct": price_movement_pct,
                            "copy_delay_ms": copy_delay_ms,
                        }
                    except Exception as e:
                        log.debug(
                            "precompute_execution_failed",
                            error=str(e),
                            market=market.slug,
                        )

                if selective_enabled and selective_filter:
                    execution_info = precomputed_execution or {
                        "execution_price": market.up_price if direction == "up" else market.down_price,
                        "spread": 0.0,
                        "price_movement_pct": 0.0,
                        "copy_delay_ms": copy_delay_ms,
                        "depth_at_best": 0.0,
                        "delay_breakdown": None,
                    }
                    should_trade, reason = selective_filter.should_trade(sig, market, execution_info)
                    trade_label = f"{sig.trader_name} {direction.upper()} ${amount:.2f}"
                    if not should_trade:
                        log.status_line(f"[FILTER] ⏭️  SKIP: {reason} | {trade_label}")
                        copied_markets.add(key)
                        continue
                    log.status_line(f"[FILTER] ✅ PASS: all checks OK | {trade_label}")

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
                    precomputed_execution=precomputed_execution,
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
                                pending_info.append(
                                    {
                                        "direction": trade.direction,
                                        "current_prob": current_price,
                                        "likely_win": trade.direction == implied_winner,
                                    }
                                )
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

    if market_cache:
        market_cache.stop()

    # Mark pending trades as force_exit before saving
    if bankrupt:
        state.mark_pending_as_force_exit("insufficient_bankroll")
    else:
        state.mark_pending_as_force_exit("shutdown")

    state.save()

    total = session_wins + session_losses
    win_rate = (session_wins / total * 100) if total > 0 else 0
    log.status_line(f"Session: {session_wins}W/{session_losses}L ({win_rate:.0f}%) | PnL: ${session_pnl:+.2f}")
    log.status_line(f"Final bankroll: ${state.bankroll:.2f}")

    # Handle retry logic
    current_retry = args._retry_count
    max_retries = args.retry
    retries_remaining = max_retries - current_retry

    if bankrupt and retries_remaining > 0:
        # Retry: restart with fresh bankroll
        log.status_line("")
        log.status_line(f"═══ RETRY {current_retry + 1}/{max_retries} ═══")
        log.status_line(f"Retries remaining: {retries_remaining}")
        time.sleep(2)

        # Build new command with incremented retry count
        new_args = sys.argv.copy()

        # Update or add --_retry_count
        if "--_retry_count" in new_args:
            idx = new_args.index("--_retry_count")
            new_args[idx + 1] = str(current_retry + 1)
        else:
            new_args.extend(["--_retry_count", str(current_retry + 1)])

        # Force fresh bankroll if specified, otherwise use default
        initial_bankroll = args.bankroll or Config.BET_AMOUNT * 3
        if "--bankroll" in new_args:
            idx = new_args.index("--bankroll")
            new_args[idx + 1] = str(initial_bankroll)
        else:
            new_args.extend(["--bankroll", str(initial_bankroll)])

        # Restart the script
        os.execv(sys.executable, [sys.executable] + new_args)

    # Final exit
    if bankrupt:
        log.status_line("═══ SIMULATION TERMINATED ═══")
        if max_retries > 0:
            log.status_line(f"All {max_retries} retries exhausted")
        log.status_line("Exit code: 1 (insufficient funds)")
        sys.exit(1)
    else:
        log.status_line("═══ Shutdown ═══")


if __name__ == "__main__":
    main()
