"""Structured logging configuration for production use.

Provides consistent, parseable log output with key metrics and colors.
"""

import sys
from datetime import datetime
from typing import Any

from src.config import Config, LOCAL_TZ


# ANSI color codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"

    # Background colors
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"


class StructuredLogger:
    """Simple structured logger with consistent formatting and colors.

    Output format is designed to be:
    - Human readable in console with colors
    - Easy to grep and analyze
    - Contains key metrics for debugging

    Example output:
        [14:32:15] ✓ WIN  UP @ 0.48 → UP | PnL: +$2.15 | 3W/1L (75%)
        [14:32:16] ⚠ WARN api_timeout | retries=2
    """

    LEVELS = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }

    # Level colors and symbols
    LEVEL_STYLE = {
        "DEBUG": (Colors.GRAY, "·"),
        "INFO": (Colors.CYAN, "→"),
        "WARNING": (Colors.YELLOW, "⚠"),
        "ERROR": (Colors.RED, "✗"),
        "CRITICAL": (Colors.BG_RED + Colors.WHITE, "☠"),
    }

    def __init__(
        self, name: str = "copybot", level: str | None = None, use_colors: bool = True
    ):
        """Initialize logger.

        Args:
            name: Logger name (appears in log prefix)
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            use_colors: Whether to use ANSI colors (default True)
        """
        self.name = name
        self.level = self.LEVELS.get((level or Config.LOG_LEVEL).upper(), 20)
        self.use_colors = use_colors and sys.stdout.isatty()

    def _c(self, color: str, text: str) -> str:
        """Apply color to text if colors are enabled."""
        if self.use_colors:
            return f"{color}{text}{Colors.RESET}"
        return text

    def _format_value(self, value: Any) -> str:
        """Format a value for log output."""
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, float):
            # Format floats consistently
            if abs(value) < 0.01 and value != 0:
                return f"{value:.4f}"
            elif abs(value) >= 1000:
                return f"{value:.0f}"
            else:
                return f"{value:.2f}"
        elif isinstance(value, str):
            # Quote strings with spaces
            if " " in value or "=" in value:
                return f'"{value}"'
            return value
        else:
            return str(value)

    def _format_kwargs(self, kwargs: dict) -> str:
        """Format kwargs as key=value pairs."""
        parts = []
        for key, value in kwargs.items():
            if key.startswith("_"):
                continue
            parts.append(f"{key}={self._format_value(value)}")
        return " ".join(parts)

    def _log(self, level: str, event: str, **kwargs):
        """Internal log method."""
        level_num = self.LEVELS.get(level, 20)
        if level_num < self.level:
            return

        # Timestamp in local timezone
        ts = datetime.now(LOCAL_TZ).strftime("%H:%M:%S")

        # Get level style
        color, symbol = self.LEVEL_STYLE.get(level, (Colors.WHITE, "·"))

        # Build log line with colors
        ts_str = self._c(Colors.DIM, f"[{ts}]")
        symbol_str = self._c(color, symbol)
        event_str = self._c(Colors.BOLD if level_num >= 30 else "", event)

        parts = [ts_str, symbol_str, event_str]

        if kwargs:
            parts.append(self._c(Colors.DIM, "|"))
            parts.append(self._c(Colors.GRAY, self._format_kwargs(kwargs)))

        line = " ".join(parts)
        print(line, file=sys.stdout if level_num < 40 else sys.stderr)

    def debug(self, event: str, **kwargs):
        """Log debug message."""
        self._log("DEBUG", event, **kwargs)

    def info(self, event: str, **kwargs):
        """Log info message."""
        self._log("INFO", event, **kwargs)

    def warning(self, event: str, **kwargs):
        """Log warning message."""
        self._log("WARNING", event, **kwargs)

    def error(self, event: str, **kwargs):
        """Log error message."""
        self._log("ERROR", event, **kwargs)

    def critical(self, event: str, **kwargs):
        """Log critical message."""
        self._log("CRITICAL", event, **kwargs)

    # Convenience methods for common events

    def order_placed(
        self,
        order_id: str,
        direction: str,
        amount: float,
        price: float,
        latency_ms: float | None = None,
        **kwargs,
    ):
        """Log order placement."""
        self.info(
            "order_placed",
            order_id=order_id,
            direction=direction,
            amount=amount,
            price=price,
            latency_ms=latency_ms,
            **kwargs,
        )

    def order_filled(
        self,
        order_id: str,
        filled_size: float,
        fill_price: float,
        latency_ms: float | None = None,
        **kwargs,
    ):
        """Log order fill."""
        self.info(
            "order_filled",
            order_id=order_id,
            filled_size=filled_size,
            fill_price=fill_price,
            latency_ms=latency_ms,
            **kwargs,
        )

    def order_failed(self, order_id: str, error: str, **kwargs):
        """Log order failure."""
        self.error("order_failed", order_id=order_id, error=error, **kwargs)

    def trade_settled(
        self,
        market: str,
        direction: str,
        outcome: str,
        pnl: float,
        won: bool,
        bankroll: float = 0,
        pending: int = 0,
        wins: int = 0,
        losses: int = 0,
        **kwargs,
    ):
        """Log trade settlement - clean, single line."""
        ts = datetime.now(LOCAL_TZ).strftime("%H:%M:%S")
        ts_str = self._c(Colors.DIM, f"[{ts}]")

        if won:
            result = self._c(Colors.GREEN + Colors.BOLD, "WIN ")
            pnl_str = self._c(Colors.GREEN, f"+${pnl:.2f}")
        else:
            result = self._c(Colors.RED + Colors.BOLD, "LOSS")
            pnl_str = self._c(Colors.RED, f"-${abs(pnl):.2f}")

        direction_str = direction.upper()
        outcome_str = outcome.upper()
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0

        # Clean single-line format
        line = f"{ts_str} {result} {direction_str}→{outcome_str} {pnl_str} | {wins}W/{losses}L ({win_rate:.0f}%) | ${bankroll:.2f}"
        print(line)

    def copy_signal(
        self,
        trader: str,
        direction: str,
        amount: float,
        price: float,
        delay_ms: int,
        our_amount: float = 0,
        **kwargs,
    ):
        """Log copy trade signal with full details."""
        ts = datetime.now(LOCAL_TZ).strftime("%H:%M:%S")
        ts_str = self._c(Colors.DIM, f"[{ts}]")

        copy_icon = self._c(Colors.MAGENTA + Colors.BOLD, "📋 COPY")
        trader_str = self._c(Colors.CYAN, trader)
        direction_str = self._c(
            Colors.GREEN if direction.lower() == "up" else Colors.RED, direction.upper()
        )

        delay_sec = delay_ms / 1000
        delay_color = (
            Colors.GREEN
            if delay_sec < 5
            else (Colors.YELLOW if delay_sec < 15 else Colors.RED)
        )
        delay_str = self._c(delay_color, f"{delay_sec:.1f}s")

        line = f"{ts_str} {copy_icon} {trader_str}: {direction_str} @ {price:.2f} (${amount:.0f}) → ${our_amount:.2f} | Delay: {delay_str}"
        print(line)

    def circuit_breaker(self, name: str, state: str, failures: int, **kwargs):
        """Log circuit breaker state change."""
        level = "WARNING" if state == "open" else "INFO"
        self._log(
            level,
            "circuit_breaker",
            name=name,
            state=state,
            failures=failures,
            **kwargs,
        )

    def rate_limited(self, endpoint: str, wait_time: float, **kwargs):
        """Log rate limiting."""
        self.warning("rate_limited", endpoint=endpoint, wait_time=wait_time, **kwargs)

    def health_check(self, healthy: bool, components: dict, **kwargs):
        """Log health check result."""
        level = "INFO" if healthy else "WARNING"
        self._log(level, "health_check", healthy=healthy, **kwargs)

    def heartbeat(
        self,
        pending: int,
        wins: int,
        losses: int,
        pnl: float,
        bankroll: float,
        unrealized: float = 0,
        ws_connected: bool = False,
        **kwargs,
    ):
        """Log periodic heartbeat with status."""
        ts = datetime.now(LOCAL_TZ).strftime("%H:%M:%S")
        ts_str = self._c(Colors.DIM, f"[{ts}]")

        # Heartbeat symbol
        ws_status = (
            self._c(Colors.GREEN, "●") if ws_connected else self._c(Colors.YELLOW, "○")
        )

        total = wins + losses
        if total > 0:
            win_rate = wins / total * 100
            stats = f"{wins}W/{losses}L ({win_rate:.0f}%)"
        else:
            stats = "waiting..."

        # Color PnL
        if pnl > 0:
            pnl_str = self._c(Colors.GREEN, f"+${pnl:.2f}")
        elif pnl < 0:
            pnl_str = self._c(Colors.RED, f"-${abs(pnl):.2f}")
        else:
            pnl_str = self._c(Colors.DIM, "$0.00")

        # Compact single line
        parts = [
            f"{ts_str} {ws_status}",
            self._c(Colors.DIM, f"Pending:{pending}"),
            stats,
            f"PnL:{pnl_str}",
            self._c(Colors.DIM, f"Bank:${bankroll:.2f}"),
        ]

        # Add unrealized if there are pending trades
        if pending > 0 and unrealized != 0:
            unr_color = Colors.GREEN if unrealized > 0 else Colors.RED
            unr_sign = "+" if unrealized > 0 else ""
            parts.append(self._c(unr_color, f"(EV:{unr_sign}${unrealized:.2f})"))

        line = " | ".join(parts)
        print(line)

    def pending_trades(
        self,
        trades: list[dict],
    ):
        """Log pending trades with up/down percentages."""
        if not trades:
            return

        ts = datetime.now(LOCAL_TZ).strftime("%H:%M:%S")
        ts_str = self._c(Colors.DIM, f"[{ts}]")

        parts = []
        for t in trades:
            direction = t.get("direction", "?")[0].upper()
            prob = t.get("current_prob", 0)
            likely_win = t.get("likely_win", False)

            # Color based on win/loss likelihood
            if likely_win:
                status = self._c(Colors.GREEN, f"{direction}↑{prob:.0%}")
            else:
                status = self._c(Colors.RED, f"{direction}↓{prob:.0%}")
            parts.append(status)

        pending_str = " ".join(parts)
        line = f"{ts_str} {self._c(Colors.DIM, '       └─')} {pending_str}"
        print(line)

    def trade_placed(
        self,
        trade_num: int,
        pending: int,
        wins: int,
        losses: int,
        pnl: float,
    ):
        """Log trade placement confirmation."""
        ts = datetime.now(LOCAL_TZ).strftime("%H:%M:%S")
        ts_str = self._c(Colors.DIM, f"[{ts}]")

        total = wins + losses
        if total > 0:
            win_rate = wins / total * 100
            stats = f"{wins}W/{losses}L ({win_rate:.0f}%)"
        else:
            stats = "no results yet"

        placed = self._c(Colors.GREEN, f"✓ Placed #{trade_num}")

        if pnl >= 0:
            pnl_str = self._c(Colors.GREEN, f"+${pnl:.2f}")
        else:
            pnl_str = self._c(Colors.RED, f"-${abs(pnl):.2f}")

        line = f"{ts_str} {placed} | Pending: {pending} | {stats} | PnL: {pnl_str}"
        print(line)

    def status_line(self, message: str):
        """Log a simple status message."""
        ts = datetime.now(LOCAL_TZ).strftime("%H:%M:%S")
        ts_str = self._c(Colors.DIM, f"[{ts}]")
        print(f"{ts_str} {self._c(Colors.DIM, message)}")


# Global logger instance
log = StructuredLogger()


def get_logger(name: str = "copybot") -> StructuredLogger:
    """Get a logger instance.

    Args:
        name: Logger name

    Returns:
        StructuredLogger instance
    """
    return StructuredLogger(name=name)
