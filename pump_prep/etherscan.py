from __future__ import annotations

import logging
import time
from typing import Any

import requests

from mute.pace import etherscan_wait
from pump_prep.config import ETHERSCAN_API_KEY, ETHERSCAN_V2, REQUEST_DELAY_SEC, TX_OFFSET

logger = logging.getLogger(__name__)


class Pace:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        gap = self.delay - (now - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()


def _etherscan(
    sess: requests.Session,
    api_key: str,
    chain_id: int,
    pace: Pace,
    **params: Any,
) -> list[dict]:
    for _attempt in range(2):
        etherscan_wait()
        q = {"chainid": chain_id, "apikey": api_key, **params}
        try:
            resp = sess.get(ETHERSCAN_V2, params=q, timeout=45)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Etherscan fail chain=%s action=%s", chain_id, params.get("action"))
            return []

        status = str(data.get("status", ""))
        result = data.get("result")
        if status == "1" and isinstance(result, list):
            return result
        if isinstance(result, str) and "rate limit" in result.lower():
            logger.warning("rate limit chain=%s — retry", chain_id)
            time.sleep(2.0)
            continue
        return []
    return []


def fetch_token_transfers(
    sess: requests.Session,
    address: str,
    chain_id: int,
    *,
    api_key: str | None = None,
    pace: Pace | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """Both inbound and outbound ERC-20 transfers for an address."""
    api_key = api_key or ETHERSCAN_API_KEY
    if not api_key:
        logger.warning("ETHERSCAN_API_KEY missing")
        return []
    pace = pace or Pace(REQUEST_DELAY_SEC)
    rows = _etherscan(
        sess,
        api_key,
        chain_id,
        pace,
        module="account",
        action="tokentx",
        address=address,
        page=1,
        offset=offset or TX_OFFSET,
        sort="desc",
    )
    out: list[dict[str, Any]] = []
    addr = address.lower()
    for row in rows:
        frm = (row.get("from") or "").lower()
        to = (row.get("to") or "").lower()
        if addr not in (frm, to):
            continue
        direction = "in" if to == addr else "out"
        out.append(
            {
                "chain_id": chain_id,
                "direction": direction,
                "from": frm,
                "to": to,
                "contract": (row.get("contractAddress") or "").lower(),
                "symbol": row.get("tokenSymbol") or "TOKEN",
                "name": row.get("tokenName") or "",
                "decimals": int(row.get("tokenDecimal") or 18),
                "value_raw": row.get("value") or "0",
                "hash": row.get("hash") or "",
                "timestamp": int(row.get("timeStamp") or 0),
                "seed_address": addr,
            }
        )
    return out


def fetch_native_transfers(
    sess: requests.Session,
    address: str,
    chain_id: int,
    *,
    api_key: str | None = None,
    pace: Pace | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    api_key = api_key or ETHERSCAN_API_KEY
    if not api_key:
        return []
    pace = pace or Pace(REQUEST_DELAY_SEC)
    rows = _etherscan(
        sess,
        api_key,
        chain_id,
        pace,
        module="account",
        action="txlist",
        address=address,
        page=1,
        offset=offset or TX_OFFSET,
        sort="desc",
    )
    out: list[dict[str, Any]] = []
    addr = address.lower()
    for row in rows:
        if row.get("isError") == "1":
            continue
        value = row.get("value") or "0"
        if value == "0":
            continue
        frm = (row.get("from") or "").lower()
        to = (row.get("to") or "").lower()
        if addr not in (frm, to):
            continue
        direction = "in" if to == addr else "out"
        out.append(
            {
                "chain_id": chain_id,
                "direction": direction,
                "from": frm,
                "to": to,
                "contract": "",
                "symbol": "NATIVE",
                "name": "native",
                "decimals": 18,
                "value_raw": value,
                "hash": row.get("hash") or "",
                "timestamp": int(row.get("timeStamp") or 0),
                "seed_address": addr,
                "is_native": True,
            }
        )
    return out
