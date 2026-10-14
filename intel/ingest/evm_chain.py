"""Generic EVM ingest (Ethereum=1, BNB=56, …) via Etherscan V2."""

from __future__ import annotations

import logging
from typing import Any

import requests

from intel.config import ETHERSCAN_API_KEY, ETHERSCAN_V2, REQUEST_DELAY_SEC, TX_OFFSET_EVM
from intel.normalize import chain_id_to_name, norm, storage_chain
from intel.store import add_edge, enqueue, upsert_address
from mute.pace import etherscan_wait

logger = logging.getLogger(__name__)

NATIVE = {1: "ETH", 56: "BNB", 42161: "ETH", 8453: "ETH"}


class Pace:
    def __init__(self, delay: float) -> None:
        import time

        self.delay = delay
        self._last = 0.0
        self._time = time

    def wait(self) -> None:
        now = self._time.monotonic()
        gap = self.delay - (now - self._last)
        if gap > 0:
            self._time.sleep(gap)
        self._last = self._time.monotonic()


def _es(sess: requests.Session, pace: Pace, chain_id: int, **params: Any) -> list[dict]:
    if not ETHERSCAN_API_KEY:
        logger.warning("ETHERSCAN_API_KEY missing")
        return []
    for _attempt in range(2):
        etherscan_wait()
        q = {"chainid": chain_id, "apikey": ETHERSCAN_API_KEY, **params}
        try:
            r = sess.get(ETHERSCAN_V2, params=q, timeout=45)
            r.raise_for_status()
            data = r.json()
        except Exception:
            logger.exception("etherscan fail chain=%s", chain_id)
            return []
        result = data.get("result")
        if str(data.get("status")) == "1" and isinstance(result, list):
            return result
        if isinstance(result, str) and "rate limit" in result.lower():
            logger.warning("rate limit chain=%s — retry", chain_id)
            import time

            time.sleep(2.0)
            continue
        return []
    return []


def fetch_address_transfers(
    address: str,
    chain_id: int,
    *,
    sess: requests.Session | None = None,
    pace: Pace | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    sess = sess or requests.Session()
    pace = pace or Pace(REQUEST_DELAY_SEC)
    addr = norm("evm", address)
    if not addr:
        return []
    offset = offset or TX_OFFSET_EVM
    chain_name = storage_chain(chain_id_to_name(chain_id), chain_id)
    native_sym = NATIVE.get(chain_id, "ETH")
    out: list[dict[str, Any]] = []

    for action, is_native in (("tokentx", False), ("txlist", True)):
        rows = _es(
            sess,
            pace,
            chain_id,
            module="account",
            action=action,
            address=addr,
            page=1,
            offset=offset,
            sort="desc",
        )
        for row in rows:
            if is_native and (row.get("isError") == "1" or (row.get("value") or "0") == "0"):
                continue
            frm = norm("evm", row.get("from"))
            to = norm("evm", row.get("to"))
            if addr not in {frm, to}:
                continue
            direction = "in" if to == addr else "out"
            if is_native:
                dec, raw, sym, contract = 18, row.get("value") or "0", native_sym, ""
            else:
                dec = int(row.get("tokenDecimal") or 18)
                raw = row.get("value") or "0"
                sym = row.get("tokenSymbol") or "TOKEN"
                contract = (row.get("contractAddress") or "").lower()
            try:
                amt = int(raw) / (10**dec) if raw else None
            except Exception:
                amt = None
            out.append(
                {
                    "chain": chain_name,
                    "chain_id": chain_id,
                    "from": frm,
                    "to": to,
                    "direction": direction,
                    "symbol": sym,
                    "token": contract or sym,
                    "contract": contract,
                    "amount": amt,
                    "tx": row.get("hash") or "",
                    "timestamp": int(row.get("timeStamp") or 0),
                    "source": f"evm_{chain_id}",
                }
            )
    return out


def ingest_seed(
    address: str,
    state: dict[str, Any],
    *,
    chain_id: int = 1,
    hop: int = 0,
    reason: str = "",
    max_neighbors: int = 25,
    sess: requests.Session | None = None,
    pace: Pace | None = None,
) -> dict[str, Any]:
    sess = sess or requests.Session()
    pace = pace or Pace(REQUEST_DELAY_SEC)
    chain_name = storage_chain(chain_id_to_name(chain_id), chain_id)
    txs = fetch_address_transfers(address, chain_id, sess=sess, pace=pace)
    written = 0
    neighbors: set[str] = set()
    addr = norm("evm", address)
    for tx in txs:
        tx["seed"] = addr
        tx["hop"] = hop
        if add_edge(tx):
            written += 1
        other = tx["to"] if tx["from"] == addr else tx["from"]
        if other:
            neighbors.add(other)

    upsert_address(
        chain_name,
        addr,
        tags=["seed", chain_name, "hub" if "hub" in reason else "seen"],
        meta={"reason": reason, "hop": hop},
    )

    enq = 0
    if hop < 2:
        for n in list(neighbors)[:max_neighbors]:
            if enqueue(
                state,
                chain_name if chain_name != "bnb" else "bnb",
                n,
                reason=f"nbr:{reason or addr[:10]}",
                hop=hop + 1,
                priority=5,
            ):
                enq += 1

    return {
        "chain": chain_name,
        "chain_id": chain_id,
        "address": addr,
        "txs": len(txs),
        "edges_new": written,
        "neighbors": len(neighbors),
        "enqueued": enq,
    }
