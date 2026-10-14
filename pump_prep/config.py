"""pump_prep configuration."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PACKAGE_DIR = Path(__file__).resolve().parent
OUT_DIR = PACKAGE_DIR / "out"
OUT_DIR.mkdir(exist_ok=True)

SEEDS_FILE = Path(
    os.getenv("PUMP_PREP_SEEDS", str(ROOT / "addresses" / "pump_prep_watchlist.json"))
)
MCAP_CACHE = Path(
    os.getenv(
        "PUMP_PREP_MCAP_CACHE",
        str(ROOT / "crypto_funds_tracker" / "out" / "tokens_mcap_350k_60m.json"),
    )
)

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "").strip()
ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"

# Lookback window for prep signals
LOOKBACK_DAYS = int(os.getenv("PUMP_PREP_DAYS", "14"))
# Max tokentx rows per address per chain
TX_OFFSET = int(os.getenv("PUMP_PREP_TX_OFFSET", "100"))
REQUEST_DELAY_SEC = float(os.getenv("PUMP_PREP_DELAY", "0.4"))

# Chains to scan (core MM flows)
CHAINS: dict[int, str] = {
    1: "Ethereum",
    56: "BSC",
    42161: "Arbitrum",
    8453: "Base",
}

MCAP_MIN = float(os.getenv("PUMP_PREP_MCAP_MIN", "350000"))
MCAP_MAX = float(os.getenv("PUMP_PREP_MCAP_MAX", "60000000"))

# How many top counterparties to optionally expand (1-hop fetch)
EXPAND_TOP_N = int(os.getenv("PUMP_PREP_EXPAND_N", "8"))

EXPLORERS: dict[int, str] = {
    1: "https://etherscan.io",
    56: "https://bscscan.com",
    42161: "https://arbiscan.io",
    8453: "https://basescan.org",
}
