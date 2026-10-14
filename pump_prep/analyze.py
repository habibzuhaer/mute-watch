from __future__ import annotations

import json
import logging
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from pump_prep.cex_labels import cex_name, is_major_symbol
from pump_prep.config import (
    CHAINS,
    EXPAND_TOP_N,
    EXPLORERS,
    LOOKBACK_DAYS,
    MCAP_CACHE,
    MCAP_MAX,
    MCAP_MIN,
    OUT_DIR,
    REQUEST_DELAY_SEC,
    SEEDS_FILE,
)
from pump_prep.etherscan import Pace, fetch_native_transfers, fetch_token_transfers
from pump_prep.seeds import Seed, load_seeds, seed_index

logger = logging.getLogger(__name__)


def _load_mcap_by_symbol(path: Path) -> dict[str, dict[str, Any]]:
    """symbol(upper) -> best row by mcap from cache JSON."""
    if not path.exists():
        logger.warning("mcap cache missing: %s", path)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    tokens = data.get("tokens") or []
    by_sym: dict[str, dict[str, Any]] = {}
    for t in tokens:
        sym = (t.get("symbol") or "").upper()
        if not sym:
            continue
        prev = by_sym.get(sym)
        if prev is None or (t.get("mcap") or 0) > (prev.get("mcap") or 0):
            by_sym[sym] = t
    return by_sym


def _in_window(ts: int, cutoff: int) -> bool:
    return ts >= cutoff


def _short(addr: str) -> str:
    if not addr:
        return ""
    if len(addr) < 12:
        return addr
    return f"{addr[:6]}…{addr[-4:]}"


def analyze(
    *,
    seeds_path: Path | None = None,
    lookback_days: int | None = None,
    expand: bool = True,
) -> dict[str, Any]:
    seeds_path = seeds_path or SEEDS_FILE
    lookback_days = lookback_days if lookback_days is not None else LOOKBACK_DAYS
    now = int(time.time())
    cutoff = now - lookback_days * 86400

    seeds = [s for s in load_seeds(seeds_path) if s.family == "evm"]
    by_addr = seed_index(seeds)
    mcap_by_sym = _load_mcap_by_symbol(MCAP_CACHE)

    sess = requests.Session()
    sess.trust_env = False
    sess.headers.update({"User-Agent": "MUTE-pump-prep/0.1"})
    pace = Pace(REQUEST_DELAY_SEC)

    all_transfers: list[dict[str, Any]] = []
    logger.info("Fetching transfers for %d EVM seeds × %d chains…", len(seeds), len(CHAINS))

    for seed in seeds:
        for chain_id, chain_name in CHAINS.items():
            toks = fetch_token_transfers(sess, seed.address, chain_id, pace=pace)
            nats = fetch_native_transfers(sess, seed.address, chain_id, pace=pace)
            for t in toks + nats:
                t["entity"] = seed.entity
                t["seed_label"] = seed.label
                t["chain"] = chain_name
                if _in_window(t["timestamp"], cutoff):
                    all_transfers.append(t)

    # Counterparty frequency for optional 1-hop expand
    cp_counts: Counter[str] = Counter()
    for t in all_transfers:
        seed_a = t["seed_address"]
        other = t["from"] if t["direction"] == "in" else t["to"]
        if other and other != seed_a and other not in by_addr and not cex_name(other):
            cp_counts[other] += 1

    expanded: list[str] = []
    if expand and EXPAND_TOP_N > 0:
        expanded = [a for a, _ in cp_counts.most_common(EXPAND_TOP_N)]
        logger.info("Expanding top %d counterparties…", len(expanded))
        for addr in expanded:
            for chain_id, chain_name in CHAINS.items():
                toks = fetch_token_transfers(sess, addr, chain_id, pace=pace)
                for t in toks:
                    t["entity"] = "expanded"
                    t["seed_label"] = f"1-hop {_short(addr)}"
                    t["chain"] = chain_name
                    t["expanded_from"] = addr
                    if _in_window(t["timestamp"], cutoff):
                        all_transfers.append(t)

    # --- Build edges ---
    edge_key_map: dict[tuple, dict[str, Any]] = {}
    for t in all_transfers:
        frm, to = t["from"], t["to"]
        if not frm or not to:
            continue
        key = (frm, to, t.get("contract") or t.get("symbol"), t["chain_id"])
        edge = edge_key_map.get(key)
        if edge is None:
            edge_key_map[key] = {
                "from": frm,
                "to": to,
                "contract": t.get("contract") or "",
                "symbol": t.get("symbol") or "",
                "chain_id": t["chain_id"],
                "chain": t.get("chain") or "",
                "count": 1,
                "last_seen": t["timestamp"],
                "entities": {t.get("entity") or ""},
            }
        else:
            edge["count"] += 1
            edge["last_seen"] = max(edge["last_seen"], t["timestamp"])
            edge["entities"].add(t.get("entity") or "")

    edges = []
    for e in edge_key_map.values():
        e["entities"] = sorted(x for x in e["entities"] if x)
        e["from_cex"] = cex_name(e["from"])
        e["to_cex"] = cex_name(e["to"])
        edges.append(e)
    edges.sort(key=lambda x: (-x["count"], -x["last_seen"]))

    # --- Address roles ---
    addr_meta: dict[str, dict[str, Any]] = {}

    def touch(addr: str, **kwargs: Any) -> None:
        if not addr:
            return
        m = addr_meta.setdefault(
            addr,
            {
                "address": addr,
                "roles": set(),
                "entities": set(),
                "tx_touch": 0,
                "symbols": set(),
                "cex": cex_name(addr),
            },
        )
        m["tx_touch"] += 1
        for k, v in kwargs.items():
            if k == "role" and v:
                m["roles"].add(v)
            elif k == "entity" and v:
                m["entities"].add(v)
            elif k == "symbol" and v:
                m["symbols"].add(v)

    for s in seeds:
        a = s.address.lower()
        touch(a, role="seed", entity=s.entity)
        addr_meta[a]["label"] = s.label
        addr_meta[a]["priority"] = s.priority

    for a in expanded:
        touch(a, role="expanded")

    for t in all_transfers:
        touch(t["from"], symbol=t.get("symbol"), entity=t.get("entity"))
        touch(t["to"], symbol=t.get("symbol"), entity=t.get("entity"))
        if cex_name(t["from"]):
            touch(t["from"], role="cex")
        if cex_name(t["to"]):
            touch(t["to"], role="cex")
        seed_a = t["seed_address"]
        other = t["from"] if t["direction"] == "in" else t["to"]
        if other != seed_a and not cex_name(other) and other not in by_addr:
            touch(other, role="counterparty", entity=t.get("entity"))

    # shared funder: native/stable out from same parent to many EOAs
    funder_children: dict[str, set[str]] = defaultdict(set)
    for t in all_transfers:
        if t["direction"] != "out":
            continue
        if t.get("symbol") not in ("NATIVE", "USDT", "USDC", "DAI", "ETH", "WETH", "BNB"):
            if not t.get("is_native") and not is_major_symbol(t.get("symbol")):
                continue
        parent = t["from"]
        child = t["to"]
        if cex_name(child) or child in by_addr:
            continue
        funder_children[parent].add(child)

    shared_funders = {p: kids for p, kids in funder_children.items() if len(kids) >= 3}
    for p, kids in shared_funders.items():
        touch(p, role="shared_funder")
        for c in kids:
            touch(c, role="fresh")

    # repeat counterparties across seed entities
    cp_entities: dict[str, set[str]] = defaultdict(set)
    for t in all_transfers:
        if t.get("entity") in ("expanded", None, ""):
            continue
        other = t["from"] if t["direction"] == "in" else t["to"]
        if other in by_addr or cex_name(other):
            continue
        cp_entities[other].add(t["entity"])

    repeat_cps = {a: ents for a, ents in cp_entities.items() if len(ents) >= 2}
    for a in repeat_cps:
        touch(a, role="repeat_counterparty")

    addresses = []
    for a, m in addr_meta.items():
        addresses.append(
            {
                "address": a,
                "short": _short(a),
                "label": m.get("label") or (m["cex"] if m.get("cex") else ""),
                "roles": sorted(m["roles"]),
                "entities": sorted(m["entities"]),
                "tx_touch": m["tx_touch"],
                "symbols": sorted(m["symbols"])[:12],
                "cex": m.get("cex"),
                "explorer": f"{EXPLORERS.get(1, 'https://etherscan.io')}/address/{a}",
            }
        )
    addresses.sort(key=lambda x: (-x["tx_touch"], x["address"]))

    # --- Signals ---
    signals: list[dict[str, Any]] = []

    for t in all_transfers:
        if t.get("is_native") or t.get("symbol") == "NATIVE":
            continue
        sym = t.get("symbol") or ""
        mcap_row = mcap_by_sym.get(sym.upper())
        mcap = mcap_row.get("mcap") if mcap_row else None
        in_band = mcap is not None and MCAP_MIN <= mcap <= MCAP_MAX
        obscure = not is_major_symbol(sym)

        # new_token_in
        if t["direction"] == "in" and obscure and t["seed_address"] in by_addr:
            if in_band or mcap is None:
                signals.append(
                    {
                        "type": "new_token_in",
                        "entity": t.get("entity"),
                        "seed": t["seed_address"],
                        "seed_label": t.get("seed_label"),
                        "counterparty": t["from"],
                        "symbol": sym,
                        "contract": t.get("contract"),
                        "mcap": mcap,
                        "chain": t.get("chain"),
                        "chain_id": t["chain_id"],
                        "hash": t.get("hash"),
                        "timestamp": t["timestamp"],
                        "note": "inbound obscure/mid-cap token to seed",
                    }
                )

        # cex_deposit
        if t["direction"] == "out" and obscure:
            dest_cex = cex_name(t["to"])
            if dest_cex and (t["seed_address"] in by_addr or t.get("entity") == "expanded"):
                signals.append(
                    {
                        "type": "cex_deposit",
                        "entity": t.get("entity"),
                        "seed": t["seed_address"],
                        "seed_label": t.get("seed_label"),
                        "counterparty": t["to"],
                        "cex": dest_cex,
                        "symbol": sym,
                        "contract": t.get("contract"),
                        "mcap": mcap,
                        "chain": t.get("chain"),
                        "chain_id": t["chain_id"],
                        "hash": t.get("hash"),
                        "timestamp": t["timestamp"],
                        "note": f"token out to {dest_cex}",
                    }
                )

    for parent, kids in shared_funders.items():
        signals.append(
            {
                "type": "shared_funder",
                "entity": ",".join(sorted(addr_meta.get(parent, {}).get("entities") or [])),
                "seed": parent,
                "seed_label": _short(parent),
                "counterparty": f"{len(kids)} children",
                "children": sorted(kids)[:20],
                "symbol": "gas/stable",
                "contract": "",
                "mcap": None,
                "chain": "multi",
                "chain_id": 0,
                "hash": "",
                "timestamp": now,
                "note": f"funded {len(kids)} EOAs",
            }
        )

    for a, ents in repeat_cps.items():
        signals.append(
            {
                "type": "repeat_counterparty",
                "entity": ",".join(sorted(ents)),
                "seed": a,
                "seed_label": _short(a),
                "counterparty": a,
                "symbol": "",
                "contract": "",
                "mcap": None,
                "chain": "multi",
                "chain_id": 0,
                "hash": "",
                "timestamp": now,
                "note": f"seen with entities: {', '.join(sorted(ents))}",
            }
        )

    # de-dupe signals loosely
    seen_sig: set[str] = set()
    uniq_signals = []
    for s in signals:
        key = f"{s['type']}:{s.get('seed')}:{s.get('symbol')}:{s.get('counterparty')}:{s.get('hash')}"
        if key in seen_sig:
            continue
        seen_sig.add(key)
        uniq_signals.append(s)
    uniq_signals.sort(key=lambda x: (-(x.get("timestamp") or 0), x["type"]))

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": lookback_days,
        "seeds_file": str(seeds_path),
        "seed_count": len(seeds),
        "transfer_count": len(all_transfers),
        "expanded_count": len(expanded),
        "mcap_cache": str(MCAP_CACHE) if MCAP_CACHE.exists() else None,
        "signals": uniq_signals,
        "addresses": addresses,
        "edges": edges[:500],
        "stats": {
            "signals_by_type": dict(Counter(s["type"] for s in uniq_signals)),
            "addresses": len(addresses),
            "edges": len(edges),
        },
    }

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "pump_prep_data.json").write_text(
        json.dumps(result, indent=2, default=list),
        encoding="utf-8",
    )
    return result
