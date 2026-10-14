"""Solana transfer ingest — max: SOL + SPL IN/OUT with counterparties (Helius/RPC)."""

from __future__ import annotations

import logging
from typing import Any

import requests

from intel.config import HELIUS_API_KEY, REQUEST_DELAY_SEC, SOLANA_RPC_URL, TX_LIMIT_SOL
from intel.normalize import norm
from intel.store import add_edge, enqueue, upsert_address

logger = logging.getLogger(__name__)

SOLSCAN = "https://solscan.io/tx/"


def _rpc_url() -> str:
    if HELIUS_API_KEY and "helius" not in SOLANA_RPC_URL:
        return f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    return SOLANA_RPC_URL


def _rpc(sess: requests.Session, method: str, params: list[Any]) -> Any:
    import time

    time.sleep(REQUEST_DELAY_SEC)
    try:
        r = sess.post(
            _rpc_url(),
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            logger.warning("sol rpc %s: %s", method, data["error"])
            return None
        return data.get("result")
    except Exception:
        logger.exception("sol rpc %s", method)
        return None


def _account_keys(parsed: dict) -> list[str]:
    msg = (parsed.get("transaction") or {}).get("message") or {}
    keys = msg.get("accountKeys") or []
    out = []
    for k in keys:
        if isinstance(k, str):
            out.append(k)
        elif isinstance(k, dict):
            out.append(k.get("pubkey") or "")
    return out


def _tok_owner(b: dict) -> str:
    return b.get("owner") or ""


def _tok_mint(b: dict) -> str:
    return b.get("mint") or ""


def _tok_amount(b: dict) -> float:
    ui = b.get("uiTokenAmount") or {}
    if ui.get("uiAmount") is not None:
        try:
            return float(ui["uiAmount"])
        except Exception:
            pass
    try:
        return float(ui.get("uiAmountString") or 0)
    except Exception:
        return 0.0


def parse_transaction(parsed: dict, focus: str) -> list[dict[str, Any]]:
    """Extract SOL + SPL transfers involving focus; try to resolve counterparty."""
    if not parsed:
        return []
    meta = parsed.get("meta") or {}
    if meta.get("err"):
        return []
    sig = ""
    try:
        sig = ((parsed.get("transaction") or {}).get("signatures") or [""])[0]
    except Exception:
        pass
    ts = int(parsed.get("blockTime") or 0)
    keys = _account_keys(parsed)
    edges: list[dict[str, Any]] = []

    # Native SOL deltas per account
    pre_b = meta.get("preBalances") or []
    post_b = meta.get("postBalances") or []
    deltas: dict[str, int] = {}
    for i, k in enumerate(keys):
        if i >= len(pre_b) or i >= len(post_b):
            break
        d = int(post_b[i]) - int(pre_b[i])
        if d != 0:
            deltas[k] = d

    focus_d = deltas.get(focus, 0)
    if focus_d != 0:
        # counterparty: largest opposite delta
        opp = -1 if focus_d > 0 else 1
        cands = [(a, d) for a, d in deltas.items() if a != focus and d * opp > 0]
        cands.sort(key=lambda x: -abs(x[1]))
        other = cands[0][0] if cands else ""
        if other and norm("solana", other):
            frm, to = (other, focus) if focus_d > 0 else (focus, other)
            edges.append(
                {
                    "chain": "solana",
                    "from": frm,
                    "to": to,
                    "direction": "in" if to == focus else "out",
                    "symbol": "SOL",
                    "token": "native",
                    "amount": abs(focus_d) / 1_000_000_000,
                    "tx": sig,
                    "timestamp": ts,
                    "source": "sol_ingest",
                }
            )

    # SPL: build owner+mint → amount maps
    def bal_map(rows: list) -> dict[tuple[str, str], float]:
        m: dict[tuple[str, str], float] = {}
        for b in rows or []:
            o, mint = _tok_owner(b), _tok_mint(b)
            if o and mint:
                m[(o, mint)] = _tok_amount(b)
        return m

    pre = bal_map(meta.get("preTokenBalances") or [])
    post = bal_map(meta.get("postTokenBalances") or [])
    keys_set = set(pre) | set(post)
    # per mint: who gained / lost
    by_mint: dict[str, dict[str, float]] = {}
    for (owner, mint) in keys_set:
        d = post.get((owner, mint), 0.0) - pre.get((owner, mint), 0.0)
        if abs(d) < 1e-12:
            continue
        by_mint.setdefault(mint, {})[owner] = d

    for mint, owners in by_mint.items():
        focus_delta = owners.get(focus)
        if focus_delta is None or abs(focus_delta) < 1e-12:
            continue
        # counterparty with opposite sign, max abs
        cands = [(o, d) for o, d in owners.items() if o != focus and d * focus_delta < 0]
        cands.sort(key=lambda x: -abs(x[1]))
        other = cands[0][0] if cands else ""
        if not other or not norm("solana", other):
            # still record vs system if fee-only; skip orphan
            continue
        frm, to = (other, focus) if focus_delta > 0 else (focus, other)
        sym = mint[:8] if mint else "SPL"
        edges.append(
            {
                "chain": "solana",
                "from": frm,
                "to": to,
                "direction": "in" if to == focus else "out",
                "symbol": sym,
                "token": mint,
                "mint": mint,
                "amount": abs(focus_delta),
                "tx": sig,
                "timestamp": ts,
                "source": "sol_ingest",
            }
        )
    return edges


def fetch_address_transfers(
    address: str,
    *,
    limit: int | None = None,
    sess: requests.Session | None = None,
) -> list[dict[str, Any]]:
    sess = sess or requests.Session()
    addr = norm("solana", address)
    if not addr:
        return []
    limit = limit or TX_LIMIT_SOL
    sigs = _rpc(sess, "getSignaturesForAddress", [addr, {"limit": limit}])
    if not isinstance(sigs, list):
        return []
    edges: list[dict[str, Any]] = []
    for item in sigs:
        if item.get("err"):
            continue
        sig = item.get("signature")
        if not sig:
            continue
        parsed = _rpc(
            sess,
            "getTransaction",
            [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        )
        if not parsed:
            continue
        edges.extend(parse_transaction(parsed, addr))
    return edges


def ingest_seed(
    address: str,
    state: dict[str, Any],
    *,
    hop: int = 0,
    reason: str = "",
    max_neighbors: int = 25,
    sess: requests.Session | None = None,
) -> dict[str, Any]:
    from mute.config import solana_rpc_usable

    if not solana_rpc_usable(HELIUS_API_KEY, SOLANA_RPC_URL):
        logger.info("Solana ingest skip — public RPC (set HELIUS_API_KEY)")
        return {
            "chain": "solana",
            "address": address,
            "txs": 0,
            "edges_new": 0,
            "neighbors": 0,
            "enqueued": 0,
            "rpc": "skipped_public",
        }
    sess = sess or requests.Session()
    txs = fetch_address_transfers(address, sess=sess)
    written = 0
    neighbors: set[str] = set()
    addr = norm("solana", address)
    for tx in txs:
        tx["seed"] = addr
        tx["hop"] = hop
        if add_edge(tx):
            written += 1
        other = tx["to"] if tx["from"] == addr else tx["from"]
        if other:
            neighbors.add(other)

    upsert_address("solana", addr, tags=["seed", "solana"], meta={"reason": reason, "hop": hop})

    enq = 0
    if hop < 2:
        for n in list(neighbors)[:max_neighbors]:
            if enqueue(
                state,
                "solana",
                n,
                reason=f"nbr:{reason or addr[:8]}",
                hop=hop + 1,
                priority=5,
            ):
                enq += 1

    return {
        "chain": "solana",
        "address": addr,
        "txs": len(txs),
        "edges_new": written,
        "neighbors": len(neighbors),
        "enqueued": enq,
        "rpc": "helius" if HELIUS_API_KEY else "public",
    }
