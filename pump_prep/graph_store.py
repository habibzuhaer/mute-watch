"""Persistent address/edge graph — survives stop/restart."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pump_prep.config import ROOT

GRAPH_DIR = Path(
    __import__("os").getenv("MUTE_GRAPH_DIR", str(ROOT / "data" / "graph"))
)
STATE_FILE = GRAPH_DIR / "state.json"
ADDR_FILE = GRAPH_DIR / "addresses.jsonl"
EDGE_FILE = GRAPH_DIR / "edges.jsonl"
MATCH_FILE = GRAPH_DIR / "matches.jsonl"
TOKEN_FILE = GRAPH_DIR / "tokens.jsonl"
SIGNAL_FILE = GRAPH_DIR / "signals.jsonl"

_lock = threading.Lock()


def ensure_dir() -> None:
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict[str, Any]:
    ensure_dir()
    if not STATE_FILE.exists():
        return {
            "version": 1,
            "done_tokens": [],
            "failed_tokens": {},
            "expand_queue": [],
            "expand_done": [],
            "stats": {
                "tokens_ok": 0,
                "tokens_fail": 0,
                "edges": 0,
                "matches": 0,
                "addresses": 0,
            },
            "updated_at": None,
            "last_token": None,
            "cycles": 0,
        }
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    ensure_dir()
    state["updated_at"] = _now()
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    ensure_dir()
    row = {**row, "saved_at": _now()}
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
            if limit and len(rows) >= limit:
                break
    return rows


def read_jsonl_tail(path: Path, n: int = 200) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    return rows[-n:]


def upsert_address(addr: str, **fields: Any) -> None:
    """Append address sighting (duplicates OK; report aggregates)."""
    if not addr:
        return
    append_jsonl(
        ADDR_FILE,
        {
            "address": addr.lower() if addr.startswith("0x") else addr,
            **fields,
        },
    )


def add_edge(**fields: Any) -> None:
    append_jsonl(EDGE_FILE, fields)


def add_match(**fields: Any) -> None:
    append_jsonl(MATCH_FILE, fields)


def add_signal(**fields: Any) -> None:
    """Append a scored, human-readable signal to the journal."""
    append_jsonl(SIGNAL_FILE, fields)


def add_token_result(**fields: Any) -> None:
    append_jsonl(TOKEN_FILE, fields)


def progress_snapshot(universe_total: int | None = None) -> dict[str, Any]:
    """Explicit scan progress for dashboard / HTML."""
    from pump_prep.config import MCAP_CACHE

    state = load_state()
    done = len(state.get("done_tokens") or [])
    total = universe_total
    if total is None and MCAP_CACHE.exists():
        try:
            total = len(json.loads(MCAP_CACHE.read_text()).get("tokens") or [])
        except Exception:
            total = 0
    total = int(total or 0)
    pct = round(100.0 * done / total, 2) if total else 0.0
    signals = read_jsonl_tail(SIGNAL_FILE, 300)
    by_tier: dict[str, int] = {}
    for s in signals:
        t = s.get("tier") or "noise"
        by_tier[t] = by_tier.get(t, 0) + 1
    actionable = [s for s in signals if s.get("tier") == "actionable"]
    actionable.sort(key=lambda x: (-(x.get("score") or 0), x.get("saved_at") or ""))
    return {
        "done": done,
        "total": total,
        "remaining": max(0, total - done),
        "pct": pct,
        "last_token": state.get("last_token"),
        "updated_at": state.get("updated_at"),
        "expand_queue": len(state.get("expand_queue") or []),
        "expand_done": len(state.get("expand_done") or []),
        "stats": state.get("stats") or {},
        "signals_total_sample": len(signals),
        "signals_by_tier": by_tier,
        "top_actionable": actionable[-25:][::-1],
        "bar": {
            "done": done,
            "remaining": max(0, total - done),
        },
    }


def mark_token_done(state: dict[str, Any], token_id: str, ok: bool = True) -> None:
    done = set(state.get("done_tokens") or [])
    done.add(token_id)
    state["done_tokens"] = sorted(done)
    stats = state.setdefault("stats", {})
    if ok:
        stats["tokens_ok"] = int(stats.get("tokens_ok") or 0) + 1
    else:
        stats["tokens_fail"] = int(stats.get("tokens_fail") or 0) + 1
        fails = state.setdefault("failed_tokens", {})
        fails[token_id] = int(fails.get(token_id) or 0) + 1


def enqueue_expand(
    state: dict[str, Any],
    address: str,
    reason: str = "",
    *,
    hop: int = 1,
) -> None:
    if not address or not address.startswith("0x"):
        return
    a = address.lower()
    done = set(state.get("expand_done") or [])
    q = list(state.get("expand_queue") or [])
    if a in done or a in q:
        return
    q.append(a)
    state["expand_queue"] = q
    meta = dict(state.get("expand_meta") or {})
    meta[a] = {"reason": reason or "", "hop": max(1, int(hop))}
    state["expand_meta"] = meta
    # keep queue bounded
    if len(state["expand_queue"]) > 500:
        dropped = state["expand_queue"][:-500]
        state["expand_queue"] = state["expand_queue"][-500:]
        for d in dropped:
            meta.pop(d, None)
        state["expand_meta"] = meta


def pop_expand(state: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Pop next expand address and its meta ({reason, hop})."""
    q = list(state.get("expand_queue") or [])
    if not q:
        return None, {}
    addr = q.pop(0)
    state["expand_queue"] = q
    done = set(state.get("expand_done") or [])
    done.add(addr)
    state["expand_done"] = sorted(done)[-2000:]
    meta = dict(state.get("expand_meta") or {})
    info = dict(meta.pop(addr, {}) or {})
    state["expand_meta"] = meta
    if "hop" not in info:
        # legacy queue entries / hop2 reason prefix
        reason = str(info.get("reason") or "")
        info["hop"] = 2 if reason.startswith("hop2") else 1
    return addr, info


def aggregate_summary() -> dict[str, Any]:
    """Build rollup for API / HTML from jsonl + state."""
    state = load_state()
    matches = read_jsonl_tail(MATCH_FILE, 500)
    tokens = read_jsonl_tail(TOKEN_FILE, 500)
    edges = read_jsonl_tail(EDGE_FILE, 500)
    addrs = read_jsonl_tail(ADDR_FILE, 800)
    signals = read_jsonl_tail(SIGNAL_FILE, 300)
    progress = progress_snapshot()

    # unique address count approx
    uniq_addr = {a.get("address") for a in addrs if a.get("address")}
    entity_hits: dict[str, int] = {}
    for m in matches:
        e = m.get("match_entity") or ""
        if e:
            entity_hits[e] = entity_hits.get(e, 0) + 1

    return {
        "state": {
            "done_tokens": len(state.get("done_tokens") or []),
            "expand_queue": len(state.get("expand_queue") or []),
            "expand_done": len(state.get("expand_done") or []),
            "stats": state.get("stats") or {},
            "updated_at": state.get("updated_at"),
            "last_token": state.get("last_token"),
            "cycles": state.get("cycles") or 0,
        },
        "progress": progress,
        "files": {
            "dir": str(GRAPH_DIR),
            "matches": MATCH_FILE.exists(),
            "edges": EDGE_FILE.exists(),
            "addresses": ADDR_FILE.exists(),
            "tokens": TOKEN_FILE.exists(),
            "signals": SIGNAL_FILE.exists(),
        },
        "uniq_addresses_sample": len(uniq_addr),
        "recent_matches": matches[-80:],
        "recent_tokens": tokens[-120:],
        "recent_edges": edges[-120:],
        "recent_signals": signals[-80:],
        "entity_hits": dict(sorted(entity_hits.items(), key=lambda x: -x[1])[:30]),
        "generated_at": _now(),
    }


def touch_mtime() -> float:
    ensure_dir()
    times = []
    for p in (STATE_FILE, MATCH_FILE, EDGE_FILE, TOKEN_FILE):
        if p.exists():
            times.append(p.stat().st_mtime)
    return max(times) if times else 0.0


_mcap_cache: dict[str, Any] = {"mtime": -1.0, "by_symbol": {}, "by_id": {}, "by_contract": {}}


def token_mcap_index(*, force: bool = False) -> dict[str, Any]:
    """Cached maps symbol/id/contract → market cap USD from tokens.jsonl."""
    ensure_dir()
    mtime = TOKEN_FILE.stat().st_mtime if TOKEN_FILE.exists() else 0.0
    if not force and _mcap_cache["mtime"] == mtime and _mcap_cache["by_symbol"]:
        return _mcap_cache
    by_symbol: dict[str, float] = {}
    by_id: dict[str, float] = {}
    by_contract: dict[str, float] = {}
    if TOKEN_FILE.exists():
        with TOKEN_FILE.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                raw = row.get("mcap")
                if raw is None or raw == "":
                    continue
                try:
                    mcap = float(raw)
                except (TypeError, ValueError):
                    continue
                if mcap <= 0:
                    continue
                sym = (row.get("symbol") or "").strip().upper()
                tid = (row.get("id") or "").strip().lower()
                contract = (row.get("contract") or "").strip().lower()
                if sym:
                    by_symbol[sym] = mcap
                if tid:
                    by_id[tid] = mcap
                if contract:
                    by_contract[contract] = mcap
    _mcap_cache.update(
        {
            "mtime": mtime,
            "by_symbol": by_symbol,
            "by_id": by_id,
            "by_contract": by_contract,
            "count": len(by_id) or len(by_symbol),
        }
    )
    return _mcap_cache


def lookup_mcap(
    *,
    symbol: str | None = None,
    token_id: str | None = None,
    contract: str | None = None,
    index: dict[str, Any] | None = None,
) -> float | None:
    idx = index or token_mcap_index()
    if contract:
        v = idx["by_contract"].get(contract.strip().lower())
        if v is not None:
            return float(v)
    if token_id:
        v = idx["by_id"].get(token_id.strip().lower())
        if v is not None:
            return float(v)
    if symbol:
        v = idx["by_symbol"].get(symbol.strip().upper())
        if v is not None:
            return float(v)
    return None


def fmt_mcap(mcap: float | None) -> str:
    if mcap is None:
        return "—"
    try:
        n = float(mcap)
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000_000:
        return f"${n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n / 1_000:.0f}K"
    return f"${n:.0f}"
