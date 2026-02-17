"""Copytrade module - monitor wallets and copy BTC 5-min trades."""

import re
import time
from dataclasses import dataclass

import requests

from src.config import Config


@dataclass
class CopySignal:
    """Signal emitted when a tracked wallet makes a BTC 5-min trade."""

    wallet: str
    direction: str  # "Up" or "Down"
    market_ts: int  # Unix timestamp of the market (from slug)
    trade_ts: int  # Unix timestamp when trader placed the trade
    side: str  # "BUY" or "SELL"
    price: float
    size: float  # shares
    usdc_amount: float
    tx_hash: str
    trader_name: str

    # On-chain data (optional, fetched from Polygonscan)
    block_number: int | None = None
    gas_used: int | None = None
    tx_fee_matic: float | None = None
    on_chain_timestamp: int | None = None


class CopytradeMonitor:
    """Monitor specific wallets for BTC 5-min trades."""

    # Pattern: btc-updown-5m-{timestamp}
    BTC_5M_PATTERN = re.compile(r"^btc-updown-5m-(\d+)$")

    def __init__(self, wallets: list[str] | None = None):
        self.wallets = wallets or Config.COPY_WALLETS
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "PolymarketCopyBot/1.0", "Accept": "application/json"})
        # Track last seen timestamp per wallet to detect new trades
        self.last_seen: dict[str, int] = {w: int(time.time()) for w in self.wallets}

    def _fetch_activity(self, wallet: str, limit: int = 10) -> list[dict]:
        """Fetch recent activity for a wallet."""
        try:
            resp = self.session.get(
                f"{Config.DATA_API}/activity",
                params={"user": wallet, "limit": limit, "offset": 0},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[copytrade] Error fetching activity for {wallet[:10]}...: {e}")
            return []

    def _is_btc_5m_trade(self, trade: dict) -> bool:
        """Check if trade is a BTC 5-min market trade."""
        slug = trade.get("slug", "")
        return bool(self.BTC_5M_PATTERN.match(slug))

    def _extract_market_ts(self, slug: str) -> int | None:
        """Extract market timestamp from slug."""
        match = self.BTC_5M_PATTERN.match(slug)
        if match:
            return int(match.group(1))
        return None

    def _trade_to_signal(self, trade: dict) -> CopySignal | None:
        """Convert API trade to CopySignal."""
        slug = trade.get("slug", "")
        market_ts = self._extract_market_ts(slug)
        if not market_ts:
            return None

        return CopySignal(
            wallet=trade.get("proxyWallet", ""),
            direction=trade.get("outcome", ""),  # "Up" or "Down"
            market_ts=market_ts,
            trade_ts=trade.get("timestamp", 0),  # when trader placed the trade
            side=trade.get("side", "BUY"),
            price=float(trade.get("price", 0.5)),
            size=float(trade.get("size", 0)),
            usdc_amount=float(trade.get("usdcSize", 0)),
            tx_hash=trade.get("transactionHash", ""),
            trader_name=trade.get("pseudonym", trade.get("name", "")[:10]),
        )

    def poll(self) -> list[CopySignal]:
        """
        Poll all tracked wallets for new BTC 5-min trades.
        Returns list of new signals since last poll.
        """
        signals: list[CopySignal] = []

        for wallet in self.wallets:
            activity = self._fetch_activity(wallet)
            last_ts = self.last_seen.get(wallet, 0)
            new_last_ts = last_ts

            for trade in activity:
                trade_ts = trade.get("timestamp", 0)
                trade_type = trade.get("type", "")

                # Skip if already seen or not a trade
                if trade_ts <= last_ts or trade_type != "TRADE":
                    continue

                # Only BTC 5-min trades
                if not self._is_btc_5m_trade(trade):
                    continue

                signal = self._trade_to_signal(trade)
                if signal:
                    signals.append(signal)
                    new_last_ts = max(new_last_ts, trade_ts)

            self.last_seen[wallet] = new_last_ts

        return signals

    def get_latest_btc_5m_trades(self, wallet: str, limit: int = 5) -> list[CopySignal]:
        """Get recent BTC 5-min trades for a wallet (for initial state)."""
        activity = self._fetch_activity(wallet, limit=20)
        signals = []

        for trade in activity:
            if trade.get("type") != "TRADE":
                continue
            if not self._is_btc_5m_trade(trade):
                continue
            signal = self._trade_to_signal(trade)
            if signal:
                signals.append(signal)
                if len(signals) >= limit:
                    break

        return signals
