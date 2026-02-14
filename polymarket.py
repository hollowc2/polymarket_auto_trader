"""Polymarket API client for reading market data and placing trades."""

import json
import time
from dataclasses import dataclass

import requests

from config import Config


@dataclass
class Market:
    """A single BTC 5-min up/down market."""

    timestamp: int
    slug: str
    title: str
    closed: bool
    outcome: str | None  # "up", "down", or None if not resolved
    up_token_id: str | None
    down_token_id: str | None
    up_price: float
    down_price: float
    volume: float
    accepting_orders: bool
    taker_fee_bps: int = 1000  # Default 10% base fee
    resolved: bool = False  # True when umaResolutionStatus == "resolved"


class PolymarketClient:
    """Read-only client for Polymarket APIs (no auth needed)."""

    def __init__(self):
        self.gamma = Config.GAMMA_API
        self.clob = Config.CLOB_API
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "PolymarketBot/1.0", "Accept": "application/json"}
        )

    def get_market(self, timestamp: int) -> Market | None:
        """Fetch a BTC 5-min market by its timestamp."""
        slug = f"btc-updown-5m-{timestamp}"
        try:
            resp = self.session.get(
                f"{self.gamma}/events", params={"slug": slug}, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None

            event = data[0]
            markets = event.get("markets", [])
            if not markets:
                return None

            m = markets[0]
            # Parse token IDs
            token_ids = json.loads(m.get("clobTokenIds", "[]"))
            up_token = token_ids[0] if len(token_ids) > 0 else None
            down_token = token_ids[1] if len(token_ids) > 1 else None

            # Parse prices
            prices = json.loads(m.get("outcomePrices", "[0.5, 0.5]"))
            up_price = float(prices[0]) if prices else 0.5
            down_price = float(prices[1]) if len(prices) > 1 else 0.5

            # Determine outcome if resolved
            # A market is truly resolved when:
            # 1. closed=true AND
            # 2. umaResolutionStatus="resolved" (or outcomePrices shows 1.0/0.0)
            outcome = None
            is_closed = m.get("closed", False)
            uma_status = m.get("umaResolutionStatus", "")
            is_resolved = uma_status == "resolved"

            if is_closed and (is_resolved or up_price > 0.99 or down_price > 0.99):
                # Use threshold comparison to handle float precision
                if up_price > 0.99:
                    outcome = "up"
                elif down_price > 0.99:
                    outcome = "down"

            # Extract fee rate from market data (already in Gamma response)
            taker_fee_bps = m.get("takerBaseFee")
            if taker_fee_bps is None:
                taker_fee_bps = 1000
                print(f"[polymarket] No takerBaseFee in response for {slug}, using default {taker_fee_bps} bps")
            else:
                taker_fee_bps = int(taker_fee_bps)

            return Market(
                timestamp=timestamp,
                slug=slug,
                title=event.get("title", ""),
                closed=event.get("closed", False) or m.get("closed", False),
                outcome=outcome,
                up_token_id=up_token,
                down_token_id=down_token,
                up_price=up_price,
                down_price=down_price,
                volume=event.get("volume", 0),
                accepting_orders=m.get("acceptingOrders", False),
                taker_fee_bps=taker_fee_bps,
                resolved=is_resolved,
            )
        except Exception as e:
            print(f"[polymarket] Error fetching {slug}: {e}")
            return None

    def get_recent_outcomes(self, count: int = 10) -> list[str]:
        """Get the last N resolved market outcomes (oldest first)."""
        now = int(time.time())
        current_window = (now // 300) * 300
        outcomes: list[str] = []

        # Walk backwards from the most recent completed window
        ts = current_window - 300  # previous window (should be resolved or resolving)
        attempts = 0
        max_attempts = count + 10  # some buffer for missing markets

        while len(outcomes) < count and attempts < max_attempts:
            market = self.get_market(ts)
            if market and market.closed and market.outcome:
                outcomes.append(market.outcome)
            ts -= 300
            attempts += 1
            time.sleep(0.05)

        # Reverse so oldest is first
        outcomes.reverse()
        return outcomes

    def get_next_market_timestamp(self) -> int:
        """Get the timestamp of the next upcoming 5-min window."""
        now = int(time.time())
        current_window = (now // 300) * 300
        # If we're in the first half of the window, current might still be tradeable
        # But for streak strategy, we want the NEXT unresolved one
        next_window = current_window + 300
        if now - current_window < 60:
            # Window just started, current is still open
            return current_window
        return next_window

    def get_orderbook(self, token_id: str) -> dict:
        """Get order book for a token."""
        try:
            resp = self.session.get(
                f"{self.clob}/book", params={"token_id": token_id}, timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[polymarket] Error fetching orderbook: {e}")
            return {}

    def get_midpoint(self, token_id: str) -> float | None:
        """Get midpoint price for a token."""
        try:
            resp = self.session.get(
                f"{self.clob}/midpoint", params={"token_id": token_id}, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("mid", 0.5))
        except Exception as e:
            print(f"[polymarket] Error fetching midpoint: {e}")
            return None

    def get_fee_rate(self, token_id: str) -> int:
        """Get fee rate in basis points for a token.

        Returns base_fee (e.g., 1000 = 10% base rate).
        Actual fee = price * (1 - price) * base_fee / 10000
        """
        DEFAULT_FEE_BPS = 1000  # Fallback: 10% base rate (typical Polymarket fee)
        try:
            resp = self.session.get(
                f"{self.clob}/fee-rate", params={"token_id": token_id}, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            return int(data.get("base_fee", DEFAULT_FEE_BPS))
        except Exception as e:
            print(f"[polymarket] Error fetching fee rate: {e}, using default {DEFAULT_FEE_BPS} bps")
            return DEFAULT_FEE_BPS

    @staticmethod
    def calculate_fee(price: float, base_fee_bps: int) -> float:
        """Calculate actual fee percentage from price and base fee.

        Fee formula: fee = price * (1 - price) * base_fee / 10000
        At 50¢ with base_fee=1000: 0.50 * 0.50 * 0.10 = 2.5%
        """
        if base_fee_bps == 0:
            return 0.0
        return price * (1 - price) * base_fee_bps / 10000

    def get_execution_price(
        self, token_id: str, side: str, amount_usd: float, copy_delay_ms: int = 0
    ) -> tuple[float, float, float, float, float]:
        """Calculate execution price with slippage for a given order size.

        Args:
            token_id: The token to trade
            side: "BUY" or "SELL"
            amount_usd: Order size in USD
            copy_delay_ms: Milliseconds since the original trade (for copytrade)

        Returns:
            tuple of (execution_price, spread, slippage_pct, fill_pct, delay_impact_pct)
            - execution_price: The price you'll actually get
            - spread: Bid-ask spread
            - slippage_pct: Slippage from walking the book
            - fill_pct: Percentage of order that can be filled (100 = full fill)
            - delay_impact_pct: Additional price impact from copy delay
        """
        book = self.get_orderbook(token_id)
        if not book:
            return (0.5, 0.0, 0.0, 100.0, 0.0)

        # Get best bid/ask for spread calculation
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if not bids or not asks:
            return (0.5, 0.0, 0.0, 100.0, 0.0)

        # Sort: asks ascending (lowest first), bids descending (highest first)
        asks_sorted = sorted(asks, key=lambda x: float(x["price"]))
        bids_sorted = sorted(bids, key=lambda x: float(x["price"]), reverse=True)

        best_ask = float(asks_sorted[0]["price"])
        best_bid = float(bids_sorted[0]["price"])
        spread = best_ask - best_bid

        # Calculate execution price by walking the book
        if side == "BUY":
            # Walk through asks (we're buying, so we take from asks)
            levels = asks_sorted
        else:
            # Walk through bids (we're selling, so we take from bids)
            levels = bids_sorted

        remaining_usd = amount_usd
        total_shares = 0.0
        total_cost = 0.0
        total_available = sum(float(l["price"]) * float(l["size"]) for l in levels)

        for level in levels:
            price = float(level["price"])
            size = float(level["size"])
            level_value = price * size  # USD value at this level

            if remaining_usd <= 0:
                break

            if level_value >= remaining_usd:
                # This level can fill the rest
                shares_to_take = remaining_usd / price
                total_shares += shares_to_take
                total_cost += remaining_usd
                remaining_usd = 0
            else:
                # Take entire level
                total_shares += size
                total_cost += level_value
                remaining_usd -= level_value

        # Calculate fill percentage
        filled_amount = amount_usd - remaining_usd
        fill_pct = (filled_amount / amount_usd * 100) if amount_usd > 0 else 100.0

        if total_shares == 0:
            midpoint = (best_ask + best_bid) / 2
            return (midpoint, spread, 0.0, 0.0, 0.0)

        execution_price = total_cost / total_shares

        # Calculate slippage vs best price
        if side == "BUY":
            slippage_pct = (execution_price - best_ask) / best_ask * 100 if best_ask > 0 else 0
        else:
            slippage_pct = (best_bid - execution_price) / best_bid * 100 if best_bid > 0 else 0

        # Calculate copy delay price impact
        # The longer the delay, the more the price moves against us
        # Empirical model: ~0.5% price impact per second of delay for popular trades
        delay_impact_pct = 0.0
        if copy_delay_ms > 0:
            delay_seconds = copy_delay_ms / 1000.0
            # Price impact increases with delay (diminishing returns after ~10s)
            # Model: 0.3% per second, capped at 5%
            delay_impact_pct = min(5.0, delay_seconds * 0.3)

            # Apply delay impact to execution price
            if side == "BUY":
                execution_price *= (1 + delay_impact_pct / 100)
            else:
                execution_price *= (1 - delay_impact_pct / 100)

            # Cap execution price at reasonable bounds
            execution_price = max(0.01, min(0.99, execution_price))

        return (execution_price, spread, max(0, slippage_pct), fill_pct, delay_impact_pct)
