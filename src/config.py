import os
from datetime import timezone, timedelta
from dotenv import load_dotenv

load_dotenv()


# Timezone configuration
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Jakarta")

# Create timezone object (Asia/Jakarta = UTC+7)
_TZ_OFFSETS = {
    "Asia/Jakarta": timedelta(hours=7),
    "Asia/Singapore": timedelta(hours=8),
    "Asia/Tokyo": timedelta(hours=9),
    "UTC": timedelta(hours=0),
    "America/New_York": timedelta(hours=-5),
    "America/Los_Angeles": timedelta(hours=-8),
}

LOCAL_TZ = timezone(_TZ_OFFSETS.get(TIMEZONE_NAME, timedelta(hours=7)))


class Config:
    # Wallet
    PRIVATE_KEY: str = os.getenv("PRIVATE_KEY", "")

    # Polymarket APIs
    GAMMA_API = "https://gamma-api.polymarket.com"
    CLOB_API = "https://clob.polymarket.com"
    CHAIN_ID = 137  # Polygon mainnet

    # Strategy
    STREAK_TRIGGER: int = int(os.getenv("STREAK_TRIGGER", "4"))
    BET_AMOUNT: float = float(os.getenv("BET_AMOUNT", "5"))
    MIN_BET: float = float(os.getenv("MIN_BET", "1"))
    MAX_DAILY_BETS: int = int(os.getenv("MAX_DAILY_BETS", "100"))
    MAX_DAILY_LOSS: float = float(os.getenv("MAX_DAILY_LOSS", "50"))

    # Timing
    ENTRY_SECONDS_BEFORE: int = int(os.getenv("ENTRY_SECONDS_BEFORE", "30"))

    # Mode
    PAPER_TRADE: bool = os.getenv("PAPER_TRADE", "true").lower() == "true"

    # Logging
    LOG_FILE: str = "bot.log"
    TRADES_FILE: str = "trades.json"

    # Copytrade
    DATA_API = "https://data-api.polymarket.com"
    COPY_WALLETS: list[str] = [
        w.strip() for w in os.getenv("COPY_WALLETS", "").split(",") if w.strip()
    ]
    COPY_POLL_INTERVAL: int = int(os.getenv("COPY_POLL_INTERVAL", "5"))

    # WebSocket settings
    WS_CLOB_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    WS_USER_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
    WS_RTDS_URL = "wss://ws-live-data.polymarket.com"
    USE_WEBSOCKET: bool = os.getenv("USE_WEBSOCKET", "true").lower() == "true"

    # Fast polling mode (1-2s for copytrade)
    FAST_POLL_INTERVAL: float = float(os.getenv("FAST_POLL_INTERVAL", "1.5"))

    # REST client settings
    REST_TIMEOUT: float = float(os.getenv("REST_TIMEOUT", "3"))  # Faster timeout
    REST_RETRIES: int = int(os.getenv("REST_RETRIES", "2"))

    # Trading client settings
    SIGNATURE_TYPE: int = int(
        os.getenv("SIGNATURE_TYPE", "0")
    )  # 0=EOA/MetaMask, 1=Magic/proxy
    FUNDER_ADDRESS: str = os.getenv("FUNDER_ADDRESS", "")  # Required for proxy wallets

    # Resilience settings
    CIRCUIT_BREAKER_THRESHOLD: int = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))
    CIRCUIT_BREAKER_RECOVERY_TIME: int = int(
        os.getenv("CIRCUIT_BREAKER_RECOVERY_TIME", "60")
    )
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = int(
        os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "120")
    )

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Polygonscan API
    POLYGONSCAN_API_KEY: str = os.getenv("POLYGONSCAN_API_KEY", "")

    # Delay impact model parameters
    DELAY_MODEL_BASE_COEF: float = float(os.getenv("DELAY_MODEL_BASE_COEF", "0.8"))
    DELAY_MODEL_MAX_IMPACT: float = float(os.getenv("DELAY_MODEL_MAX_IMPACT", "10.0"))
    DELAY_MODEL_BASELINE_SPREAD: float = float(
        os.getenv("DELAY_MODEL_BASELINE_SPREAD", "0.02")
    )

    # Selective copytrade filter
    SELECTIVE_FILTER: bool = os.getenv("SELECTIVE_FILTER", "false").lower() == "true"
    SELECTIVE_MAX_DELAY_MS: int = int(os.getenv("SELECTIVE_MAX_DELAY_MS", "20000"))
    SELECTIVE_MIN_FILL_PRICE: float = float(
        os.getenv("SELECTIVE_MIN_FILL_PRICE", "0.55")
    )
    SELECTIVE_MAX_FILL_PRICE: float = float(
        os.getenv("SELECTIVE_MAX_FILL_PRICE", "0.80")
    )
    SELECTIVE_MAX_PRICE_MOVEMENT_PCT: float = float(
        os.getenv("SELECTIVE_MAX_PRICE_MOVEMENT_PCT", "15.0")
    )
    SELECTIVE_MAX_SPREAD: float = float(os.getenv("SELECTIVE_MAX_SPREAD", "0.025"))
    SELECTIVE_MAX_VOLATILITY_FACTOR: float = float(
        os.getenv("SELECTIVE_MAX_VOLATILITY_FACTOR", "1.25")
    )
    SELECTIVE_MIN_DEPTH_AT_BEST: float = float(
        os.getenv("SELECTIVE_MIN_DEPTH_AT_BEST", "5.0")
    )
