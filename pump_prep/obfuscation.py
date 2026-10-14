"""Heuristics for obfuscated prep flows: hops, same-amount, fresh wallets, bridges."""

from __future__ import annotations

import time
from typing import Any

# Same-amount chain: allow ±0.5% (fees / rounding)
SAME_AMOUNT_TOL = float(__import__("os").getenv("MUTE_SAME_AMOUNT_TOL", "0.005"))

# Wallet is "fresh" if first on-chain activity younger than this
FRESH_WALLET_DAYS = int(__import__("os").getenv("MUTE_FRESH_WALLET_DAYS", "14"))


def human_amount(value_raw: Any, decimals: Any) -> float | None:
    try:
        raw = int(value_raw)
        dec = int(decimals)
        if dec < 0:
            return None
        return raw / (10**dec)
    except (TypeError, ValueError):
        return None


def amounts_match(
    a: float | None,
    b: float | None,
    *,
    tol: float = SAME_AMOUNT_TOL,
) -> bool:
    """True if two human amounts are within relative tolerance."""
    if a is None or b is None:
        return False
    try:
        a = float(a)
        b = float(b)
    except (TypeError, ValueError):
        return False
    if a <= 0 or b <= 0:
        return False
    base = max(a, b)
    return abs(a - b) / base <= tol


def wallet_age_days(first_ts: Any, *, now: float | None = None) -> float | None:
    """Days since first known activity timestamp (unix sec)."""
    if not first_ts:
        return None
    try:
        ts = int(first_ts)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    now = time.time() if now is None else now
    return max(0.0, (now - ts) / 86400)


def is_fresh_wallet(first_ts: Any, *, max_days: int = FRESH_WALLET_DAYS, now: float | None = None) -> bool:
    age = wallet_age_days(first_ts, now=now)
    if age is None:
        return False
    return age <= max_days


def hop_from_via(via: str | None) -> int:
    v = (via or "").lower().strip()
    if v in ("expand2", "hop2", "2hop"):
        return 2
    if v in ("expand3", "hop3", "3hop"):
        return 3
    if v in ("expand", "hop1", "1hop"):
        return 1
    if v in ("deployer", "live", "live_prep", ""):
        return 0
    return 1 if "expand" in v else 0


def detect_same_amount_vs_edges(
    *,
    amount: float | None,
    counterparty: str | None,
    edges: list[dict[str, Any]],
    window_sec: int = 7 * 86400,
    now_ts: int | None = None,
) -> dict[str, Any] | None:
    """
    Look for another edge involving counterparty with nearly the same amount
    within window (classic hop obfuscation: A→B 50k, B→C ~50k).
    """
    if amount is None or not counterparty or not edges:
        return None
    cp = counterparty.lower()
    now_ts = int(now_ts or time.time())
    for e in edges:
        other_amt = e.get("amount_human")
        if other_amt is None:
            other_amt = human_amount(e.get("value_raw"), e.get("decimals") or e.get("token_decimals"))
        if not amounts_match(amount, other_amt):
            continue
        addrs = {
            (e.get("from_addr") or e.get("from") or "").lower(),
            (e.get("to_addr") or e.get("to") or "").lower(),
        }
        if cp not in addrs:
            continue
        ts = e.get("timestamp")
        try:
            ts_i = int(ts) if ts else 0
        except (TypeError, ValueError):
            ts_i = 0
        if ts_i and abs(now_ts - ts_i) > window_sec:
            continue
        return {
            "matched_amount": other_amt,
            "edge_hash": e.get("hash"),
            "from": e.get("from_addr") or e.get("from"),
            "to": e.get("to_addr") or e.get("to"),
            "timestamp": ts_i,
        }
    return None
