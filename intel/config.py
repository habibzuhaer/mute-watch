"""Intel config — long collect runs (e.g. 12h × N)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("INTEL_DATA_DIR", str(ROOT / "data" / "intel")))
STATE_FILE = DATA_DIR / "state.json"
PID_FILE = ROOT / "intel.pid"
OUT_HTML = ROOT / "out" / "intel.html"

# Legacy MUTE graph (adapter source)
GRAPH_DIR = Path(os.getenv("MUTE_GRAPH_DIR", str(ROOT / "data" / "graph")))

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "").strip()
ETHERSCAN_V2 = os.getenv("ETHERSCAN_V2", "https://api.etherscan.io/v2/api").rstrip("/")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "").strip()
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com").rstrip("/")

REQUEST_DELAY_SEC = float(os.getenv("INTEL_REQUEST_DELAY", os.getenv("REQUEST_DELAY_SEC", "0.4")))
LANG = os.getenv("INTEL_LANG", "uk").strip().lower() or "uk"  # uk | en

# Collect budgets (tuned for multi-hour / 12h runs — refine later)
COLLECT_HOURS_DEFAULT = float(os.getenv("INTEL_COLLECT_HOURS", "12"))
CYCLE_SLEEP_SEC = float(os.getenv("INTEL_CYCLE_SLEEP", "45"))
SEEDS_PER_CYCLE = int(os.getenv("INTEL_SEEDS_PER_CYCLE", "6"))
TX_LIMIT_SOL = int(os.getenv("INTEL_TX_LIMIT_SOL", "40"))
TX_OFFSET_EVM = int(os.getenv("INTEL_TX_OFFSET_EVM", "50"))
MAX_NEW_NEIGHBORS = int(os.getenv("INTEL_MAX_NEW_NEIGHBORS", "25"))
QUEUE_CAP = int(os.getenv("INTEL_QUEUE_CAP", "2000"))
EXPAND_HOP_MAX = int(os.getenv("INTEL_EXPAND_HOP_MAX", "2"))

# Chains to collect (phase: both Solana + BNB; EVM adapter always on)
ENABLE_BNB = os.getenv("INTEL_ENABLE_BNB", "1").strip() not in {"0", "false", "no"}
ENABLE_SOL = os.getenv("INTEL_ENABLE_SOL", "1").strip() not in {"0", "false", "no"}
ENABLE_EVM_ADAPTER = os.getenv("INTEL_ENABLE_EVM_ADAPTER", "1").strip() not in {"0", "false", "no"}
try:
    from mute.config import solana_rpc_usable

    if ENABLE_SOL and not solana_rpc_usable(HELIUS_API_KEY, SOLANA_RPC_URL):
        ENABLE_SOL = False
except Exception:
    pass

BNB_CHAIN_ID = 56
EVM_EXPAND_CHAINS = [
    int(x)
    for x in os.getenv("INTEL_EVM_CHAINS", "56,1,42161,8453").split(",")
    if x.strip().isdigit()
]

# Activity / pre-pump windows
ACTIVITY_WINDOW_SEC = int(os.getenv("INTEL_ACTIVITY_WINDOW_SEC", str(6 * 3600)))
PREPUMP_DAYS = float(os.getenv("INTEL_PREPUMP_DAYS", "30"))
SPIKE_MIN_TX = int(os.getenv("INTEL_SPIKE_MIN_TX", "8"))
SPIKE_MIN_UNIQUE = int(os.getenv("INTEL_SPIKE_MIN_UNIQUE", "5"))
