"""Profit seeds from local history, then Etherscan expand from winners."""

from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from rozvidka.config import DATA_DIR

logger = logging.getLogger(__name__)

PROFIT_DB = DATA_DIR / "db" / "profit_seeds.json"
EXPAND_LOG = DATA_DIR / "db" / "expand_log.jsonl"

ZERO = "0x0000000000000000000000000000000000000000"
DEAD = "0x000000000000000000000000000000000000dead"

# days before ATH still counts as "early"
EARLY_DAYS = float(os.getenv("ROZVIDKA_EARLY_DAYS", "30"))
EXPAND_SEEDS = int(os.getenv("ROZVIDKA_EXPAND_SEEDS", "10"))
EXPAND_OFFSET = int(os.getenv("ROZVIDKA_EXPAND_OFFSET", "40"))
EXPAND_CHAINS = [
    int(x.strip())
    for x in os.getenv("ROZVIDKA_EXPAND_CHAINS", "1,56,42161,8453").split(",")
    if x.strip().isdigit()
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short(addr: str | None) -> str:
    a = (addr or "").strip().lower()
    if len(a) < 10:
        return a
    return a[:4] + a[-4:]


def _norm(addr: Any) -> str:
    a = (addr or "").strip().lower()
    if a.startswith("0x") and len(a) == 42 and a not in {ZERO, DEAD}:
        return a
    return ""


def _parse_ath_ts(ath_date: Any) -> int | None:
    if ath_date is None:
        return None
    if isinstance(ath_date, (int, float)) and ath_date > 1_000_000:
        return int(ath_date)
    s = str(ath_date).strip()
    if not s:
        return None
    try:
        if s.isdigit():
            return int(s)
        # ISO
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return int(datetime.fromisoformat(s).timestamp())
    except Exception:
        return None


def find_profit_seeds(*, edge_limit: int | None = None) -> dict[str, Any]:
    """Phase A: early token touches before ATH → profit proxy ranking."""
    from pump_prep import graph_store as gs
    from pump_prep.labels import load_known

    known = load_known()
    tokens: dict[str, dict[str, Any]] = {}
    by_contract: dict[str, str] = {}
    by_symbol: dict[str, str] = {}

    for t in gs.read_jsonl(gs.TOKEN_FILE):
        tid = str(t.get("id") or t.get("symbol") or "")
        if not tid:
            continue
        ath_ts = _parse_ath_ts(t.get("ath_date"))
        pumped = bool(t.get("had_pump")) or (
            t.get("ath_chg") is not None and float(t.get("ath_chg") or 0) <= -50
        )
        if not pumped or not ath_ts:
            continue
        tokens[tid] = {**t, "_ath_ts": ath_ts}
        c = (t.get("contract") or "").lower()
        if c.startswith("0x"):
            by_contract[c] = tid
        sym = (t.get("symbol") or "").lower()
        if sym:
            by_symbol[sym] = tid

    # addr -> stats
    early: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "early_tokens": set(),
            "early_n": 0,
            "late_tokens": set(),
            "touches": 0,
            "in_n": 0,
            "out_n": 0,
            "cex_out": 0,
            "first_ts": None,
            "last_ts": None,
            "hashes": [],
        }
    )
    early_window = int(EARLY_DAYS * 86400)

    edges_iter = (
        gs.read_jsonl(gs.EDGE_FILE)
        if edge_limit is None
        else gs.read_jsonl_tail(gs.EDGE_FILE, edge_limit)
    )
    edges_used = 0
    for edge in edges_iter:
        edges_used += 1
        tid = str(edge.get("token_id") or "")
        if not tid:
            c = (edge.get("contract") or "").lower()
            tid = by_contract.get(c) or by_symbol.get((edge.get("symbol") or "").lower()) or ""
        tok = tokens.get(tid)
        if not tok:
            # still count non-pump token_itself lightly? skip for profit
            if not edge.get("is_token_itself"):
                continue
            continue

        ath_ts = int(tok["_ath_ts"])
        ts = int(edge.get("timestamp") or 0)
        if not ts:
            continue

        frm = _norm(edge.get("from_addr") or edge.get("from"))
        to = _norm(edge.get("to_addr") or edge.get("to"))
        direction = (edge.get("direction") or "out").lower()
        is_self = bool(edge.get("is_token_itself"))

        # beneficiary sides: who received the token before ATH (IN to them / OUT from deployer)
        candidates: list[tuple[str, str]] = []
        if is_self or tid:
            if to:
                candidates.append((to, "recv"))
            if frm and direction == "out":
                # sender of token before ATH may be distributor; receiver is more "profit"
                pass
            if frm and direction == "in":
                candidates.append((frm, "via_in"))

        delta = ath_ts - ts
        before_ath = ts > 0 and ts < ath_ts
        # early = before ATH; prefer window near ATH for ranking weight
        in_window = before_ath and (delta <= early_window or is_self)

        for addr, how in candidates:
            st = early[addr]
            st["touches"] += 1
            if direction == "in" or how == "recv":
                st["in_n"] += 1
            else:
                st["out_n"] += 1
            if before_ath:
                st["early_tokens"].add(tid)
                st["early_n"] += 1 if in_window else 0
                if in_window and len(st["hashes"]) < 8:
                    st["hashes"].append(edge.get("hash") or "")
                # count at least once even outside window
                if not in_window:
                    st["early_n"] = max(st["early_n"], 1)
            else:
                st["late_tokens"].add(tid)
            if st["first_ts"] is None or ts < st["first_ts"]:
                st["first_ts"] = ts
            if st["last_ts"] is None or ts > st["last_ts"]:
                st["last_ts"] = ts

            # CEX exit after early = stronger profit signal (sold)
            meta = known.get(to if direction == "out" else frm) or {}
            other = to if direction == "out" else frm
            om = known.get(other) or {}
            if (om.get("role") or "").lower() == "cex" and before_ath is False and tid in st["early_tokens"]:
                st["cex_out"] += 1

    # also boost from high-score non-cex signals
    signal_boost: dict[str, int] = defaultdict(int)
    for s in gs.read_jsonl(gs.SIGNAL_FILE):
        if (s.get("tier") or "") not in {"actionable", "watch"}:
            continue
        if (s.get("match_role") or "").lower() in {"cex", "bridge"}:
            continue
        for key in ("counterparty", "deployer"):
            a = _norm(s.get(key))
            if a:
                signal_boost[a] += int(s.get("score") or 0) // 10

    # addresses.jsonl coverage
    labeled_extra = 0
    for row in gs.read_jsonl(gs.ADDR_FILE):
        a = _norm(row.get("address"))
        if not a:
            continue
        if a not in early:
            early[a]  # create empty
            labeled_extra += 1
        st = early[a]
        if row.get("role"):
            st.setdefault("roles", set()).add(str(row.get("role")).lower())
        if row.get("symbol") and tokens.get(str(row.get("token_id") or "")):
            # linked to a pump token as labeled actor
            tid = str(row.get("token_id") or "")
            if tid in tokens and "deployer" in str(row.get("role") or "").lower():
                st["early_tokens"].add(tid)

    seeds: list[dict[str, Any]] = []
    for addr, st in early.items():
        meta = known.get(addr) or {}
        role = (meta.get("role") or "").lower()
        if role in {"cex", "bridge"}:
            continue
        early_toks = sorted(st["early_tokens"])
        late_toks = sorted(st["late_tokens"])
        multi = len(early_toks)
        if multi < 1 and signal_boost.get(addr, 0) < 5 and st["touches"] < 3:
            continue
        score = min(
            100,
            multi * 18
            + min(20, st["early_n"] * 2)
            + min(15, st["cex_out"] * 5)
            + min(20, signal_boost.get(addr, 0))
            + (8 if multi >= 3 else 0)
            + (5 if role in {"mm", "fund", "seed", "watch", "accused"} else 0),
        )
        if score < 18 and multi < 2:
            continue
        tags = {"profit_proxy", "early_beneficiary"}
        if multi >= 2:
            tags.add("multi_pump")
        if st["cex_out"]:
            tags.add("cex_exit")
        if role:
            tags.add(role)
        for r in st.get("roles") or []:
            tags.add(r)

        seeds.append(
            {
                "address": addr,
                "short": _short(addr),
                "score": score,
                "early_n": st["early_n"],
                "early_tokens": early_toks[:20],
                "early_token_n": multi,
                "late_tokens": late_toks[:10],
                "touches": st["touches"],
                "in_n": st["in_n"],
                "out_n": st["out_n"],
                "cex_out": st["cex_out"],
                "signal_boost": signal_boost.get(addr, 0),
                "entity": meta.get("entity"),
                "label": meta.get("label"),
                "role": role or None,
                "tags": sorted(tags),
                "first_ts": st["first_ts"],
                "last_ts": st["last_ts"],
                "sample_hashes": [h for h in st["hashes"] if h][:5],
            }
        )

    seeds.sort(key=lambda x: (-int(x["score"]), -int(x["early_token_n"]), -int(x["early_n"])))

    out = {
        "built_at": _now(),
        "params": {"early_days": EARLY_DAYS, "edges_used": edges_used, "pump_tokens": len(tokens)},
        "stats": {
            "candidates": len(early),
            "seeds": len(seeds),
            "multi_pump": sum(1 for s in seeds if s["early_token_n"] >= 2),
            "labeled_scanned": labeled_extra,
            "top_score": seeds[0]["score"] if seeds else 0,
        },
        "seeds": seeds,
    }
    PROFIT_DB.parent.mkdir(parents=True, exist_ok=True)
    PROFIT_DB.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return out


def expand_profit_seeds(
    seeds: list[dict[str, Any]] | None = None,
    *,
    limit: int | None = None,
    enqueue_graph: bool = True,
) -> dict[str, Any]:
    """Phase B: pull live transfer history for top profit addresses → edges.jsonl."""
    from pump_prep.config import ETHERSCAN_API_KEY, REQUEST_DELAY_SEC
    from pump_prep.etherscan import Pace, fetch_native_transfers, fetch_token_transfers
    from pump_prep import graph_store as gs
    from pump_prep.labels import load_known

    if not ETHERSCAN_API_KEY:
        return {"ok": False, "error": "ETHERSCAN_API_KEY missing", "expanded": 0}

    if seeds is None:
        if PROFIT_DB.exists():
            seeds = json.loads(PROFIT_DB.read_text(encoding="utf-8")).get("seeds") or []
        else:
            seeds = (find_profit_seeds().get("seeds") or [])

    limit = EXPAND_SEEDS if limit is None else limit
    known = load_known()
    picked: list[dict[str, Any]] = []
    for s in seeds:
        a = _norm(s.get("address"))
        if not a:
            continue
        role = (s.get("role") or (known.get(a) or {}).get("role") or "").lower()
        if role in {"cex", "bridge"}:
            continue
        picked.append(s)
        if len(picked) >= limit:
            break

    sess = requests.Session()
    pace = Pace(REQUEST_DELAY_SEC)
    state = gs.load_state() if enqueue_graph else {}

    expanded = []
    new_edges = 0
    new_addrs: set[str] = set()
    t0 = time.time()

    for s in picked:
        addr = s["address"]
        per = {
            "address": addr,
            "short": s.get("short") or _short(addr),
            "score": s.get("score"),
            "chains": {},
            "edges": 0,
            "neighbors": [],
        }
        neighbors: Counter[str] = Counter()
        for chain_id in EXPAND_CHAINS:
            try:
                txs = fetch_token_transfers(
                    sess, addr, chain_id, pace=pace, offset=EXPAND_OFFSET
                )
                native = fetch_native_transfers(
                    sess, addr, chain_id, pace=pace, offset=min(20, EXPAND_OFFSET)
                )
            except Exception as exc:
                logger.warning("expand %s chain %s: %s", _short(addr), chain_id, exc)
                per["chains"][str(chain_id)] = {"error": str(exc)}
                continue
            rows = list(txs) + list(native)
            per["chains"][str(chain_id)] = {"txs": len(rows)}
            for tx in rows:
                frm = _norm(tx.get("from"))
                to = _norm(tx.get("to"))
                if not frm or not to:
                    continue
                other = to if frm == addr else frm
                if other:
                    neighbors[other] += 1
                    new_addrs.add(other)
                sym = (tx.get("symbol") or "TOKEN").lower()
                is_native = bool(tx.get("is_native")) or sym in {"native", "eth", "bnb", "matic"}
                edge = {
                    "from_addr": frm,
                    "to_addr": to,
                    "direction": tx.get("direction") or ("out" if frm == addr else "in"),
                    "symbol": "eth" if is_native and sym == "native" else tx.get("symbol"),
                    "token_symbol": tx.get("symbol"),
                    "token_id": "",
                    "contract": tx.get("contract") or "",
                    "is_token_itself": False,
                    "chain_id": chain_id,
                    "hash": tx.get("hash"),
                    "timestamp": int(tx.get("timestamp") or 0),
                    "deployer": "",
                    "expanded_from": addr,
                    "expand_reason": "profit_seed",
                    "value_raw": tx.get("value_raw"),
                    "decimals": tx.get("decimals"),
                }
                gs.add_edge(**edge)
                new_edges += 1
                per["edges"] += 1

        top_n = [{"addr": a, "short": _short(a), "n": n} for a, n in neighbors.most_common(15)]
        per["neighbors"] = top_n
        expanded.append(per)

        if enqueue_graph:
            gs.enqueue_expand(state, addr, reason=f"profit:{s.get('score')}", hop=1)
            for n, _c in neighbors.most_common(8):
                if n not in known and (known.get(n) or {}).get("role") not in {"cex", "bridge"}:
                    gs.enqueue_expand(state, n, reason=f"profit_nbr:{_short(addr)}", hop=2)

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        EXPAND_LOG.parent.mkdir(parents=True, exist_ok=True)
        with EXPAND_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": _now(), **per}, ensure_ascii=False, default=str) + "\n")

    if enqueue_graph:
        gs.save_state(state)

    return {
        "ok": True,
        "elapsed_sec": round(time.time() - t0, 2),
        "expanded": len(expanded),
        "new_edges": new_edges,
        "new_neighbors": len(new_addrs),
        "expand_queue": len(state.get("expand_queue") or []) if enqueue_graph else None,
        "seeds": expanded,
    }


def run_profit_pipeline(
    *,
    do_expand: bool = False,
    expand_limit: int | None = None,
) -> dict[str, Any]:
    """A then B: local profit → live expand."""
    t0 = time.time()
    profit = find_profit_seeds()
    expand: dict[str, Any] = {"ok": False, "skipped": True}
    if do_expand:
        expand = expand_profit_seeds(
            profit.get("seeds") or [],
            limit=expand_limit,
            enqueue_graph=True,
        )
    return {
        "tool": "profit_pipeline",
        "elapsed_sec": round(time.time() - t0, 2),
        "profit": {
            "stats": profit.get("stats"),
            "params": profit.get("params"),
            "top": (profit.get("seeds") or [])[:20],
        },
        "expand": expand,
    }
