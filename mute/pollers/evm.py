from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from mute.amount_filter import attach_amount_fields
from mute.pace import Pace, etherscan_wait

logger = logging.getLogger(__name__)

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"

EXPLORERS: dict[int, str] = {
    1: "https://etherscan.io/tx/",
    56: "https://bscscan.com/tx/",
    137: "https://polygonscan.com/tx/",
    42161: "https://arbiscan.io/tx/",
    10: "https://optimistic.etherscan.io/tx/",
    8453: "https://basescan.org/tx/",
    43114: "https://snowtrace.io/tx/",
    250: "https://ftmscan.com/tx/",
    59144: "https://lineascan.build/tx/",
    534352: "https://scrollscan.com/tx/",
    5000: "https://mantlescan.xyz/tx/",
    81457: "https://blastscan.io/tx/",
    25: "https://cronoscan.com/tx/",
    100: "https://gnosisscan.io/tx/",
    324: "https://era.zksync.network/tx/",
    1101: "https://zkevm.polygonscan.com/tx/",
}


def _fmt_amount(value: str, decimals: str | int) -> str:
    try:
        dec = int(decimals)
        raw = int(value)
        if dec <= 0:
            return str(raw)
        scaled = raw / (10**dec)
        if scaled >= 1_000_000:
            return f"{scaled:,.2f}"
        if scaled >= 1:
            return f"{scaled:,.6f}".rstrip("0").rstrip(".")
        return f"{scaled:.8f}".rstrip("0").rstrip(".")
    except Exception:
        return value


def fetch_evm_inbounds(
    *,
    address: str,
    wallet_label: str,
    chains: dict[int, str],
    api_key: str,
    alert_tokens: bool,
    alert_native: bool,
    request_delay_sec: float,
    workers: int = 6,
    pace: Pace | None = None,
    session: requests.Session | None = None,
    include_token_out: bool = False,
) -> list[dict[str, Any]]:
    if not api_key:
        logger.warning("ETHERSCAN_API_KEY missing — skipping EVM polls")
        return []

    pace = pace or Pace(request_delay_sec)
    addr = address.lower()
    chain_items = list(chains.items())
    workers = max(1, min(workers, len(chain_items) or 1))

    def _one_chain(item: tuple[int, str]) -> list[dict[str, Any]]:
        chain_id, chain_name = item
        # Per-thread session — requests.Session is not safely shared across threads
        sess = requests.Session()
        sess.trust_env = False
        sess.headers.update({"User-Agent": "MUTE-DWF-Monitor/0.1"})
        local: list[dict[str, Any]] = []

        if alert_tokens:
            rows = _etherscan(
                sess,
                api_key,
                chain_id,
                module="account",
                action="tokentx",
                address=address,
                page=1,
                offset=100,
                sort="desc",
            )
            for row in rows:
                to = (row.get("to") or "").lower()
                frm = (row.get("from") or "").lower()
                direction = None
                if to == addr:
                    direction = "in"
                elif include_token_out and frm == addr:
                    direction = "out"
                else:
                    continue
                txh = row.get("hash") or ""
                log_index = row.get("logIndex") or row.get("transactionIndex") or "0"
                ev = {
                        "dedupe_key": f"evm:{chain_id}:tok:{direction}:{txh}:{log_index}:{addr}",
                        "chain": chain_name,
                        "chain_id": chain_id,
                        "address": address,
                        "wallet_label": wallet_label,
                        "kind": "ERC-20 IN" if direction == "in" else "ERC-20 OUT",
                        "direction": direction,
                        "symbol": row.get("tokenSymbol") or "TOKEN",
                        "contract": (row.get("contractAddress") or "").lower(),
                        "amount_fmt": _fmt_amount(
                            row.get("value", "0"),
                            row.get("tokenDecimal", "18"),
                        ),
                        "from_address": row.get("from", ""),
                        "to_address": row.get("to", ""),
                        "tx_hash": txh,
                        "explorer_tx": f"{EXPLORERS.get(chain_id, '')}{txh}"
                        if chain_id in EXPLORERS
                        else "",
                        "timestamp": int(row.get("timeStamp") or 0),
                }
                attach_amount_fields(
                    ev, raw=row.get("value", "0"), decimals=row.get("tokenDecimal", "18")
                )
                local.append(ev)

        if alert_native:
            rows = _etherscan(
                sess,
                api_key,
                chain_id,
                module="account",
                action="txlist",
                address=address,
                page=1,
                offset=100,
                sort="desc",
            )
            for row in rows:
                if (row.get("to") or "").lower() != addr:
                    continue
                if row.get("isError") == "1":
                    continue
                value = row.get("value") or "0"
                if value == "0":
                    continue
                txh = row.get("hash") or ""
                ev = {
                        "dedupe_key": f"evm:{chain_id}:nat:{txh}:{addr}",
                        "chain": chain_name,
                        "chain_id": chain_id,
                        "address": address,
                        "wallet_label": wallet_label,
                        "kind": "NATIVE IN",
                        "symbol": _native_symbol(chain_id),
                        "amount_fmt": _fmt_amount(value, 18),
                        "from_address": row.get("from", ""),
                        "tx_hash": txh,
                        "explorer_tx": f"{EXPLORERS.get(chain_id, '')}{txh}"
                        if chain_id in EXPLORERS
                        else "",
                        "timestamp": int(row.get("timeStamp") or 0),
                }
                attach_amount_fields(ev, raw=value, decimals=18)
                local.append(ev)
        return local

    events: list[dict[str, Any]] = []
    if workers == 1 or len(chain_items) <= 1:
        for item in chain_items:
            events.extend(_one_chain(item))
        return events

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mute-evm") as pool:
        futs = [pool.submit(_one_chain, item) for item in chain_items]
        for fut in as_completed(futs):
            try:
                events.extend(fut.result())
            except Exception:
                logger.exception("EVM parallel chain failed for %s", address)
    return events


def _native_symbol(chain_id: int) -> str:
    return {
        1: "ETH",
        56: "BNB",
        137: "MATIC",
        42161: "ETH",
        10: "ETH",
        8453: "ETH",
        43114: "AVAX",
        250: "FTM",
        59144: "ETH",
        534352: "ETH",
        5000: "MNT",
        81457: "ETH",
    }.get(chain_id, "NATIVE")


def _etherscan(
    sess: requests.Session,
    api_key: str,
    chain_id: int,
    **params: Any,
) -> list[dict]:
    for _attempt in range(2):
        etherscan_wait()
        q = {"chainid": chain_id, "apikey": api_key, **params}
        try:
            resp = sess.get(ETHERSCAN_V2, params=q, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception(
                "Etherscan request failed chain=%s action=%s",
                chain_id,
                params.get("action"),
            )
            return []

        status = str(data.get("status", ""))
        result = data.get("result")
        if status == "1" and isinstance(result, list):
            return result
        if isinstance(result, str) and result and "rate limit" in result.lower():
            logger.warning("Etherscan rate limit on chain %s — retry", chain_id)
            time.sleep(2.0)
            continue
        if isinstance(result, str) and result not in (
            "No transactions found",
            "No token transfers found",
        ):
            logger.debug("Etherscan chain=%s: %s", chain_id, result[:200])
        return []
    return []
