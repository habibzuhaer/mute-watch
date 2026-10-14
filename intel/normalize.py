"""Chain-aware address normalization."""

from __future__ import annotations

import re
from typing import Any

ZERO_EVM = "0x0000000000000000000000000000000000000000"
DEAD_EVM = "0x000000000000000000000000000000000000dead"

# Solana base58-ish (no 0/O/I/l), length 32–44
_SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def detect_chain_hint(addr: str) -> str | None:
    a = (addr or "").strip()
    if _EVM_RE.match(a):
        return "evm"
    if _SOL_RE.match(a) and not a.startswith("0x"):
        return "solana"
    return None


def norm(chain: str, addr: Any) -> str:
    """Normalize address for storage key. Empty if invalid."""
    a = (addr or "").strip()
    if not a or a in {"?", "-", "unknown"}:
        return ""
    ch = (chain or "").lower()
    if ch in {"sol", "solana"}:
        # reject Tron-style T… and EVM
        if a.startswith("0x") or (a.startswith("T") and len(a) <= 36):
            return ""
        if _SOL_RE.match(a):
            return a
        return ""
    # bnb / evm / eth / arbitrum / base …
    al = a.lower()
    if not _EVM_RE.match(al):
        return ""
    if al in {ZERO_EVM, DEAD_EVM}:
        return ""
    return al


def short(addr: str | None, n: int = 4) -> str:
    a = (addr or "").strip()
    if len(a) < n * 2 + 2:
        return a
    return a[:n] + "…" + a[-n:]


def chain_id_to_name(chain_id: int) -> str:
    return {
        1: "ethereum",
        56: "bnb",
        42161: "arbitrum",
        8453: "base",
        137: "polygon",
    }.get(int(chain_id), f"evm_{chain_id}")


def storage_chain(chain: str, chain_id: int | None = None) -> str:
    c = (chain or "").lower()
    if c in {"sol", "solana"}:
        return "solana"
    if c in {"bnb", "bsc", "binance-smart-chain"} or chain_id == 56:
        return "bnb"
    if chain_id:
        return chain_id_to_name(chain_id)
    if c in {"eth", "ethereum"}:
        return "ethereum"
    return c or "evm"
