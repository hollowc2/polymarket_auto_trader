#!/usr/bin/env python3
"""Polymarket BTC Streak Reversal Bot — multi-timeframe.

Supports 5m, 15m, and 1h analysis windows via --timeframe.
The bot always bets on the next 5-minute Polymarket market, but when running
at 15m or 1h it only fires once per TF-aligned window and evaluates the
signal against aggregated (resampled) outcomes at that timeframe.

Confidence (Kelly sizing) is drawn from per-timeframe REVERSAL_RATES measured
from a 2-year Binance backtest. Default trigger per timeframe:
  5m  → trigger=4  (Sharpe 3.19, 18k train trades)
  15m → trigger=6  (Sharpe 6.01,  919 train trades)
  1h  → trigger=4  (Sharpe 2.76, 1.3k train trades)
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
        description="Polymarket BTC Streak Reversal Bot — multi-timeframe",
    )
    parser.add_argument("--paper", action="store_true", help="Force paper trading mode")
    parser.add_argument("--live", action="store_true", help="Force live trading (requires PRIVATE_KEY)")
    parser.add_argument(
        "--timeframe",
        choices=["5m", "15m", "1h"],
        default=Config.TIMEFRAME,
        help="Analysis timeframe (default: %(default)s). Affects trigger default, "
             "outcome aggregation, and reversal-rate confidence table.",
    )
    parser.add_argument(
        "--trigger",
        type=int,
        metavar="N",
        help="Streak trigger length. Defaults to the best-Sharpe value for the "
             "chosen timeframe (5m→4, 15m→6, 1h→4).",
    )
    parser.add_argument("--amount", type=float, metavar="USD", help=f"Max bet amount (default: {Config.BET_AMOUNT})")
    parser.add_argument("--bankroll", type=float, metavar="USD", help="Override starting bankroll")
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

    # Trigger: explicit flag > timeframe default > env var
    trigger = args.trigger or DEFAULT_TRIGGERS.get(timeframe, Config.STREAK_TRIGGER)
    bet_amount = args.amount or Config.BET_AMOUNT

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

    log(f"Strategy : {strategy.name}")
    log(f"Timeframe: {timeframe}  (fires every {window_seconds // 60} min, "
        f"trigger={trigger}, group={group_size} outcomes/bar)")
    log(f"Max bet  : ${bet_amount:.2f} | Bankroll: ${state.bankroll:.2f}")
    log(f"Limits   : max {Config.MAX_DAILY_BETS} bets/day, max ${Config.MAX_DAILY_LOSS} loss/day")
    log(f"Timezone : {TIMEZONE_NAME}")
    log("")

    bet_timestamps: set[int] = {t.timestamp for t in state.trades}
    pending: list = []

    while running:
        try:
            now = int(time.time())
            # Always align to 5m boundaries for market lookup
            current_5m = (now // 300) * 300
            seconds_into_5m = now - current_5m
            next_5m = current_5m + 300
            target_ts = next_5m          # the Polymarket market to bet on
            seconds_until_target = target_ts - now

            # === SETTLE PENDING TRADES ===
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

            # === TIMEFRAME GATE — only fire on TF-aligned windows ===
            # For 5m this is always true. For 15m, fires every 3rd window.
            # For 1h, fires every 12th window.
            if target_ts % window_seconds != 0:
                time.sleep(5)
                continue

            # === ENTRY TIMING ===
            if seconds_until_target > Config.ENTRY_SECONDS_BEFORE:
                if seconds_into_5m % 60 == 0:
                    log(
                        f"Next {timeframe} window in {seconds_until_target}s "
                        f"(entering at T-{Config.ENTRY_SECONDS_BEFORE}s) | "
                        f"Pending: {len(pending)} trades"
                    )
                time.sleep(1)
                continue

            # === GET RECENT OUTCOMES ===
            # Fetch enough raw 5m outcomes to fill `trigger + 2` bars at target TF
            raw_count = (trigger + 2) * group_size
            log(f"Fetching {raw_count} outcomes (→ {trigger + 2} {timeframe} bars)...")
            outcomes_raw = client.get_recent_outcomes(count=raw_count)

            # Resample into target-timeframe bars
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

            # === INTERPRET SIGNAL (timeframe-aware confidence) ===
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

            # === PLACE BET ===
            streak_len, _ = detect_streak(outcomes)
            log(f"Signal: {decision.reason}")
            trade = trader.place_bet(
                market=market,
                direction=decision.direction,
                amount=decision.size,
                confidence=decision.confidence,
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
    if pending:
        state.mark_pending_as_force_exit("shutdown")
    state.save()
    log(f"State saved. Bankroll: ${state.bankroll:.2f}")
    log(f"Session: {state.daily_bets} bets, PnL: ${state.daily_pnl:+.2f}")


if __name__ == "__main__":
    main()
