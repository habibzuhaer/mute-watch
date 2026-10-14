"""Crypto funds / DAT portfolio tracker configuration."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "out"
OUT_DIR.mkdir(exist_ok=True)

# Optional — leave empty to skip VC block (no API on your account → leave empty)
ARKHAM_API_KEY = ""

# Optional CoinGecko Pro key (free demo works without it for public_treasury)
COINGECKO_API_KEY = ""
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Focus: mid / small-mid caps (not BTC/ETH mega-caps)
MCAP_MIN_USD = 50_000_000
MCAP_MAX_USD = 600_000_000
EXCLUDE_SYMBOLS = {"BTC", "ETH", "WBTC", "WETH", "STETH", "CBETH"}
EXCLUDE_IDS = {"bitcoin", "ethereum", "wrapped-bitcoin", "weth", "staked-ether"}

# Skip DAT mega-cap treasuries by default (almost only BTC/ETH)
INCLUDE_DAT_TREASURIES = False

# Coins to pull company treasuries for (only if INCLUDE_DAT_TREASURIES)
TREASURY_COINS = ["bitcoin", "ethereum"]

# How many mid-cap market rows to keep (after filter), sorted by volume
MIDCAP_LIMIT = 80
# Compute vol from CoinGecko market_chart for top-N by volume (rate-limit friendly)
VOL_CHART_TOP_N = 8
# Skip multi-exchange fan-out by default (slow); CoinGecko price is enough
FETCH_EXCHANGE_PRICES = False
EXCHANGE_TOP_N = 10

# ccxt exchange ids for spot prices
EXCHANGES = ["binance", "bybit", "okx", "bingx"]

# Volatility windows in days ≈ 3 / 6 / 9 months
VOL_WINDOWS_DAYS = {
    "3m": 90,
    "6m": 180,
    "9m": 270,
}

# Known VC entities for Arkham (used only when ARKHAM_API_KEY is set)
ARKHAM_ENTITIES = [
    {"id": "a16z", "name": "Andreessen Horowitz (a16z)", "website": "https://a16z.com"},
    {"id": "paradigm", "name": "Paradigm", "website": "https://www.paradigm.xyz"},
    {"id": "pantera-capital", "name": "Pantera Capital", "website": "https://panteracapital.com"},
    {"id": "polychain-capital", "name": "Polychain Capital", "website": "https://polychain.capital"},
    {"id": "multicoin-capital", "name": "Multicoin Capital", "website": "https://multicoin.capital"},
]

# Manual website overrides for DAT / public companies when CoinGecko has no URL
FUND_WEBSITES = {
    "Strategy": "https://www.strategy.com",
    "MicroStrategy": "https://www.strategy.com",
    "MARA Holdings": "https://www.mara.com",
    "Metaplanet": "https://metaplanet.jp",
    "Galaxy Digital Holdings Ltd": "https://www.galaxy.com",
    "BitMine Immersion": "https://bitminetech.io",
    "Tesla": "https://www.tesla.com",
    "Block Inc.": "https://block.xyz",
}

REQUEST_TIMEOUT = 30
REQUEST_DELAY = 1.2
