#!/usr/bin/env python3
"""Polymarket BTC Streak Reversal Bot — alternative entry execution.

Three toggleable features layered on top of the standard streak strategy:

  1. Streak length filter  (ALT_ENTRY_USE_STREAK_FILTER / --no-streak-filter)
       Only trade streaks >= ALT_ENTRY_MIN_STREAK (default 4).

  2. Price floor filter    (ALT_ENTRY_USE_PRICE_FLOOR / --no-price-floor)
       Skip if the reversal ask > ALT_ENTRY_MAX_ENTRY_PRICE (default 0.44).
       Rationale: after N consecutive up candles the DOWN price is often
       0.40–0.45; a price above 0.44 means the crowd isn't pricing in much
       continuation momentum, reducing edge.

  3. Limit orders          (ALT_ENTRY_USE_LIMIT_ORDERS / --no-limit-orders)
       Place GTC bids at (ask - discount) instead of FOK market orders.
       Discount is streak-length dependent (ALT_ENTRY_DISCOUNTS).
       If the limit doesn't fill within ALT_ENTRY_FILL_WINDOW_SEC seconds
       it is cancelled and logged to missed_orders.json.

Features apply in order; each can independently abort the trade:
    streak_filter → price_floor → limit_order

Usage:
    uv run python scripts/streak_bot_alternative_entry.py --paper
    uv run python scripts/streak_bot_alternative_entry.py --paper --no-limit-orders
    uv run python scripts/streak_bot_alternative_entry.py --paper --no-streak-filter --no-price-floor
"""

import argparse
import signal
import time
from datetime import datetime

from polymarket_algo.core.adapters import (
    TF_GROUP_SIZE,
    detect_streak,
    interpret_signal,
    outcomes_to_candles,
    resample_outcomes,
)
from polymarket_algo.core.config import LOCAL_TZ, TIMEZONE_NAME, Config
from polymarket_algo.core.sizing import DEFAULT_TRIGGERS
from polymarket_algo.executor.client import PolymarketClient
from polymarket_algo.executor.trader import PaperTrader, TradingState
from polymarket_algo.strategies.streak_reversal import StreakReversalStrategy

# Path for logging missed limit orders
MISSED_ORDERS_PATH = "missed_orders.json"

# Seconds per timeframe window — used to align bet windows
TF_SECONDS: dict[str, int] = {"5m": 300, "15m": 900, "1h": 3600}

running = True


def handle_signal(sig, _frame):
    global running
    print("\n[bot] Shutting down gracefully...")
    running = False


def log(msg: str):
    ts = datetime.now(LOCAL_TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def main():
    global running
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    parser = argparse.ArgumentParser(
        description="Polymarket BTC Streak Reversal Bot — alternative entry execution",
    )
    parser.add_argument("--paper", action="store_true", help="Force paper trading mode")
    parser.add_argument("--live", action="store_true", help="Force live trading (requires PRIVATE_KEY)")
    parser.add_argument(
        "--timeframe",
        choices=["5m", "15m", "1h"],
        default=Config.TIMEFRAME,
        help="Analysis timeframe (default: %(default)s).",
    )
    parser.add_argument(
        "--trigger",
        type=int,
        metavar="N",
        help="Streak trigger length. Defaults to best-Sharpe per timeframe (5m→4, 15m→6, 1h→4).",
    )
    parser.add_argument("--amount", type=float, metavar="USD", help=f"Max bet amount (default: {Config.BET_AMOUNT})")
    parser.add_argument("--bankroll", type=float, metavar="USD", help="Override starting bankroll")

    # Feature toggles — mirror the env vars but let CLI override
    parser.add_argument(
        "--no-streak-filter",
        dest="streak_filter",
        action="store_false",
        default=Config.ALT_ENTRY_USE_STREAK_FILTER,
        help="Disable streak length filter",
    )
    parser.add_argument(
        "--no-price-floor",
        dest="price_floor",
        action="store_false",
        default=Config.ALT_ENTRY_USE_PRICE_FLOOR,
        help="Disable price floor filter",
    )
    parser.add_argument(
        "--no-limit-orders",
        dest="limit_orders",
        action="store_false",
        default=Config.ALT_ENTRY_USE_LIMIT_ORDERS,
        help="Disable limit orders (falls back to FOK market orders)",
    )
    parser.add_argument(
        "--min-streak",
        type=int,
        default=Config.ALT_ENTRY_MIN_STREAK,
        metavar="N",
        help=f"Minimum streak length to trade (default: {Config.ALT_ENTRY_MIN_STREAK})",
    )
    parser.add_argument(
        "--max-ask",
        type=float,
        default=Config.ALT_ENTRY_MAX_ENTRY_PRICE,
        metavar="PRICE",
        help=f"Max reversal ask price to trade (default: {Config.ALT_ENTRY_MAX_ENTRY_PRICE})",
    )
    parser.add_argument(
        "--fill-window",
        type=int,
        default=Config.ALT_ENTRY_FILL_WINDOW_SEC,
        metavar="SEC",
        help=f"Seconds to wait for limit fill before cancelling (default: {Config.ALT_ENTRY_FILL_WINDOW_SEC})",
    )
    args = parser.parse_args()

    # Determine trading mode — default to paper
    if args.live:
        paper_mode = False
    elif args.paper:
        paper_mode = True
    else:
        paper_mode = Config.PAPER_TRADE

    timeframe = args.timeframe
    window_seconds = TF_SECONDS[timeframe]
    group_size = TF_GROUP_SIZE[timeframe]

    trigger = args.trigger or DEFAULT_TRIGGERS.get(timeframe, Config.STREAK_TRIGGER)
    bet_amount = args.amount or Config.BET_AMOUNT

    use_streak_filter = args.streak_filter
    use_price_floor = args.price_floor
    use_limit_orders = args.limit_orders
    min_streak = args.min_streak
    max_ask = args.max_ask
    fill_window = args.fill_window
    discounts = Config.ALT_ENTRY_DISCOUNTS

    # Init components
    client = PolymarketClient()
    strategy = StreakReversalStrategy()
    state = TradingState.load()
    if args.bankroll:
        state.bankroll = args.bankroll

    if paper_mode:
        trader = PaperTrader()
        log("Paper trading mode")
    else:
        from polymarket_algo.executor.trader import LiveTrader

        trader = LiveTrader()
        log("LIVE trading mode - Real money!")

    log(f"Strategy : {strategy.name} (alternative entry)")
    log(f"Timeframe: {timeframe}  (fires every {window_seconds // 60} min, "
        f"trigger={trigger}, group={group_size} outcomes/bar)")
    log(f"Max bet  : ${bet_amount:.2f} | Bankroll: ${state.bankroll:.2f}")
    log(f"Limits   : max {Config.MAX_DAILY_BETS} bets/day, max ${Config.MAX_DAILY_LOSS} loss/day")
    log(f"Timezone : {TIMEZONE_NAME}")
    log("")
    log("── Alternative entry features ──────────────────────────────")
    log(f"  Streak filter : {'ON' if use_streak_filter else 'OFF'}  (min_streak={min_streak})")
    log(f"  Price floor   : {'ON' if use_price_floor else 'OFF'}  (max_ask={max_ask:.3f})")
    log(f"  Limit orders  : {'ON' if use_limit_orders else 'OFF'}  (fill_window={fill_window}s, discounts={discounts})")
    log("────────────────────────────────────────────────────────────")
    log("")

    bet_timestamps: set[int] = {t.timestamp for t in state.trades}
    # Settled market orders waiting for resolution
    pending: list = []
    # Limit orders waiting for fill or expiry: list of (trade, market, placed_at_unix)
    pending_limits: list = []

    while running:
        try:
            now = int(time.time())
            current_5m = (now // 300) * 300
            seconds_into_5m = now - current_5m
            next_5m = current_5m + 300
            target_ts = next_5m
            seconds_until_target = target_ts - now

            # === SETTLE PENDING MARKET-ORDER TRADES ===
            for trade in list(pending):
                market = client.get_market(trade.timestamp)
                if market and market.closed and market.outcome:
                    state.settle_trade(trade, market.outcome, market)
                    emoji = "+" if trade.pnl > 0 else "-"
                    fee_info = f" (fee: {trade.fee_pct:.2%})" if trade.won and trade.fee_pct > 0 else ""
                    log(
                        f"[{emoji}] Settled: {trade.direction.upper()} @ {trade.execution_price:.3f} "
                        f"-> {market.outcome.upper()} | PnL: ${trade.pnl:+.2f}{fee_info} "
                        f"| Bankroll: ${state.bankroll:.2f}"
                    )
                    pending.remove(trade)
                    state.save()

            # === POLL PENDING LIMIT ORDERS ===
            still_pending_limits = []
            for limit_trade, limit_market, placed_at in pending_limits:
                seconds_elapsed = now - placed_at
                if trader.check_limit_fill(limit_trade):
                    log(
                        f"[L] Limit filled: {limit_trade.direction.upper()} "
                        f"@ {limit_trade.execution_price:.4f} "
                        f"(target {limit_trade.limit_price:.4f}) | elapsed {seconds_elapsed}s"
                    )
                    state.record_trade(limit_trade)
                    pending.append(limit_trade)
                    state.save()
                elif seconds_elapsed >= fill_window:
                    log(
                        f"[L] Limit expired after {seconds_elapsed}s "
                        f"({limit_trade.direction.upper()} @ {limit_trade.limit_price:.4f}) — missed"
                    )
                    trader.cancel_limit_bet(limit_trade, MISSED_ORDERS_PATH)
                else:
                    remaining = fill_window - seconds_elapsed
                    still_pending_limits.append((limit_trade, limit_market, placed_at))
                    # Log progress every ~30s
                    if seconds_elapsed % 30 < 2:
                        log(
                            f"[L] Waiting for limit fill: {limit_trade.direction.upper()} "
                            f"@ {limit_trade.limit_price:.4f} | {remaining}s remaining"
                        )
            pending_limits = still_pending_limits

            # === CHECK IF WE CAN TRADE ===
            can_trade, reason = state.can_trade()
            if not can_trade:
                if seconds_into_5m == 0:
                    log(f"Paused: {reason}")
                time.sleep(10)
                continue

            # Already bet on this market?
            if target_ts in bet_timestamps:
                time.sleep(5)
                continue

            # === TIMEFRAME GATE ===
            if target_ts % window_seconds != 0:
                time.sleep(5)
                continue

            # === ENTRY TIMING ===
            if seconds_until_target > Config.ENTRY_SECONDS_BEFORE:
                if seconds_into_5m % 60 == 0:
                    log(
                        f"Next {timeframe} window in {seconds_until_target}s "
                        f"(entering at T-{Config.ENTRY_SECONDS_BEFORE}s) | "
                        f"Pending: {len(pending)} market, {len(pending_limits)} limit"
                    )
                time.sleep(1)
                continue

            # === GET RECENT OUTCOMES ===
            raw_count = (trigger + 2) * group_size
            log(f"Fetching {raw_count} outcomes (→ {trigger + 2} {timeframe} bars)...")
            outcomes_raw = client.get_recent_outcomes(count=raw_count)
            outcomes = resample_outcomes(outcomes_raw, group_size)

            if len(outcomes) < trigger:
                log(f"Only {len(outcomes)} {timeframe} bars after resample, need {trigger}")
                bet_timestamps.add(target_ts)
                time.sleep(5)
                continue

            log(f"{timeframe} bars: {' -> '.join(o.upper() for o in outcomes[-trigger - 2:])}")

            # === EVALUATE VIA STRATEGY PROTOCOL ===
            candles = outcomes_to_candles(outcomes)
            result = strategy.evaluate(candles, trigger=trigger, size=bet_amount)

            # === GET TARGET MARKET ===
            market = client.get_market(target_ts)
            if not market:
                log(f"Market not found for ts={target_ts}")
                time.sleep(5)
                continue

            if not market.accepting_orders:
                log(f"Market not accepting orders: {market.slug}")
                bet_timestamps.add(target_ts)
                time.sleep(5)
                continue

            last_signal = int(result.iloc[-1]["signal"])
            entry_price = market.up_price if last_signal == 1 else market.down_price
            if entry_price <= 0:
                entry_price = 0.5

            # === INTERPRET SIGNAL ===
            decision = interpret_signal(
                result=result,
                outcomes=outcomes,
                bankroll=state.bankroll,
                entry_price=entry_price,
                max_bet=bet_amount,
                timeframe=timeframe,
            )

            if not decision.should_bet:
                log(f"No signal: {decision.reason}")
                bet_timestamps.add(target_ts)
                time.sleep(5)
                continue

            streak_len, _ = detect_streak(outcomes)
            direction = decision.direction
            size = decision.size
            confidence = decision.confidence

            # Current ask for the reversal direction
            current_ask = market.down_price if direction == "down" else market.up_price

            log(f"Signal: {decision.reason} | streak={streak_len} | ask={current_ask:.4f}")

            # ── Feature 1: Streak length filter ──────────────────────────────
            if use_streak_filter and streak_len < min_streak:
                log(f"[filter] Streak {streak_len} < min {min_streak} — skipping")
                bet_timestamps.add(target_ts)
                time.sleep(5)
                continue

            # ── Feature 2: Price floor filter ────────────────────────────────
            if use_price_floor and current_ask > max_ask:
                log(f"[filter] Ask {current_ask:.4f} > floor {max_ask:.4f} — skipping")
                bet_timestamps.add(target_ts)
                time.sleep(5)
                continue

            # ── Feature 3: Limit orders vs market orders ──────────────────────
            if use_limit_orders:
                # Streak-length-dependent discount; fall back to smallest if not in table
                fallback_discount = discounts.get(min(discounts.keys()), 0.03)
                discount = discounts.get(streak_len, fallback_discount)
                limit_price = max(0.01, round(current_ask - discount, 4))

                log(
                    f"[limit] Placing GTC bid @ {limit_price:.4f} "
                    f"(ask={current_ask:.4f}, discount={discount:.3f})"
                )

                trade = trader.place_limit_bet(
                    market=market,
                    direction=direction,
                    amount=size,
                    limit_price=limit_price,
                    confidence=confidence,
                    streak_length=streak_len,
                )

                if trade is None:
                    log("Limit order rejected")
                    bet_timestamps.add(target_ts)
                    continue

                # Track in pending_limits — NOT yet recorded in state
                pending_limits.append((trade, market, int(time.time())))
                bet_timestamps.add(target_ts)

                log(
                    f"Daily: {state.daily_bets} bets, PnL: ${state.daily_pnl:+.2f} "
                    f"| Bankroll: ${state.bankroll:.2f} | Limits pending: {len(pending_limits)}"
                )

            else:
                # Fall back to standard FOK market order
                trade = trader.place_bet(
                    market=market,
                    direction=direction,
                    amount=size,
                    confidence=confidence,
                    streak_length=streak_len,
                )

                if trade is None:
                    log("Order rejected")
                    bet_timestamps.add(target_ts)
                    continue

                state.record_trade(trade)
                bet_timestamps.add(target_ts)
                pending.append(trade)
                state.save()

                log(
                    f"Daily: {state.daily_bets} bets, PnL: ${state.daily_pnl:+.2f} "
                    f"| Bankroll: ${state.bankroll:.2f} | Pending: {len(pending)}"
                )

            time.sleep(5)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(10)

    # Graceful shutdown
    # Cancel any open limit orders
    for limit_trade, _limit_market, _placed_at in pending_limits:
        log(f"Cancelling open limit: {limit_trade.direction.upper()} @ {limit_trade.limit_price:.4f}")
        trader.cancel_limit_bet(limit_trade, MISSED_ORDERS_PATH)

    if pending:
        state.mark_pending_as_force_exit("shutdown")
    state.save()
    log(f"State saved. Bankroll: ${state.bankroll:.2f}")
    log(f"Session: {state.daily_bets} bets, PnL: ${state.daily_pnl:+.2f}")
    log(f"Missed limits logged to: {MISSED_ORDERS_PATH}")


if __name__ == "__main__":
    main()
