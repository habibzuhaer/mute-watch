"""Adapter: import legacy MUTE data/graph into intel store + seed queues."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from intel.config import GRAPH_DIR
from intel.normalize import norm, storage_chain
from intel.store import add_edge, enqueue, flush_addresses, upsert_address

logger = logging.getLogger(__name__)


def import_graph_edges(*, limit: int = 8000, state: dict[str, Any] | None = None) -> dict[str, Any]:
    edge_path = GRAPH_DIR / "edges.jsonl"
    if not edge_path.exists():
        return {"ok": False, "error": "no graph edges", "written": 0}

    written = 0
    seeds_bnb = 0
    seeds_evm = 0
    # read tail
    lines: list[str] = []
    with edge_path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        block = min(size, 4_000_000)
        f.seek(max(0, size - block))
        data = f.read().decode("utf-8", errors="replace")
    lines = [ln for ln in data.splitlines() if ln.strip()][-limit:]

    for ln in lines:
        try:
            e = json.loads(ln)
        except Exception:
            continue
        cid = e.get("chain_id")
        ch = storage_chain("", cid) if cid else "ethereum"
        row = {
            "chain": ch,
            "chain_id": cid,
            "from": e.get("from_addr") or e.get("from"),
            "to": e.get("to_addr") or e.get("to"),
            "direction": e.get("direction") or "out",
            "symbol": e.get("symbol") or "",
            "token": e.get("contract") or e.get("token_id") or "",
            "tx": e.get("hash") or "",
            "timestamp": int(e.get("timestamp") or 0),
            "source": "evm_adapter",
        }
        if add_edge(row):
            written += 1
        if state is not None and cid == 56:
            for side in (row["from"], row["to"]):
                if enqueue(state, "bnb", side, reason="graph56", hop=0, priority=3):
                    seeds_bnb += 1

    # addresses.jsonl labels
    addr_path = GRAPH_DIR / "addresses.jsonl"
# Limit labeled import size for bootstrap speed (refine later)
    labeled = 0
    if addr_path.exists():
        for ln in addr_path.open(encoding="utf-8", errors="replace"):
            try:
                a = json.loads(ln)
            except Exception:
                continue
            ad = norm("evm", a.get("address"))
            if not ad:
                continue
            upsert_address(
                "ethereum",
                ad,
                tags=["legacy", a.get("role") or ""],
                role=a.get("role"),
                entity=a.get("entity"),
                label=a.get("label"),
            )
            labeled += 1
            if labeled > 3000:
                break
            if state is not None and (a.get("role") or "") in {"watch", "mm", "fund", "seed", "deployer"}:
                enqueue(state, "bnb", ad, reason="legacy_label", hop=0, priority=8)
                seeds_evm += 1

    # Solana seeds from watchlists if present
    seeds_sol = 0
    for wl in (
        Path(__file__).resolve().parents[2] / "addresses" / "dwf_labs.json",
        Path(__file__).resolve().parents[2] / "addresses" / "pump_prep_watchlist.json",
    ):
        if not wl.exists() or state is None:
            continue
        try:
            data = json.loads(wl.read_text(encoding="utf-8"))
        except Exception:
            continue
        wallets = data if isinstance(data, list) else data.get("wallets") or data.get("addresses") or []
        for w in wallets:
            if isinstance(w, str):
                addr, family = w, ""
            else:
                addr = w.get("address") or ""
                family = (w.get("family") or w.get("chain") or "").lower()
            if family in {"solana", "sol"} or (
                addr
                and not addr.startswith("0x")
                and not addr.startswith("T")  # Tron
                and len(addr) >= 32
                and family in {"", "solana", "sol"}
            ):
                if family in {"tron", "trx"}:
                    continue
                if enqueue(state, "solana", addr, reason="watchlist", hop=0, priority=10):
                    seeds_sol += 1
                    upsert_address("solana", addr, tags=["watchlist", "seed"])

    # profit seeds from rozvidka if any
    profit = Path(__file__).resolve().parents[2] / "data" / "rozvidka" / "db" / "profit_seeds.json"
    if profit.exists() and state is not None:
        try:
            seeds = json.loads(profit.read_text(encoding="utf-8")).get("seeds") or []
            for s in seeds[:40]:
                ad = s.get("address")
                if enqueue(state, "bnb", ad, reason="profit", hop=0, priority=9):
                    seeds_bnb += 1
        except Exception:
            logger.exception("profit seed import")

    flush_addresses()
    return {
        "ok": True,
        "written": written,
        "labeled": labeled,
        "enqueued_bnb": seeds_bnb,
        "enqueued_sol": seeds_sol,
        "enqueued_label": seeds_evm,
    }
