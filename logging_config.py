"""Structured logging configuration for production use.

Provides consistent, parseable log output with key metrics.
"""

import json
import sys
import time
from datetime import datetime
from typing import Any

from config import Config, LOCAL_TZ, TIMEZONE_NAME


class StructuredLogger:
    """Simple structured logger with consistent formatting.

    Output format is designed to be:
    - Human readable in console
    - Easy to grep and analyze
    - Contains key metrics for debugging

    Example output:
        [14:32:15] INFO  order_placed | order_id=abc123 amount=5.00 latency_ms=45
        [14:32:16] ERROR api_error | endpoint=/book error="timeout" retries=2
    """

    LEVELS = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }

    def __init__(self, name: str = "copybot", level: str | None = None):
        """Initialize logger.

        Args:
            name: Logger name (appears in log prefix)
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self.name = name
        self.level = self.LEVELS.get((level or Config.LOG_LEVEL).upper(), 20)

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

        # Format level (fixed width)
        level_str = level.ljust(5)

        # Build log line
        parts = [f"[{ts}]", level_str, event]

        if kwargs:
            parts.append("|")
            parts.append(self._format_kwargs(kwargs))

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
        **kwargs
    ):
        """Log order placement."""
        self.info(
            "order_placed",
            order_id=order_id,
            direction=direction,
            amount=amount,
            price=price,
            latency_ms=latency_ms,
            **kwargs
        )

    def order_filled(
        self,
        order_id: str,
        filled_size: float,
        fill_price: float,
        latency_ms: float | None = None,
        **kwargs
    ):
        """Log order fill."""
        self.info(
            "order_filled",
            order_id=order_id,
            filled_size=filled_size,
            fill_price=fill_price,
            latency_ms=latency_ms,
            **kwargs
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
        **kwargs
    ):
        """Log trade settlement."""
        self.info(
            "trade_settled",
            market=market,
            direction=direction,
            outcome=outcome,
            pnl=pnl,
            won=won,
            **kwargs
        )

    def copy_signal(
        self,
        trader: str,
        direction: str,
        amount: float,
        price: float,
        delay_ms: int,
        **kwargs
    ):
        """Log copy trade signal."""
        self.info(
            "copy_signal",
            trader=trader,
            direction=direction,
            amount=amount,
            price=price,
            delay_ms=delay_ms,
            **kwargs
        )

    def circuit_breaker(self, name: str, state: str, failures: int, **kwargs):
        """Log circuit breaker state change."""
        level = "WARNING" if state == "open" else "INFO"
        self._log(level, "circuit_breaker", name=name, state=state, failures=failures, **kwargs)

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
        **kwargs
    ):
        """Log periodic heartbeat."""
        win_rate = (wins / (wins + losses) * 100) if wins + losses > 0 else 0
        self.info(
            "heartbeat",
            pending=pending,
            wins=wins,
            losses=losses,
            win_rate=f"{win_rate:.0f}%",
            pnl=pnl,
            bankroll=bankroll,
            **kwargs
        )


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
