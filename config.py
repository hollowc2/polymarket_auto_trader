import os
from dotenv import load_dotenv

load_dotenv()


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
    MAX_DAILY_BETS: int = int(os.getenv("MAX_DAILY_BETS", "50"))
    MAX_DAILY_LOSS: float = float(os.getenv("MAX_DAILY_LOSS", "50"))

    # Timing
    ENTRY_SECONDS_BEFORE: int = int(os.getenv("ENTRY_SECONDS_BEFORE", "30"))

    # Mode
    PAPER_TRADE: bool = os.getenv("PAPER_TRADE", "true").lower() == "true"

    # Logging
    LOG_FILE: str = "bot.log"
    TRADES_FILE: str = "trades.json"
