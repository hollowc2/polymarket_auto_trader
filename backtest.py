#!/usr/bin/env python3
"""Backtest streak reversal strategy against historical data."""

import argparse
import json
import sys


def backtest(data_file: str, trigger: int, bet_amount: float, bankroll: float, fee_pct: float = 0.05):
    with open(data_file) as f:
        markets = json.load(f)

    closed = [m for m in markets if m.get("closed") and m["outcome"] in ("up", "down")]
    outcomes = [m["outcome"] for m in closed]

    print(f"=== BACKTEST: trigger={trigger}, bet=${bet_amount}, fee={fee_pct:.0%} ===")
    print(f"Markets: {len(closed)}, Up: {sum(1 for o in outcomes if o == 'up')}, Down: {sum(1 for o in outcomes if o == 'down')}")
    print()

    trades = []
    wins = 0
    losses = 0
    total_pnl = 0.0
    max_drawdown = 0.0
    peak_bankroll = bankroll

    for i in range(trigger, len(outcomes)):
        window = outcomes[i - trigger : i]
        if len(set(window)) != 1:
            continue

        # Streak detected — bet on reversal
        streak_dir = window[0]
        bet_dir = "down" if streak_dir == "up" else "up"
        actual = outcomes[i]
        won = bet_dir == actual

        if won:
            pnl = bet_amount * (1 - fee_pct)  # win minus fee
            wins += 1
        else:
            pnl = -bet_amount
            losses += 1

        bankroll += pnl
        total_pnl += pnl
        peak_bankroll = max(peak_bankroll, bankroll)
        drawdown = peak_bankroll - bankroll
        max_drawdown = max(max_drawdown, drawdown)

        trades.append(
            {
                "idx": i,
                "streak": f"{trigger}x{streak_dir}",
                "bet": bet_dir,
                "actual": actual,
                "won": won,
                "pnl": pnl,
                "bankroll": bankroll,
            }
        )

    total_bets = wins + losses
    if total_bets == 0:
        print("No trades triggered.")
        return

    win_rate = wins / total_bets
    avg_pnl = total_pnl / total_bets

    print(f"Total bets:    {total_bets}")
    print(f"Wins:          {wins} ({win_rate:.1%})")
    print(f"Losses:        {losses} ({1 - win_rate:.1%})")
    print(f"Total PnL:     ${total_pnl:+.2f}")
    print(f"Avg PnL/trade: ${avg_pnl:+.2f}")
    print(f"Final bankroll: ${bankroll:.2f}")
    print(f"Max drawdown:  ${max_drawdown:.2f}")
    print(f"ROI:           {(total_pnl / (bet_amount * total_bets)) * 100:+.1f}%")
    print()

    # Streak breakdown
    print("=== STREAK LENGTH BREAKDOWN ===")
    for sl in range(trigger, min(trigger + 4, 8)):
        sw = sl_wins = sl_total = 0
        for i in range(sl, len(outcomes)):
            window = outcomes[i - sl : i]
            # Must be exactly this streak length (not longer)
            if len(set(window)) == 1:
                if i - sl - 1 >= 0 and outcomes[i - sl - 1] == window[0]:
                    continue  # streak is actually longer
                sl_total += 1
                bet_dir = "down" if window[0] == "up" else "up"
                if outcomes[i] == bet_dir:
                    sl_wins += 1
        if sl_total:
            print(f"  Exactly {sl}-streak: {sl_wins}/{sl_total} ({sl_wins / sl_total:.1%} reversal)")

    # Print last 10 trades
    print()
    print("=== LAST 10 TRADES ===")
    for t in trades[-10:]:
        emoji = "✅" if t["won"] else "❌"
        print(
            f"  {emoji} {t['streak']} → bet {t['bet']} → actual {t['actual']} "
            f"| PnL: ${t['pnl']:+.2f} | Bankroll: ${t['bankroll']:.2f}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="../polymarket-research/data/polymarket_all_resolved.json")
    parser.add_argument("--trigger", type=int, default=4)
    parser.add_argument("--amount", type=float, default=10)
    parser.add_argument("--bankroll", type=float, default=1000)
    parser.add_argument("--fee", type=float, default=0.05, help="Fee as decimal (0.05 = 5%)")
    args = parser.parse_args()

    backtest(args.data, args.trigger, args.amount, args.bankroll, args.fee)

    # Also run with different triggers for comparison
    print("\n" + "=" * 60)
    print("=== COMPARISON ACROSS TRIGGERS ===")
    print("=" * 60)
    for t in [3, 4, 5]:
        print()
        backtest(args.data, t, args.amount, args.bankroll, args.fee)
