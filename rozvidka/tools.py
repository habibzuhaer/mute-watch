"""Deterministic tools over MUTE graph — inputs for each Розвідка turn."""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable

from rozvidka import wiki

logger = logging.getLogger(__name__)

ToolFn = Callable[..., dict[str, Any]]


def _short(addr: str | None) -> str:
    a = (addr or "").strip()
    if len(a) < 10:
        return a
    return a[:4] + a[-4:]


def base_stats() -> dict[str, Any]:
    from pump_prep import graph_store as gs
    from pump_prep.cycles import check_cycle_health, signal_board

    progress = gs.progress_snapshot()
    health = check_cycle_health()
    board = signal_board(limit_act=8, limit_watch=8)
    state = gs.load_state()
    return {
        "tool": "base_stats",
        "progress": {
            "pct": progress.get("pct"),
            "tokens_done": progress.get("tokens_done"),
            "tokens_total": progress.get("tokens_total"),
            "signals_by_tier": progress.get("signals_by_tier"),
        },
        "health": {
            "cycle_status": health.get("cycle_status"),
            "cycles": health.get("cycles"),
            "age_sec": health.get("age_sec"),
            "expand_queue": health.get("expand_queue"),
            "issues": (health.get("issues_i18n") or {}).get("uk") or health.get("issues") or [],
        },
        "board": {
            "act_n": len(board.get("actionable") or []),
            "watch_n": len(board.get("watch") or []),
            "act_top": [
                {
                    "symbol": s.get("symbol"),
                    "score": s.get("score"),
                    "entity": s.get("match_entity"),
                    "kind": s.get("signal_kind") or s.get("kind"),
                }
                for s in (board.get("actionable") or [])[:5]
            ],
            "watch_top": [
                {
                    "symbol": s.get("symbol"),
                    "score": s.get("score"),
                    "entity": s.get("match_entity"),
                }
                for s in (board.get("watch") or [])[:5]
            ],
        },
        "scanner_cycles": state.get("cycles"),
        "last_token": state.get("last_token"),
    }


def cluster_by_funder(*, limit: int = 12) -> dict[str, Any]:
    """Group native/stable funding edges: parent → many EOAs (shared funder)."""
    from pump_prep import graph_store as gs
    from pump_prep.clusters import build_deployer_clusters
    from pump_prep.labels import load_known

    known = load_known()
    gas_or_stable = {
        "eth",
        "bnb",
        "matic",
        "avax",
        "ftm",
        "glmr",
        "movr",
        "usdt",
        "usdc",
        "dai",
        "usdce",
        "usdbc",
        "native",
    }
    parents: dict[str, set[str]] = defaultdict(set)
    for edge in gs.read_jsonl_tail(gs.EDGE_FILE, 12000):
        sym = (edge.get("symbol") or edge.get("asset") or "").lower()
        if sym not in gas_or_stable:
            continue
        if edge.get("is_token_itself"):
            continue
        frm = (
            edge.get("from_addr")
            or edge.get("from")
            or edge.get("from_address")
            or ""
        ).lower()
        to = (
            edge.get("to_addr")
            or edge.get("to")
            or edge.get("to_address")
            or ""
        ).lower()
        if not frm.startswith("0x") or not to.startswith("0x"):
            continue
        direction = (edge.get("direction") or "out").lower()
        if direction == "out":
            parents[frm].add(to)
        elif direction == "in":
            parents[to].add(frm)

    clusters = []
    for parent, kids in parents.items():
        if len(kids) < 3:
            continue
        meta = known.get(parent) or {}
        clusters.append(
            {
                "funder": parent,
                "short": _short(parent),
                "children": len(kids),
                "sample_kids": [_short(k) for k in list(kids)[:6]],
                "entity": meta.get("entity"),
                "role": meta.get("role"),
                "label": meta.get("label"),
                "kind": "funder_family",
            }
        )
    clusters.sort(key=lambda c: -c["children"])

    # Deployer clusters = second group type (pump factories)
    dep = build_deployer_clusters()
    deployer_groups = []
    for c in (dep.get("clusters") or [])[:limit]:
        if int(c.get("token_count") or 0) < 2 and int(c.get("pump_count") or 0) < 1:
            continue
        deployer_groups.append(
            {
                "funder": c.get("deployer"),
                "short": _short(c.get("deployer")),
                "children": c.get("token_count"),
                "pump_count": c.get("pump_count"),
                "symbols": (c.get("symbols") or [])[:8],
                "entity": (c.get("entities") or [None])[0] if c.get("entities") else None,
                "kind": "deployer_cluster",
                "score_hint": c.get("score_hint"),
            }
        )

    return {
        "tool": "cluster_by_funder",
        "count": len(clusters),
        "clusters": clusters[:limit],
        "deployer_groups": deployer_groups[:limit],
        "deployer_count": len(deployer_groups),
    }


def token_early_wallets(*, limit: int = 10) -> dict[str, Any]:
    """Recent tokens with early counterparty / match activity."""
    from pump_prep import graph_store as gs
    from pump_prep.clusters import build_deployer_clusters

    tokens = gs.read_jsonl_tail(gs.TOKEN_FILE, 400)
    # latest per id
    latest: dict[str, dict[str, Any]] = {}
    for row in tokens:
        tid = row.get("id") or row.get("symbol")
        if tid:
            latest[str(tid)] = row

    ranked = sorted(
        latest.values(),
        key=lambda t: (-int(t.get("match_count") or 0), -(t.get("timestamp") or 0)),
    )
    out = []
    for t in ranked[:limit]:
        dep = t.get("deployer") or ""
        out.append(
            {
                "id": t.get("id"),
                "symbol": t.get("symbol"),
                "deployer": dep,
                "deployer_short": _short(dep),
                "match_count": t.get("match_count"),
                "age_days": t.get("age_days"),
                "had_pump": bool(t.get("had_pump")),
                "status": t.get("status"),
            }
        )

    dep_clusters = build_deployer_clusters()
    top_deps = (dep_clusters.get("clusters") or [])[:5]
    return {
        "tool": "token_early_wallets",
        "tokens": out,
        "top_deployers": [
            {
                "deployer": c.get("deployer"),
                "short": _short(c.get("deployer")),
                "token_count": c.get("token_count"),
                "pump_count": c.get("pump_count"),
                "symbols": c.get("symbols"),
            }
            for c in top_deps
        ],
    }


def wallet_card(address: str | None = None) -> dict[str, Any]:
    """Card for a wallet: labels, recent edges, wiki note, signal hits."""
    from pump_prep import graph_store as gs
    from pump_prep.labels import load_known

    known = load_known()
    addr = (address or "").strip().lower()
    if not addr:
        # pick most active address from recent matches
        matches = gs.read_jsonl_tail(gs.MATCH_FILE, 500)
        counts: Counter[str] = Counter()
        for m in matches:
            for key in ("address", "counterparty", "match_address", "from", "to"):
                a = (m.get(key) or "").lower()
                if a.startswith("0x"):
                    counts[a] += 1
        addr = counts.most_common(1)[0][0] if counts else ""

    if not addr:
        return {"tool": "wallet_card", "error": "no address"}

    meta = known.get(addr) or {}
    edges = []
    for e in gs.read_jsonl_tail(gs.EDGE_FILE, 3000):
        frm = (e.get("from_addr") or e.get("from") or e.get("from_address") or "").lower()
        to = (e.get("to_addr") or e.get("to") or e.get("to_address") or "").lower()
        if addr in (frm, to):
            edges.append(
                {
                    "from": _short(frm),
                    "to": _short(to),
                    "asset": e.get("symbol") or e.get("token_symbol") or e.get("asset"),
                    "via": e.get("via") or e.get("reason") or e.get("direction"),
                }
            )
            if len(edges) >= 12:
                break

    note = wiki.read_address(addr, max_chars=1500)
    return {
        "tool": "wallet_card",
        "address": addr,
        "short": _short(addr),
        "entity": meta.get("entity"),
        "role": meta.get("role"),
        "label": meta.get("label"),
        "source": meta.get("source"),
        "recent_edges": edges,
        "wiki_note": note[:800] if note else None,
        "has_wiki": bool(note),
    }


def wiki_read(page: str = "memory") -> dict[str, Any]:
    return {"tool": "wiki_read", "page": page, "content": wiki.read_page(page, max_chars=3000)}


def wiki_append(page: str, text: str, heading: str | None = None) -> dict[str, Any]:
    path = wiki.append_page(page, text, heading=heading)
    return {"tool": "wiki_append", "page": page, "path": path, "ok": True}


def wiki_address_note(address: str, note: str, tags: list[str] | None = None) -> dict[str, Any]:
    path = wiki.upsert_address(address, note=note, tags=tags or ["prep"])
    return {"tool": "wiki_address_note", "address": address.lower(), "path": path, "ok": True}


def recent_signals(*, limit: int = 15) -> dict[str, Any]:
    from pump_prep import graph_store as gs

    rows = gs.read_jsonl_tail(gs.SIGNAL_FILE, limit)
    slim = []
    for s in reversed(rows):
        slim.append(
            {
                "tier": s.get("tier"),
                "score": s.get("score"),
                "symbol": s.get("symbol"),
                "kind": s.get("signal_kind") or s.get("kind"),
                "entity": s.get("match_entity"),
                "summary_uk": s.get("summary_uk") or s.get("summary"),
                "reasons_uk": (s.get("reasons_uk") or s.get("reasons") or [])[:3],
            }
        )
    return {"tool": "recent_signals", "signals": slim}


TOOLS: dict[str, ToolFn] = {
    "base_stats": lambda **_: base_stats(),
    "cluster_by_funder": lambda **kw: cluster_by_funder(**kw),
    "token_early_wallets": lambda **kw: token_early_wallets(**kw),
    "wallet_card": lambda **kw: wallet_card(**kw),
    "wiki_read": lambda **kw: wiki_read(**kw),
    "wiki_append": lambda **kw: wiki_append(**kw),
    "wiki_address_note": lambda **kw: wiki_address_note(**kw),
    "recent_signals": lambda **kw: recent_signals(**kw),
}


def run_tool(name: str, **kwargs: Any) -> dict[str, Any]:
    fn = TOOLS.get(name)
    if not fn:
        return {"tool": name, "error": f"unknown tool {name}"}
    try:
        return fn(**kwargs)
    except Exception as exc:
        logger.exception("tool %s failed", name)
        return {"tool": name, "error": str(exc)}


def default_turn_tools() -> list[tuple[str, dict[str, Any]]]:
    """Fixed tool sequence each autonomous turn (DeepSeek narrates after)."""
    return [
        ("base_stats", {}),
        ("recent_signals", {"limit": 12}),
        ("cluster_by_funder", {"limit": 10}),
        ("token_early_wallets", {"limit": 8}),
        ("wallet_card", {}),
        ("wiki_read", {"page": "clusters"}),
        ("wiki_read", {"page": "memory"}),
    ]


def dumps_compact(obj: Any, limit: int = 12000) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    if len(text) > limit:
        return text[: limit - 20] + "…[truncated]"
    return text
