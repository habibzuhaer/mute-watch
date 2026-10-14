"""Deepen top pump hubs + prioritize them in Intel queue."""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from intel import wiki
from intel.config import DATA_DIR, GRAPH_DIR
from intel.normalize import short
from intel.store import (
    enqueue,
    flush_addresses,
    iter_all_edges,
    load_addresses,
    load_json,
    load_state,
    save_json,
    save_state,
    upsert_address,
)

logger = logging.getLogger(__name__)

HUBS_FILE = DATA_DIR / "hubs.json"
PRIORITY = 100  # top of queue


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pick_hubs(*, limit: int = 7) -> list[dict[str, Any]]:
    """Multi-pump profit hubs + top RepeatDeployers."""
    hubs: list[dict[str, Any]] = []
    seen: set[str] = set()

    profit_path = Path(__file__).resolve().parents[1] / "data" / "rozvidka" / "db" / "profit_seeds.json"
    if profit_path.exists():
        seeds = json.loads(profit_path.read_text(encoding="utf-8")).get("seeds") or []
        for s in seeds:
            if int(s.get("early_token_n") or 0) < 2 and int(s.get("score") or 0) < 50:
                continue
            a = (s.get("address") or "").lower()
            if not a or a in seen:
                continue
            seen.add(a)
            hubs.append(
                {
                    "address": a,
                    "short": s.get("short") or short(a),
                    "kind": "multi_pump_hub",
                    "score": s.get("score"),
                    "early_tokens": s.get("early_tokens") or [],
                    "tags": list(s.get("tags") or []) + ["hub", "priority"],
                    "chain": "ethereum",
                }
            )
            if len(hubs) >= 5:
                break

    dl = GRAPH_DIR / "discovered_labels.json"
    if dl.exists():
        wallets = json.loads(dl.read_text(encoding="utf-8")).get("wallets") or []

        def pump_n(w: dict) -> int:
            lab = w.get("label") or ""
            if "pump×" not in lab:
                return 0
            try:
                return int(lab.split("pump×")[-1].split()[0])
            except Exception:
                return 0

        for w in sorted(wallets, key=pump_n, reverse=True):
            if (w.get("entity") or "") != "RepeatDeployer":
                continue
            if pump_n(w) < 2:
                continue
            a = (w.get("address") or "").lower()
            if not a or a in seen:
                continue
            seen.add(a)
            hubs.append(
                {
                    "address": a,
                    "short": short(a),
                    "kind": "repeat_deployer",
                    "score": 50 + pump_n(w) * 5,
                    "label": w.get("label"),
                    "entity": w.get("entity"),
                    "tags": ["hub", "priority", "repeat_deployer", "robot"],
                    "chain": "ethereum",
                }
            )
            if len([h for h in hubs if h["kind"] == "repeat_deployer"]) >= 2:
                break

    return hubs[:limit]


def _map_flows(address: str) -> dict[str, Any]:
    """Build куда/откуда/related from intel + legacy edges."""
    addr = address.lower()
    sent: Counter[str] = Counter()
    recv: Counter[str] = Counter()
    tokens: Counter[str] = Counter()
    chains: Counter[str] = Counter()

    for e in iter_all_edges():
        frm = (e.get("from") or "").lower()
        to = (e.get("to") or "").lower()
        if addr not in {frm, to}:
            continue
        chains[e.get("chain") or "?"] += 1
        tok = e.get("symbol") or e.get("token") or ""
        if tok:
            tokens[str(tok)[:32]] += 1
        if frm == addr and to:
            sent[to] += 1
        elif to == addr and frm:
            recv[frm] += 1

    # legacy graph edges
    edge_path = GRAPH_DIR / "edges.jsonl"
    if edge_path.exists():
        with edge_path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            block = min(size, 3_000_000)
            f.seek(max(0, size - block))
            data = f.read().decode("utf-8", errors="replace")
        for ln in data.splitlines()[-8000:]:
            try:
                e = json.loads(ln)
            except Exception:
                continue
            frm = (e.get("from_addr") or e.get("from") or "").lower()
            to = (e.get("to_addr") or e.get("to") or "").lower()
            if addr not in {frm, to}:
                continue
            chains["legacy"] += 1
            if frm == addr and to:
                sent[to] += 1
            elif to == addr and frm:
                recv[frm] += 1

    # rozvidka card if any
    roz = Path(__file__).resolve().parents[1] / "data" / "rozvidka" / "db" / "addresses.json"
    card = {}
    if roz.exists():
        card = (json.loads(roz.read_text(encoding="utf-8")).get(addr) or {})

    return {
        "sent_to": [{"addr": a, "short": short(a), "n": n} for a, n in sent.most_common(12)],
        "recv_from": [{"addr": a, "short": short(a), "n": n} for a, n in recv.most_common(12)],
        "tokens": [{"symbol": s, "n": n} for s, n in tokens.most_common(15)],
        "chains": dict(chains),
        "family_id": card.get("family_id"),
        "roz_tags": card.get("tags") or [],
        "edge_touch": sum(sent.values()) + sum(recv.values()),
    }


def deepen_hubs(*, limit: int = 7, prioritize: bool = True) -> dict[str, Any]:
    """A: map flows + wiki. B: enqueue high priority for expand."""
    hubs = _pick_hubs(limit=limit)
    deepened = []
    state = load_state() if prioritize else {}
    enq = 0

    for h in hubs:
        flows = _map_flows(h["address"])
        rec = {**h, **flows, "deepened_at": _now()}
        deepened.append(rec)

        tags = list(h.get("tags") or []) + ["hub_deep"]
        upsert_address(
            h.get("chain") or "ethereum",
            h["address"],
            tags=tags,
            role="hub" if h.get("kind") == "multi_pump_hub" else "deployer",
            entity=h.get("entity") or h.get("kind"),
            label=h.get("label") or f"hub:{','.join((h.get('early_tokens') or [])[:3])}",
            meta={
                "hub_kind": h.get("kind"),
                "hub_score": h.get("score"),
                "early_tokens": h.get("early_tokens"),
                "sent_to": flows["sent_to"][:8],
                "recv_from": flows["recv_from"][:8],
            },
        )

        # wiki card
        sent_lines = [f"- `{x['short']}` ×{x['n']} `{x['addr']}`" for x in flows["sent_to"][:10]] or ["- —"]
        recv_lines = [f"- `{x['short']}` ×{x['n']} `{x['addr']}`" for x in flows["recv_from"][:10]] or ["- —"]
        tok_lines = [f"- {x['symbol']} ×{x['n']}" for x in flows["tokens"][:12]] or ["- —"]
        lines = [
            f"# Hub {h.get('short')} ({h.get('kind')})",
            "",
            f"- address: `{h['address']}`",
            f"- score: {h.get('score')}",
            f"- early/pump: {', '.join(h.get('early_tokens') or []) or h.get('label') or '—'}",
            f"- family: {flows.get('family_id') or '—'}",
            f"- edge_touch: {flows.get('edge_touch')}",
            f"- chains: {flows.get('chains')}",
            "",
            "## куда (sent_to)",
            *sent_lines,
            "",
            "## откуда (recv_from)",
            *recv_lines,
            "",
            "## tokens",
            *tok_lines,
            "",
            f"_updated {_now()}_",
        ]
        wiki.ensure()
        path = wiki.WIKI / "addresses" / f"hub_{h['address']}.md"
        path.write_text("\n".join(lines), encoding="utf-8")

        # also rozvidka wiki if available
        try:
            from rozvidka import wiki as rw

            rw.upsert_address(
                h["address"],
                note="\n".join(lines[2:20]),
                tags=tags,
                meta={"hub": True, "kind": h.get("kind"), "score": h.get("score")},
            )
        except Exception:
            pass

        if prioritize:
            # expand on BNB + mark ethereum for eth ingest
            for ch in ("bnb", "ethereum"):
                if enqueue(
                    state,
                    ch,
                    h["address"],
                    reason=f"hub:{h.get('kind')}",
                    hop=0,
                    priority=PRIORITY,
                ):
                    enq += 1
            # neighbors as hop1 high priority
            for x in (flows["sent_to"] + flows["recv_from"])[:8]:
                if enqueue(
                    state,
                    "bnb",
                    x["addr"],
                    reason=f"hub_nbr:{h.get('short')}",
                    hop=1,
                    priority=PRIORITY - 10,
                ):
                    enq += 1
                if enqueue(
                    state,
                    "ethereum",
                    x["addr"],
                    reason=f"hub_nbr:{h.get('short')}",
                    hop=1,
                    priority=PRIORITY - 10,
                ):
                    enq += 1

    flush_addresses()
    if prioritize:
        save_state(state)

    out = {
        "built_at": _now(),
        "hubs": deepened,
        "enqueued": enq,
        "queue": len(state.get("queue") or []) if prioritize else None,
    }
    save_json(HUBS_FILE, out)

    # memory / clusters summary EN+UK
    wiki.ensure()
    summary = []
    for h in deepened:
        summary.append(
            f"- **{h.get('short')}** `{h['address']}` · {h.get('kind')} · sc {h.get('score')} · "
            f"куда×{len(h.get('sent_to') or [])} откуда×{len(h.get('recv_from') or [])} · "
            f"{', '.join(h.get('early_tokens') or []) or h.get('label')}"
        )
    wiki.append(
        "memory",
        "EN: Top pump hubs / controllers mapped (flows + priority expand).\n"
        "UK: Топ хаби пампа / контролери — карта потоків + пріоритет у черзі.\n\n"
        + "\n".join(summary),
        heading="hubs deepen",
    )
    wiki.append("clusters", "\n".join(summary), heading="priority hubs")
    return out
