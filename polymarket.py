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
            outcome = None
            if m.get("closed"):
                if up_price == 1.0:
                    outcome = "up"
                elif down_price == 1.0:
                    outcome = "down"

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
