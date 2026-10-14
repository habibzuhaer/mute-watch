from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Etherscan V2 chain IDs commonly used by MM flows.
# Profiles control how many API calls we make per cycle.
CHAIN_PROFILES: dict[str, dict[int, str]] = {
    "core": {
        1: "Ethereum",
        56: "BSC",
        42161: "Arbitrum",
        8453: "Base",
    },
    "wide": {
        1: "Ethereum",
        56: "BSC",
        42161: "Arbitrum",
        8453: "Base",
        137: "Polygon",
        10: "Optimism",
        43114: "Avalanche",
        59144: "Linea",
        534352: "Scroll",
        5000: "Mantle",
        81457: "Blast",
        250: "Fantom",
    },
    "max": {
        1: "Ethereum",
        56: "BSC",
        42161: "Arbitrum",
        8453: "Base",
        137: "Polygon",
        10: "Optimism",
        43114: "Avalanche",
        59144: "Linea",
        534352: "Scroll",
        5000: "Mantle",
        81457: "Blast",
        250: "Fantom",
        25: "Cronos",
        100: "Gnosis",
        324: "zkSync",
        1101: "Polygon zkEVM",
        1284: "Moonbeam",
        42220: "Celo",
        59140: "Linea Goerli",  # rarely useful; kept off by default filter below
    },
}

# Drop obvious testnets from max if present
_TESTNET_IDS = {59140}


def solana_rpc_usable(helius_key: str = "", rpc_url: str = "") -> bool:
    """Public mainnet-beta cannot carry live/collect traffic. Helius or a private RPC can."""
    if (helius_key or "").strip():
        return True
    u = (rpc_url or "").strip().lower()
    if not u:
        return False
    if "helius" in u:
        return True
    if "mainnet-beta.solana.com" in u:
        return False
    return True


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    etherscan_api_key: str
    trongrid_api_key: str
    helius_api_key: str
    solana_rpc_url: str
    chain_profile: str
    poll_interval_sec: int
    request_delay_sec: float
    parallel: bool
    parallel_workers: int
    addresses_file: Path
    data_dir: Path
    log_dir: Path
    alert_native: bool
    alert_tokens: bool
    min_token_amount_raw: int  # legacy raw units; 0 = off
    min_usdt: float  # human USDT/USDC threshold; 0 = off
    dry_run: bool
    # all = any inbound (classic MUTE); prep = obscure token in + CEX deposits out
    alert_mode: str
    # Prep Telegram: only send if score >= this (0 = send all prep matches)
    signal_min_score: int

    @property
    def chains(self) -> dict[int, str]:
        profile = self.chain_profile if self.chain_profile in CHAIN_PROFILES else "core"
        chains = dict(CHAIN_PROFILES[profile])
        for tid in _TESTNET_IDS:
            chains.pop(tid, None)
        return chains


_POLL_PRESETS = {
    "5m": 300,
    "15m": 900,
    "5": 300,
    "15": 900,
}


def _resolve_poll_interval() -> int:
    """Prefer POLL_PRESET (5m/15m); explicit POLL_INTERVAL_SEC overrides."""
    raw_interval = os.getenv("POLL_INTERVAL_SEC", "").strip()
    preset = os.getenv("POLL_PRESET", "5m").strip().lower()
    if raw_interval:
        return max(60, int(raw_interval))
    if preset in _POLL_PRESETS:
        return _POLL_PRESETS[preset]
    return 300


def load_settings() -> Settings:
    profile = os.getenv("CHAIN_PROFILE", "wide").strip().lower()
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        etherscan_api_key=os.getenv("ETHERSCAN_API_KEY", "").strip(),
        trongrid_api_key=os.getenv("TRONGRID_API_KEY", "").strip(),
        helius_api_key=os.getenv("HELIUS_API_KEY", "").strip(),
        solana_rpc_url=os.getenv(
            "SOLANA_RPC_URL",
            "https://api.mainnet-beta.solana.com",
        ).strip(),
        chain_profile=profile,
        poll_interval_sec=_resolve_poll_interval(),
        request_delay_sec=float(os.getenv("REQUEST_DELAY_SEC", "0.35")),
        parallel=os.getenv("PARALLEL", "1") == "1",
        parallel_workers=max(1, int(os.getenv("PARALLEL_WORKERS", "6"))),
        addresses_file=Path(
            os.getenv("ADDRESSES_FILE", str(ROOT / "addresses" / "dwf_labs.json"))
        ),
        data_dir=Path(os.getenv("DATA_DIR", str(ROOT / "data"))),
        log_dir=Path(os.getenv("LOG_DIR", str(ROOT / "logs"))),
        alert_native=os.getenv("ALERT_NATIVE", "1") == "1",
        alert_tokens=os.getenv("ALERT_TOKENS", "1") == "1",
        min_token_amount_raw=int(os.getenv("MIN_TOKEN_AMOUNT_RAW", "0")),
        min_usdt=float(os.getenv("MIN_USDT", "0") or 0),
        dry_run=os.getenv("DRY_RUN", "0") == "1",
        alert_mode=os.getenv("ALERT_MODE", "all").strip().lower() or "all",
        signal_min_score=int(os.getenv("SIGNAL_MIN_SCORE", "55")),
    )


def load_wallets(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    wallets = data.get("wallets", [])
    if not wallets:
        raise ValueError(f"No wallets in {path}")
    return wallets


def resource_estimate(settings: Settings, wallets: list[dict]) -> dict:
    """Rough per-cycle API call estimate for Termix/server sizing."""
    evm = [w for w in wallets if w.get("family") == "evm"]
    sol = [w for w in wallets if w.get("family") == "solana"]
    tron = [w for w in wallets if w.get("family") == "tron"]
    chains = len(settings.chains)
    # tokentx + (optional) txlist per address per chain
    actions = 1 + (1 if settings.alert_native else 0)
    evm_calls = len(evm) * chains * actions
    sol_calls = len(sol) * 2  # signatures + parsed txs batch-ish
    tron_calls = len(tron) * 2  # trc20 + trx
    total = evm_calls + sol_calls + tron_calls
    cycles_per_hour = 3600 / max(settings.poll_interval_sec, 1)
    return {
        "profile": settings.chain_profile,
        "evm_addresses": len(evm),
        "sol_addresses": len(sol),
        "tron_addresses": len(tron),
        "evm_chains": chains,
        "api_calls_per_cycle": total,
        "api_calls_per_hour": int(total * cycles_per_hour),
        "poll_interval_sec": settings.poll_interval_sec,
        "ram_mb_typical": "30–60",
        "cpu_typical": "near-idle between polls",
        "android_note": (
            "Run on a always-on host; control via Termix SSH. "
            "Do not run the poller on the phone itself."
        ),
    }
