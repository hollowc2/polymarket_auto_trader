"""Trading execution — paper and live modes."""

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from config import Config
from polymarket import Market


@dataclass
class Trade:
    """Record of a trade (paper or live)."""

    timestamp: int
    market_slug: str
    direction: str  # "up" or "down"
    amount: float
    entry_price: float
    streak_length: int
    confidence: float
    paper: bool
    outcome: str | None = None  # filled after resolution
    pnl: float = 0.0
    order_id: str | None = None


@dataclass
class TradingState:
    """Persistent state across bot restarts."""

    trades: list[Trade] = field(default_factory=list)
    daily_bets: int = 0
    daily_pnl: float = 0.0
    last_reset_date: str = ""
    bankroll: float = 100.0  # starting bankroll

    def reset_daily_if_needed(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.last_reset_date != today:
            self.daily_bets = 0
            self.daily_pnl = 0.0
            self.last_reset_date = today

    def can_trade(self) -> tuple[bool, str]:
        self.reset_daily_if_needed()
        if self.daily_bets >= Config.MAX_DAILY_BETS:
            return False, f"Max daily bets reached ({Config.MAX_DAILY_BETS})"
        if self.daily_pnl <= -Config.MAX_DAILY_LOSS:
            return False, f"Max daily loss reached (${Config.MAX_DAILY_LOSS})"
        if self.bankroll < Config.BET_AMOUNT:
            return False, f"Bankroll too low (${self.bankroll:.2f})"
        return True, "OK"

    def record_trade(self, trade: Trade):
        self.trades.append(trade)
        self.daily_bets += 1

    def settle_trade(self, trade: Trade, outcome: str):
        trade.outcome = outcome
        won = trade.direction == outcome
        if won:
            # Win: receive amount / entry_price, minus the amount paid
            payout = trade.amount / trade.entry_price
            trade.pnl = payout - trade.amount
        else:
            trade.pnl = -trade.amount

        self.daily_pnl += trade.pnl
        self.bankroll += trade.pnl

    def save(self):
        data = {
            "trades": [asdict(t) for t in self.trades[-200:]],  # keep last 200
            "daily_bets": self.daily_bets,
            "daily_pnl": self.daily_pnl,
            "last_reset_date": self.last_reset_date,
            "bankroll": self.bankroll,
        }
        with open(Config.TRADES_FILE, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls) -> "TradingState":
        if not os.path.exists(Config.TRADES_FILE):
            return cls()
        try:
            with open(Config.TRADES_FILE) as f:
                data = json.load(f)
            state = cls()
            state.trades = [Trade(**t) for t in data.get("trades", [])]
            state.daily_bets = data.get("daily_bets", 0)
            state.daily_pnl = data.get("daily_pnl", 0.0)
            state.last_reset_date = data.get("last_reset_date", "")
            state.bankroll = data.get("bankroll", 100.0)
            return state
        except Exception as e:
            print(f"[trader] Error loading state: {e}")
            return cls()


class PaperTrader:
    """Paper trading — logs trades without executing."""

    def place_bet(self, market: Market, direction: str, amount: float, confidence: float, streak_length: int) -> Trade:
        entry_price = market.up_price if direction == "up" else market.down_price
        trade = Trade(
            timestamp=market.timestamp,
            market_slug=market.slug,
            direction=direction,
            amount=amount,
            entry_price=entry_price if entry_price > 0 else 0.5,
            streak_length=streak_length,
            confidence=confidence,
            paper=True,
        )
        print(
            f"[PAPER] 📝 Bet ${amount:.2f} on {direction.upper()} @ {trade.entry_price:.2f} "
            f"| {market.title} | streak={streak_length} conf={confidence:.1%}"
        )
        return trade


class LiveTrader:
    """Live trading via Polymarket CLOB API."""

    def __init__(self):
        if not Config.PRIVATE_KEY:
            raise ValueError("PRIVATE_KEY not set in .env")
        self._init_client()

    def _init_client(self):
        """Initialize py-clob-client with wallet credentials."""
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import OrderArgs, OrderType

            self.client = ClobClient(
                Config.CLOB_API,
                key=Config.PRIVATE_KEY,
                chain_id=Config.CHAIN_ID,
            )
            # Derive API credentials
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            self.OrderArgs = OrderArgs
            self.OrderType = OrderType
            print("[trader] ✅ Live trading client initialized")
        except ImportError:
            raise ImportError("py-clob-client not installed. Run: pip install py-clob-client")
        except Exception as e:
            raise RuntimeError(f"Failed to init trading client: {e}")

    def place_bet(self, market: Market, direction: str, amount: float, confidence: float, streak_length: int) -> Trade:
        token_id = market.up_token_id if direction == "up" else market.down_token_id
        if not token_id:
            raise ValueError(f"No token ID for {direction} side")

        entry_price = market.up_price if direction == "up" else market.down_price
        if entry_price <= 0:
            entry_price = 0.5

        # Calculate size (number of shares)
        size = round(amount / entry_price, 2)

        try:
            order = self.client.create_and_post_order(
                self.OrderArgs(
                    token_id=token_id,
                    price=entry_price,
                    size=size,
                    side="BUY",
                )
            )
            order_id = order.get("orderID", order.get("id", "unknown"))
            print(
                f"[LIVE] 🔥 Bet ${amount:.2f} on {direction.upper()} @ {entry_price:.2f} "
                f"| {market.title} | order={order_id}"
            )
        except Exception as e:
            print(f"[LIVE] ❌ Order failed: {e}")
            order_id = f"FAILED:{e}"

        return Trade(
            timestamp=market.timestamp,
            market_slug=market.slug,
            direction=direction,
            amount=amount,
            entry_price=entry_price,
            streak_length=streak_length,
            confidence=confidence,
            paper=False,
            order_id=order_id,
        )
