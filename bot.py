#!/usr/bin/env python3
"""
Polymarket BTC 5-Min Streak Reversal Bot

Monitors BTC 5-min markets on Polymarket and bets against streaks.
"""

import argparse
import signal
import sys
import time
from datetime import datetime, timezone

from config import Config
from polymarket import PolymarketClient
from strategy import evaluate, kelly_size
from trader import LiveTrader, PaperTrader, TradingState

running = True


def handle_signal(sig, frame):
    global running
    print("\n[bot] Shutting down gracefully...")
    running = False


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def main():
    global running
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    parser = argparse.ArgumentParser(description="Polymarket BTC Streak Bot")
    parser.add_argument("--paper", action="store_true", help="Force paper trading")
    parser.add_argument("--trigger", type=int, help="Streak trigger length")
    parser.add_argument("--amount", type=float, help="Bet amount in USD")
    parser.add_argument("--bankroll", type=float, help="Starting bankroll")
    args = parser.parse_args()

    paper_mode = args.paper or Config.PAPER_TRADE
    trigger = args.trigger or Config.STREAK_TRIGGER
    bet_amount = args.amount or Config.BET_AMOUNT

    # Init
    client = PolymarketClient()
    state = TradingState.load()
    if args.bankroll:
        state.bankroll = args.bankroll

    if paper_mode:
        trader = PaperTrader()
        log("📝 Paper trading mode")
    else:
        trader = LiveTrader()
        log("🔥 LIVE trading mode")

    log(f"Strategy: streak trigger={trigger}, bet=${bet_amount:.2f}")
    log(f"Bankroll: ${state.bankroll:.2f}")
    log(f"Limits: max {Config.MAX_DAILY_BETS} bets/day, max ${Config.MAX_DAILY_LOSS} loss/day")
    log("")

    # Track what we've already bet on
    bet_timestamps: set[int] = {t.timestamp for t in state.trades}
    # Track pending trades (bet placed, waiting for resolution)
    pending: list = []

    while running:
        try:
            now = int(time.time())
            current_window = (now // 300) * 300
            seconds_into_window = now - current_window
            next_window = current_window + 300

            # === SETTLE PENDING TRADES ===
            for trade in list(pending):
                market = client.get_market(trade.timestamp)
                if market and market.closed and market.outcome:
                    state.settle_trade(trade, market.outcome)
                    emoji = "✅" if trade.pnl > 0 else "❌"
                    log(
                        f"{emoji} Settled: {trade.direction} @ {trade.market_slug} "
                        f"→ {market.outcome} | PnL: ${trade.pnl:+.2f} "
                        f"| Bankroll: ${state.bankroll:.2f}"
                    )
                    pending.remove(trade)
                    state.save()

            # === CHECK IF WE CAN TRADE ===
            can_trade, reason = state.can_trade()
            if not can_trade:
                if seconds_into_window == 0:
                    log(f"⏸️  {reason}")
                time.sleep(10)
                continue

            # === DETERMINE TARGET MARKET ===
            # We want to bet on the next window, entering before it starts
            target_ts = next_window
            seconds_until_target = target_ts - now

            # Already bet on this market?
            if target_ts in bet_timestamps:
                time.sleep(5)
                continue

            # === ENTRY TIMING ===
            # Wait until we're within ENTRY_SECONDS_BEFORE of the target window
            if seconds_until_target > Config.ENTRY_SECONDS_BEFORE:
                if seconds_into_window % 60 == 0:
                    log(
                        f"⏳ Next window in {seconds_until_target}s "
                        f"(entering at T-{Config.ENTRY_SECONDS_BEFORE}s) | "
                        f"Pending: {len(pending)} trades"
                    )
                time.sleep(1)
                continue

            # === GET RECENT OUTCOMES ===
            log("🔍 Fetching recent outcomes...")
            outcomes = client.get_recent_outcomes(count=trigger + 2)
            if len(outcomes) < trigger:
                log(f"⚠️  Only {len(outcomes)} recent outcomes, need {trigger}")
                bet_timestamps.add(target_ts)  # skip this window
                time.sleep(5)
                continue

            log(f"📊 Recent outcomes: {' → '.join(o.upper() for o in outcomes)}")

            # === EVALUATE STRATEGY ===
            sig = evaluate(outcomes, trigger=trigger)

            if not sig.should_bet:
                log(f"🟡 No signal: {sig.reason}")
                bet_timestamps.add(target_ts)
                time.sleep(5)
                continue

            # === GET TARGET MARKET ===
            market = client.get_market(target_ts)
            if not market:
                log(f"⚠️  Market not found for ts={target_ts}")
                time.sleep(5)
                continue

            if not market.accepting_orders:
                log(f"⚠️  Market not accepting orders: {market.slug}")
                bet_timestamps.add(target_ts)
                time.sleep(5)
                continue

            # === CALCULATE BET SIZE ===
            entry_price = (
                market.up_price if sig.direction == "up" else market.down_price
            )
            if entry_price <= 0:
                entry_price = 0.5

            odds = 1.0 / entry_price  # decimal odds
            amount = min(
                kelly_size(sig.confidence, odds, state.bankroll),
                bet_amount,
                state.bankroll * 0.1,  # never risk more than 10% of bankroll
            )
            amount = max(5, amount)  # Polymarket minimum

            # === PLACE BET ===
            log(f"🎯 Signal: {sig.reason}")
            trade = trader.place_bet(
                market=market,
                direction=sig.direction,
                amount=amount,
                confidence=sig.confidence,
                streak_length=sig.streak_length,
            )
            state.record_trade(trade)
            bet_timestamps.add(target_ts)
            pending.append(trade)
            state.save()

            # === STATUS ===
            log(
                f"📈 Daily: {state.daily_bets} bets, PnL: ${state.daily_pnl:+.2f} "
                f"| Bankroll: ${state.bankroll:.2f} | Pending: {len(pending)}"
            )

            time.sleep(5)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"❌ Error: {e}")
            time.sleep(10)

    # Save state on exit
    state.save()
    log(f"💾 State saved. Bankroll: ${state.bankroll:.2f}")
    log(f"📊 Session: {state.daily_bets} bets, PnL: ${state.daily_pnl:+.2f}")


if __name__ == "__main__":
    main()
