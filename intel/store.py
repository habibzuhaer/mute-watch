"""Persistent multi-chain address / edge / family store."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from intel.config import DATA_DIR, QUEUE_CAP
from intel.normalize import norm, short, storage_chain

_lock = threading.Lock()
_addr_cache: dict[str, dict[str, Any]] | None = None
_addr_dirty = 0
_ADDR_FLUSH_EVERY = 80

ADDR_FILE = DATA_DIR / "addresses.json"
EDGE_FILE = DATA_DIR / "edges.jsonl"
FAMILY_FILE = DATA_DIR / "families.json"
SIGNAL_FILE = DATA_DIR / "signals.jsonl"
TOKEN_FILE = DATA_DIR / "tokens.json"
STATE_FILE = DATA_DIR / "state.json"
SEEN_EDGES = DATA_DIR / "seen_edges.txt"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "wiki").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "wiki" / "addresses").mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    ensure()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def load_state() -> dict[str, Any]:
    ensure()
    st = load_json(
        STATE_FILE,
        {
            "version": 1,
            "cycle": 0,
            "collect_started_at": None,
            "collect_until": None,
            "queue": [],  # [{chain, address, hop, reason, priority}]
            "done": [],
            "stats": {},
            "last_cycle": None,
            "errors": [],
        },
    )
    return st


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = _now()
    save_json(STATE_FILE, state)


def load_addresses() -> dict[str, dict[str, Any]]:
    global _addr_cache
    with _lock:
        if _addr_cache is None:
            raw = load_json(ADDR_FILE, {})
            _addr_cache = raw if isinstance(raw, dict) else {}
        return _addr_cache


def save_addresses(addrs: dict[str, dict[str, Any]] | None = None) -> None:
    global _addr_dirty
    with _lock:
        data = addrs if addrs is not None else (_addr_cache or {})
        # compact JSON (no indent) for speed on large DB
        ensure()
        tmp = ADDR_FILE.with_name(f"{ADDR_FILE.stem}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":")), encoding="utf-8")
        tmp.replace(ADDR_FILE)
        _addr_dirty = 0


def flush_addresses() -> None:
    load_addresses()
    save_addresses()


def addr_key(chain: str, address: str) -> str:
    return f"{storage_chain(chain)}:{address}"


def upsert_address(
    chain: str,
    address: str,
    *,
    tags: list[str] | None = None,
    role: str | None = None,
    entity: str | None = None,
    label: str | None = None,
    family_id: str | None = None,
    meta: dict[str, Any] | None = None,
    bump_in: int = 0,
    bump_out: int = 0,
    token: str | None = None,
    flush: bool = False,
) -> str:
    global _addr_dirty, _addr_cache
    a = norm(chain, address)
    if not a:
        return ""
    ch = storage_chain(chain)
    key = addr_key(ch, a)
    with _lock:
        if _addr_cache is None:
            raw = load_json(ADDR_FILE, {})
            _addr_cache = raw if isinstance(raw, dict) else {}
        addrs = _addr_cache
        card = addrs.get(key) or {
            "key": key,
            "chain": ch,
            "address": a,
            "short": short(a),
            "tags": [],
            "first_seen": _now(),
            "in_n": 0,
            "out_n": 0,
            "tokens": [],
            "family_id": None,
        }
        tagset = set(card.get("tags") or [])
        for t in tags or []:
            if t:
                tagset.add(t)
        card["tags"] = sorted(tagset)
        if role:
            card["role"] = role
        if entity:
            card["entity"] = entity
        if label:
            card["label"] = label
        if family_id:
            card["family_id"] = family_id
        if meta:
            card["meta"] = {**(card.get("meta") or {}), **meta}
        card["in_n"] = int(card.get("in_n") or 0) + bump_in
        card["out_n"] = int(card.get("out_n") or 0) + bump_out
        if token:
            toks = set(card.get("tokens") or [])
            toks.add(token)
            card["tokens"] = sorted(toks)[:40]
        card["last_seen"] = _now()
        addrs[key] = card
        _addr_dirty += 1
        dirty = _addr_dirty
    if flush or dirty >= _ADDR_FLUSH_EVERY:
        save_addresses()
    return key


def _edge_dedupe_key(edge: dict[str, Any]) -> str:
    return "|".join(
        [
            str(edge.get("chain") or ""),
            str(edge.get("tx") or edge.get("hash") or ""),
            str(edge.get("from") or ""),
            str(edge.get("to") or ""),
            str(edge.get("token") or edge.get("symbol") or ""),
        ]
    )


_seen_cache: set[str] | None = None


def _load_seen() -> set[str]:
    global _seen_cache
    if _seen_cache is not None:
        return _seen_cache
    ensure()
    s: set[str] = set()
    if SEEN_EDGES.exists():
        for line in SEEN_EDGES.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                s.add(line.strip())
    # bound memory
    if len(s) > 500_000:
        s = set(list(s)[-200_000:])
    _seen_cache = s
    return s


def add_edge(edge: dict[str, Any]) -> bool:
    """Append edge if new. Updates address cards. Returns True if written."""
    ensure()
    ch = storage_chain(edge.get("chain") or "", edge.get("chain_id"))
    frm = norm(ch if ch != "bnb" else "evm", edge.get("from"))
    to = norm(ch if ch != "bnb" else "evm", edge.get("to"))
    if ch == "solana":
        frm = norm("solana", edge.get("from"))
        to = norm("solana", edge.get("to"))
    if not frm or not to or frm == to:
        return False
    row = {
        "chain": ch,
        "chain_id": edge.get("chain_id"),
        "from": frm,
        "to": to,
        "direction": edge.get("direction") or "out",
        "symbol": edge.get("symbol") or "",
        "token": edge.get("token") or edge.get("contract") or edge.get("mint") or "",
        "amount": edge.get("amount"),
        "tx": edge.get("tx") or edge.get("hash") or "",
        "timestamp": int(edge.get("timestamp") or 0),
        "source": edge.get("source") or "intel",
        "hop": edge.get("hop"),
        "seed": edge.get("seed"),
        "saved_at": _now(),
    }
    dk = _edge_dedupe_key(row)
    seen = _load_seen()
    if dk in seen:
        return False
    with _lock:
        seen.add(dk)
        with SEEN_EDGES.open("a", encoding="utf-8") as sf:
            sf.write(dk + "\n")
        with EDGE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    # address bumps (outside lock of seen — upsert has own lock)
    upsert_address(ch, frm, bump_out=1, token=row["symbol"] or None, tags=["seen"])
    upsert_address(ch, to, bump_in=1, token=row["symbol"] or None, tags=["seen"])
    return True


def read_edges_tail(limit: int = 5000) -> list[dict[str, Any]]:
    if not EDGE_FILE.exists():
        return []
    # efficient-ish tail
    rows: list[dict[str, Any]] = []
    with EDGE_FILE.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        block = min(size, 2_000_000)
        f.seek(size - block)
        data = f.read().decode("utf-8", errors="replace")
    lines = [ln for ln in data.splitlines() if ln.strip()]
    for ln in lines[-limit:]:
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    return rows


def iter_all_edges():
    if not EDGE_FILE.exists():
        return
    with EDGE_FILE.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def edge_count() -> int:
    if not EDGE_FILE.exists():
        return 0
    n = 0
    with EDGE_FILE.open("rb") as f:
        for _ in f:
            n += 1
    return n


def enqueue(
    state: dict[str, Any],
    chain: str,
    address: str,
    *,
    reason: str = "",
    hop: int = 0,
    priority: int = 0,
) -> bool:
    a = norm(chain if chain != "bnb" else "evm", address)
    if chain in {"sol", "solana"}:
        a = norm("solana", address)
    if not a:
        return False
    ch = storage_chain(chain)
    key = f"{ch}:{a}"
    done = set(state.get("done") or [])
    q = list(state.get("queue") or [])
    if key in done:
        return False
    if any(f"{x.get('chain')}:{x.get('address')}" == key for x in q):
        return False
    q.append(
        {
            "chain": ch,
            "address": a,
            "hop": int(hop),
            "reason": reason,
            "priority": int(priority),
            "enqueued_at": _now(),
        }
    )
    q.sort(key=lambda x: (-int(x.get("priority") or 0), int(x.get("hop") or 0)))
    if len(q) > QUEUE_CAP:
        q = q[:QUEUE_CAP]
    state["queue"] = q
    return True


def pop_batch(state: dict[str, Any], n: int) -> list[dict[str, Any]]:
    """Claim next N seeds into in_flight (not yet done). Crash → recover_in_flight."""
    q = list(state.get("queue") or [])
    if not q:
        return []
    batch = q[:n]
    state["queue"] = q[n:]
    state["in_flight"] = list(batch)
    state["in_flight_at"] = _now()
    return batch


def ack_batch(state: dict[str, Any], batch: list[dict[str, Any]], *, ok: bool = True) -> None:
    """Mark claimed batch done (or requeue on failure)."""
    done = list(state.get("done") or [])
    if ok:
        for item in batch:
            key = f"{item.get('chain')}:{item.get('address')}"
            if key not in done:
                done.append(key)
        state["done"] = done[-5000:]
        state["in_flight"] = []
    else:
        # put back to front of queue
        q = list(state.get("queue") or [])
        keys = {f"{x.get('chain')}:{x.get('address')}" for x in q}
        for item in reversed(batch):
            key = f"{item.get('chain')}:{item.get('address')}"
            if key not in keys:
                q.insert(0, item)
        state["queue"] = q
        state["in_flight"] = []


def append_signal(row: dict[str, Any]) -> None:
    ensure()
    row = {**row, "saved_at": _now()}
    with _lock:
        with SIGNAL_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    score = int(row.get("score") or 0)
    if score >= 40:
        try:
            from agents.hooks import on_signal

            on_signal(
                "intel",
                str(row.get("type") or "signal"),
                level="ACT" if score >= 55 else "WATCH",
                score=score,
                ref=str(row.get("symbol") or row.get("short") or row.get("key") or "")[:80],
                extra={"chain": row.get("chain")},
            )
        except Exception:
            pass


def stats_snapshot() -> dict[str, Any]:
    addrs = load_addresses()
    by_chain: dict[str, int] = defaultdict(int)
    for c in addrs.values():
        by_chain[c.get("chain") or "?"] += 1
    fam = load_json(FAMILY_FILE, {})
    return {
        "addresses": len(addrs),
        "edges": edge_count(),
        "by_chain": dict(by_chain),
        "families": len((fam.get("families") if isinstance(fam, dict) else None) or []),
        "queue": len(load_state().get("queue") or []),
        "ts": _now(),
    }
