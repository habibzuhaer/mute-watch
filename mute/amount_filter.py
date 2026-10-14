"""Minimum transfer size filter — human USDT/USDC threshold."""

from __future__ import annotations

import re
from typing import Any

# Dollar-pegged symbols we treat as ~1 USD for MIN_USDT
_STABLE_RE = re.compile(
    r"^(USDT|USDC|USD1|FDUSD|USDE|DAI|TUSD|USDD|BUSD|USDP|GUSD|FRAX|USDV|USDY|CUSD|SUSD)$",
    re.I,
)


def is_stable_symbol(symbol: str | None) -> bool:
    if not symbol:
        return False
    # strip common wrappers: USDT.e, bridged names
    s = str(symbol).strip()
    if _STABLE_RE.match(s):
        return True
    base = s.split(".")[0].split(" ")[0]
    return bool(_STABLE_RE.match(base))


def parse_amount_human(event: dict[str, Any]) -> float | None:
    """Best-effort human token amount from event fields."""
    if event.get("amount_human") is not None:
        try:
            return float(event["amount_human"])
        except (TypeError, ValueError):
            pass
    raw = event.get("amount_raw")
    decimals = event.get("decimals")
    if raw is not None and decimals is not None:
        try:
            return int(raw) / (10 ** int(decimals))
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    fmt = event.get("amount_fmt")
    if fmt is None:
        return None
    try:
        return float(str(fmt).replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def passes_min_usdt(event: dict[str, Any], min_usdt: float) -> bool:
    """
    If min_usdt <= 0 → always pass.
    For stablecoins (USDT/USDC/…): require amount >= min_usdt.
    Non-stables / native: pass (prep + MM flow still need them).
    """
    if not min_usdt or min_usdt <= 0:
        return True
    if not is_stable_symbol(event.get("symbol")):
        return True
    amt = parse_amount_human(event)
    if amt is None:
        return False
    return amt + 1e-9 >= float(min_usdt)


def attach_amount_fields(
    event: dict[str, Any],
    *,
    raw: str | int | None,
    decimals: str | int | None,
) -> dict[str, Any]:
    """Mutate/return event with amount_raw / decimals / amount_human."""
    try:
        dec = int(decimals) if decimals is not None and str(decimals) != "" else None
    except (TypeError, ValueError):
        dec = None
    try:
        raw_i = int(raw) if raw is not None and str(raw) != "" else None
    except (TypeError, ValueError):
        raw_i = None
    if raw_i is not None:
        event["amount_raw"] = raw_i
    if dec is not None:
        event["decimals"] = dec
    if raw_i is not None and dec is not None and dec >= 0:
        event["amount_human"] = raw_i / (10**dec)
    return event
