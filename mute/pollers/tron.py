from __future__ import annotations

import logging
from typing import Any

import requests

from mute.amount_filter import attach_amount_fields

logger = logging.getLogger(__name__)

TRONSCAN_TX = "https://tronscan.org/#/transaction/"


def fetch_tron_inbounds(
    *,
    address: str,
    wallet_label: str,
    api_key: str = "",
    limit: int = 80,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    sess = session or requests.Session()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["TRON-PRO-API-KEY"] = api_key

    events: list[dict[str, Any]] = []

    # TRC-20 transfers to address
    try:
        resp = sess.get(
            "https://api.trongrid.io/v1/accounts/{}/transactions/trc20".format(address),
            params={"limit": limit, "only_to": "true", "order_by": "block_timestamp,desc"},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []
    except Exception:
        logger.exception("TronGrid TRC20 failed for %s", address)
        data = []

    for row in data:
        if (row.get("to") or "") != address:
            continue
        txh = row.get("transaction_id") or ""
        token_info = row.get("token_info") or {}
        decimals = int(token_info.get("decimals") or 6)
        raw = row.get("value") or "0"
        try:
            amount = int(raw) / (10**decimals)
            amount_fmt = f"{amount:.8f}".rstrip("0").rstrip(".")
        except Exception:
            amount_fmt = str(raw)
            amount = None
        ev = {
                "dedupe_key": f"tron:trc20:{txh}:{address}:{token_info.get('address','')}",
                "chain": "TRON",
                "address": address,
                "wallet_label": wallet_label,
                "kind": "TRC-20 IN",
                "symbol": token_info.get("symbol") or "TRC20",
                "amount_fmt": amount_fmt,
                "from_address": row.get("from", ""),
                "tx_hash": txh,
                "explorer_tx": f"{TRONSCAN_TX}{txh}",
                "timestamp": int((row.get("block_timestamp") or 0) / 1000),
        }
        attach_amount_fields(ev, raw=raw, decimals=decimals)
        if amount is not None:
            ev["amount_human"] = amount
        events.append(ev)

    # Native TRX transfers to address
    try:
        resp = sess.get(
            f"https://api.trongrid.io/v1/accounts/{address}/transactions",
            params={
                "limit": limit,
                "only_to": "true",
                "only_confirmed": "true",
                "order_by": "block_timestamp,desc",
            },
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        txs = resp.json().get("data") or []
    except Exception:
        logger.exception("TronGrid TRX failed for %s", address)
        txs = []

    for row in txs:
        raw = row.get("raw_data") or {}
        contracts = raw.get("contract") or []
        if not contracts:
            continue
        c0 = contracts[0]
        if c0.get("type") != "TransferContract":
            continue
        value = ((c0.get("parameter") or {}).get("value") or {})
        to_addr = value.get("to_address")
        # TronGrid may return hex; skip strict match if only_to already filtered
        amount_sun = int(value.get("amount") or 0)
        if amount_sun <= 0:
            continue
        txh = row.get("txID") or ""
        events.append(
            {
                "dedupe_key": f"tron:trx:{txh}:{address}",
                "chain": "TRON",
                "address": address,
                "wallet_label": wallet_label,
                "kind": "TRX IN",
                "symbol": "TRX",
                "amount_fmt": f"{amount_sun / 1_000_000:.6f}".rstrip("0").rstrip("."),
                "from_address": value.get("owner_address", ""),
                "tx_hash": txh,
                "explorer_tx": f"{TRONSCAN_TX}{txh}",
                "timestamp": int((row.get("block_timestamp") or 0) / 1000),
            }
        )

    return events
