#!/usr/bin/env python3
"""Polymarket BTC 5-Min Streak Reversal Bot (packages/ architecture).

Uses StreakReversalStrategy from packages/strategies via the adapter layer.
All imports from polymarket_algo.* — zero imports from src/.
"""

import argparse
import signal
import time
from datetime import datetime

from polymarket_algo.core.adapters import (
    detect_streak,
    interpret_signal,
    outcomes_to_candles,
)
from polymarket_algo.core.config import LOCAL_TZ, TIMEZONE_NAME, Config
from polymarket_algo.executor.client import PolymarketClient
from polymarket_algo.executor.trader import PaperTrader, TradingState
from polymarket_algo.strategies.streak_reversal import StreakReversalStrategy

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
        description="Polymarket BTC 5-Min Streak Reversal Bot (packages/ architecture)",
    )
    parser.add_argument("--paper", action="store_true", help="Force paper trading mode")
    parser.add_argument("--live", action="store_true", help="Force live trading (requires PRIVATE_KEY)")
    parser.add_argument(
        "--trigger",
        type=int,
        metavar="N",
        help=f"Streak trigger length (default: {Config.STREAK_TRIGGER})",
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

    trigger = args.trigger or Config.STREAK_TRIGGER
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

    log(f"Strategy: {strategy.name} (trigger={trigger}, max_bet=${bet_amount:.2f})")
    log(f"Bankroll: ${state.bankroll:.2f}")
    log(f"Limits: max {Config.MAX_DAILY_BETS} bets/day, max ${Config.MAX_DAILY_LOSS} loss/day")
    log(f"Timezone: {TIMEZONE_NAME}")
    log("")

    # Track what we've already bet on
    bet_timestamps: set[int] = {t.timestamp for t in state.trades}
    # Pending trades awaiting resolution
    pending: list = []

    while running:
        try:
            now = int(time.time())
            current_window = (now // 300) * 300
            seconds_into_window = now - current_window
            next_window = current_window + 300
            target_ts = next_window
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
                if seconds_into_window == 0:
                    log(f"Paused: {reason}")
                time.sleep(10)
                continue

            # Already bet on this market?
            if target_ts in bet_timestamps:
                time.sleep(5)
                continue

            # === ENTRY TIMING ===
            if seconds_until_target > Config.ENTRY_SECONDS_BEFORE:
                if seconds_into_window % 60 == 0:
                    log(
                        f"Next window in {seconds_until_target}s "
                        f"(entering at T-{Config.ENTRY_SECONDS_BEFORE}s) | "
                        f"Pending: {len(pending)} trades"
                    )
                time.sleep(1)
                continue

            # === GET RECENT OUTCOMES ===
            log("Fetching recent outcomes...")
            outcomes = client.get_recent_outcomes(count=trigger + 2)
            if len(outcomes) < trigger:
                log(f"Only {len(outcomes)} recent outcomes, need {trigger}")
                bet_timestamps.add(target_ts)
                time.sleep(5)
                continue

            log(f"Recent outcomes: {' -> '.join(o.upper() for o in outcomes)}")

            # === EVALUATE VIA STRATEGY PROTOCOL ===
            candles = outcomes_to_candles(outcomes)
            result = strategy.evaluate(candles, trigger=trigger, size=bet_amount)

            # === INTERPRET SIGNAL ===
            # Get target market first for entry price
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

            decision = interpret_signal(
                result=result,
                outcomes=outcomes,
                bankroll=state.bankroll,
                entry_price=entry_price,
                max_bet=bet_amount,
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
