"""Family / relation engine: link addresses by transfers, pump contacts, persist wiki DB."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rozvidka import wiki
from rozvidka.config import DATA_DIR, ROOT

logger = logging.getLogger(__name__)

DB_DIR = DATA_DIR / "db"
ADDR_DB = DB_DIR / "addresses.json"
FAMILY_DB = DB_DIR / "families.json"
REL_DB = DB_DIR / "relations.jsonl"

ZERO = "0x0000000000000000000000000000000000000000"
SPAM_RE = re.compile(r"(claim|visit|http|reward|airdrop|\.io|\.com|\.fi)", re.I)

GAS_STABLE = {
    "eth", "bnb", "matic", "avax", "ftm", "glmr", "movr",
    "usdt", "usdc", "dai", "usdce", "usdbc", "native", "weth", "wbnb",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short(addr: str | None) -> str:
    a = (addr or "").strip().lower()
    if len(a) < 10:
        return a
    return a[:4] + a[-4:]


def _norm(addr: Any) -> str:
    a = (addr or "").strip().lower()
    if a.startswith("0x") and len(a) == 42 and a != ZERO:
        return a
    return ""


def _spam_symbol(sym: str) -> bool:
    s = (sym or "").strip()
    if not s:
        return True
    if SPAM_RE.search(s):
        return True
    if " " in s and len(s) > 20:
        return True
    return False


class UnionFind:
    def __init__(self) -> None:
        self.p: dict[str, str] = {}
        self.r: dict[str, int] = {}

    def add(self, x: str) -> None:
        if x not in self.p:
            self.p[x] = x
            self.r[x] = 0

    def find(self, x: str) -> str:
        self.add(x)
        if self.p[x] != x:
            self.p[x] = self.find(self.p[x])
        return self.p[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.r[ra] < self.r[rb]:
            ra, rb = rb, ra
        self.p[rb] = ra
        if self.r[ra] == self.r[rb]:
            self.r[ra] += 1

    def components(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = defaultdict(list)
        for x in self.p:
            groups[self.find(x)].append(x)
        return dict(groups)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _top_family_cards(families: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards = []
    for f in families[:12]:
        tokens = f.get("pump_tokens") or f.get("tokens") or []
        cards.append(
            {
                "id": f.get("id"),
                "hub": f.get("hub"),
                "short": f.get("hub_short") or f.get("short"),
                "size": f.get("size"),
                "pump_n": f.get("pump_n") if f.get("pump_n") is not None else f.get("token_n") or 0,
                "score": f.get("score"),
                "tokens": tokens[:6],
                "links": (f.get("top_links") or [])[:5],
            }
        )
    return cards


def load_existing_graph() -> dict[str, Any]:
    """Read-only view of families already on disk. Does not rewrite DBs."""
    fam = load_json(FAMILY_DB, {})
    addrs = load_json(ADDR_DB, {})
    if not isinstance(fam, dict):
        fam = {}
    if not isinstance(addrs, dict):
        addrs = {}
    if not (fam.get("families") or []):
        intel = load_json(ROOT / "data" / "intel" / "families.json", {})
        if isinstance(intel, dict) and (intel.get("families") or []):
            fam = intel
            if not addrs:
                intel_addrs = load_json(ROOT / "data" / "intel" / "addresses.json", {})
                if isinstance(intel_addrs, dict):
                    addrs = intel_addrs
    wiki_snap = load_json(ROOT / "data" / "wiki" / "snapshot.json", {})
    profit = load_json(DB_DIR / "profit_seeds.json", {})
    seeds = (profit.get("seeds") if isinstance(profit, dict) else None) or []
    families = list(fam.get("families") or [])
    shared = list(fam.get("shared_pumps") or fam.get("shared_tokens") or [])[:20]
    stats = fam.get("stats") or {}
    if not isinstance(stats, dict):
        stats = {}
    stats = {
        "families": stats.get("families") or len(families),
        "addresses": stats.get("addresses") or len(addrs),
        **{k: v for k, v in stats.items() if k not in {"families", "addresses"}},
    }
    return {
        "ok": True,
        "read_only": True,
        "stats": stats,
        "families": families[:60],
        "top_families": _top_family_cards(families),
        "addresses": addrs,
        "patterns": list(fam.get("patterns") or [])[:40],
        "shared_pumps": shared,
        "bridges": list(fam.get("bridges") or [])[:20],
        "profit_top": (fam.get("profit_top") or seeds)[:25],
        "wiki_stats": (wiki_snap.get("stats") if isinstance(wiki_snap, dict) else {}) or {},
        "wiki_moves": (wiki_snap.get("moves") if isinstance(wiki_snap, dict) else []) or [],
        "profit": {"skipped": True, "stats": {"seeds": len(seeds)}},
        "expand": {"skipped": True, "expanded": 0, "new_edges": 0, "new_neighbors": 0},
        "persisted": {"skipped": True, "read_only": True},
        "elapsed_sec": 0,
        "built_at": fam.get("built_at") or _now(),
    }


def build_relation_graph(
    *,
    edge_limit: int = 50000,
    profit_seeds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Walk transfer history → families + pump contacts + labeled address DB."""
    from pump_prep import graph_store as gs
    from pump_prep.labels import load_known

    known = load_known()
    uf = UnionFind()
    profit_by_addr = {
        (s.get("address") or "").lower(): s
        for s in (profit_seeds or [])
        if s.get("address")
    }

    # adjacency: addr -> Counter(neighbor -> weight)
    neigh: dict[str, Counter[str]] = defaultdict(Counter)
    # directed flows for "откуда / куда"
    outs: dict[str, Counter[str]] = defaultdict(Counter)  # from -> to
    ins: dict[str, Counter[str]] = defaultdict(Counter)   # to -> from
    # funding edges (gas/stable)
    fund_parent: dict[str, set[str]] = defaultdict(set)  # parent -> kids
    fund_child: dict[str, set[str]] = defaultdict(set)   # kid -> parents

    # pump token set
    pump_tokens: dict[str, dict[str, Any]] = {}
    for t in gs.read_jsonl(gs.TOKEN_FILE):
        tid = t.get("id") or t.get("symbol")
        if not tid:
            continue
        if t.get("had_pump") or (
            t.get("ath_chg") is not None and float(t.get("ath_chg") or 0) <= -50
        ):
            pump_tokens[str(tid)] = t

    # addr -> pump token contacts
    pump_touch: dict[str, set[str]] = defaultdict(set)
    # addr roles inferred
    roles: dict[str, set[str]] = defaultdict(set)

    edge_n = 0
    link_n = 0
    for edge in gs.read_jsonl_tail(gs.EDGE_FILE, edge_limit):
        frm = _norm(edge.get("from_addr") or edge.get("from"))
        to = _norm(edge.get("to_addr") or edge.get("to"))
        if not frm or not to or frm == to:
            continue
        sym = (edge.get("symbol") or edge.get("asset") or "").lower()
        if _spam_symbol(sym):
            continue
        edge_n += 1
        tid = edge.get("token_id") or edge.get("token_symbol") or ""
        is_self = bool(edge.get("is_token_itself"))
        direction = (edge.get("direction") or "out").lower()

        # weight: gas/stable stronger for family; token_itself = pump contact
        w = 3 if sym in GAS_STABLE else (2 if is_self else 1)
        neigh[frm][to] += w
        neigh[to][frm] += w
        link_n += 1

        # Family links ONLY via funding (gas/stable) — avoid mega-components from token spray
        if sym in GAS_STABLE and not is_self:
            uf.union(frm, to)

        if direction == "out":
            outs[frm][to] += 1
            ins[to][frm] += 1
        else:
            outs[to][frm] += 1
            ins[frm][to] += 1

        if sym in GAS_STABLE and not is_self and direction == "out":
            fund_parent[frm].add(to)
            fund_child[to].add(frm)
            roles[frm].add("funder")
            roles[to].add("funded")

        if is_self or (tid and tid in pump_tokens):
            key = str(tid or edge.get("token_symbol") or sym)
            if key:
                pump_touch[frm].add(key)
                pump_touch[to].add(key)
                roles[frm].add("pump_contact")
                roles[to].add("pump_contact")

        dep = _norm(edge.get("deployer"))
        if dep:
            roles[dep].add("deployer")

    # matches → counterparty on pumps (do NOT union through CEX)
    for m in gs.read_jsonl_tail(gs.MATCH_FILE, 5000):
        cp = _norm(m.get("counterparty"))
        dep = _norm(m.get("deployer"))
        tid = str(m.get("token_id") or m.get("symbol") or "")
        role = (m.get("match_role") or "").lower()
        if cp:
            uf.add(cp)
            if tid and (tid in pump_tokens or m.get("is_token_itself")):
                pump_touch[cp].add(tid)
                roles[cp].add("pump_contact")
            if role:
                roles[cp].add(role)
            # soft link deployer↔counterparty only if not CEX/bridge glue
            if dep and cp and role not in {"cex", "bridge"}:
                neigh[dep][cp] += 2
                neigh[cp][dep] += 2
                if role in {"seed", "mm", "fund", "watch", "accused", ""}:
                    uf.union(dep, cp)
        if dep:
            roles[dep].add("deployer")
            if tid:
                pump_touch[dep].add(tid)

    # known labels
    for addr, meta in known.items():
        a = _norm(addr)
        if not a:
            continue
        uf.add(a)
        role = (meta.get("role") or "").lower()
        if role:
            roles[a].add(role)
        if meta.get("entity"):
            roles[a].add("labeled")

    components = uf.components()
    # drop CEX/bridge hubs that glue unrelated people — split by removing them as members only
    glue = set()
    for addr, meta in known.items():
        a = _norm(addr)
        if not a:
            continue
        if (meta.get("role") or "").lower() in {"cex", "bridge"}:
            glue.add(a)
    glue.add("0x000000000000000000000000000000000000dead")

    families: list[dict[str, Any]] = []
    for root, members in components.items():
        members = [m for m in members if m not in glue]
        if len(members) < 2:
            continue
        if len(members) > 80:
            # keep densest core: top by neighbor weight inside component
            members = sorted(
                members,
                key=lambda a: sum(neigh[a].get(b, 0) for b in members if b != a),
                reverse=True,
            )[:80]
        funders = [m for m in members if "funder" in roles.get(m, ())]
        pumps = sorted({t for m in members for t in pump_touch.get(m, ())})
        labeled = [m for m in members if known.get(m)]
        score = min(
            100,
            len(members) * 3
            + len(funders) * 8
            + min(30, len(pumps) * 5)
            + len(labeled) * 4,
        )
        if score < 12 and len(members) < 3:
            continue
        hub = max(members, key=lambda a: sum(neigh[a].get(b, 0) for b in members if b != a))
        internal_links = []
        for a in members:
            for b, w in neigh[a].most_common(8):
                if b in members and a < b:
                    internal_links.append({"a": a, "b": b, "w": w})
        internal_links.sort(key=lambda x: -x["w"])
        fam_id = f"fam_{_short(hub)}"
        families.append(
            {
                "id": fam_id,
                "hub": hub,
                "hub_short": _short(hub),
                "size": len(members),
                "members": sorted(members),
                "funders": funders[:12],
                "pump_tokens": pumps[:20],
                "pump_n": len(pumps),
                "labeled_n": len(labeled),
                "score": score,
                "top_links": [
                    {
                        "a": _short(x["a"]),
                        "b": _short(x["b"]),
                        "w": x["w"],
                        "a_full": x["a"],
                        "b_full": x["b"],
                    }
                    for x in internal_links[:10]
                ],
            }
        )
    families.sort(key=lambda f: (-f["score"], -f["size"], -f["pump_n"]))

    # address cards
    addresses: dict[str, dict[str, Any]] = {}
    member_of = {m: f["id"] for f in families for m in f["members"]}

    interesting = set()
    for f in families[:80]:
        interesting.update(f["members"])
    for a, toks in pump_touch.items():
        if len(toks) >= 1:
            interesting.add(a)
    for a, kids in fund_parent.items():
        if len(kids) >= 2:
            interesting.add(a)
            interesting.update(list(kids)[:30])
    for addr, seed in profit_by_addr.items():
        interesting.add(addr)
        roles[addr] |= set(seed.get("tags") or []) | {"profit_proxy"}
        for t in seed.get("early_tokens") or []:
            pump_touch[addr].add(t)

    for addr in interesting:
        meta = known.get(addr) or {}
        tags = sorted(roles.get(addr, set()) | ({meta["role"]} if meta.get("role") else set()))
        # top counterparties
        sent_to = [{"addr": t, "short": _short(t), "n": n} for t, n in outs[addr].most_common(8)]
        recv_from = [{"addr": f, "short": _short(f), "n": n} for f, n in ins[addr].most_common(8)]
        # related = top neighbors
        related = [
            {"addr": b, "short": _short(b), "w": w, "family": member_of.get(b)}
            for b, w in neigh[addr].most_common(12)
        ]
        pumps = sorted(pump_touch.get(addr, ()))
        seed = profit_by_addr.get(addr) or {}
        if seed:
            tags = sorted(set(tags) | set(seed.get("tags") or []) | {"profit_proxy"})
            pumps = sorted(set(pumps) | set(seed.get("early_tokens") or []))
        addresses[addr] = {
            "address": addr,
            "short": _short(addr),
            "tags": tags,
            "entity": meta.get("entity") or seed.get("entity"),
            "label": meta.get("label") or seed.get("label"),
            "role": meta.get("role") or seed.get("role"),
            "family_id": member_of.get(addr),
            "pump_tokens": pumps[:15],
            "pump_n": len(pumps),
            "funded_kids": len(fund_parent.get(addr, ())),
            "funders": [_short(x) for x in list(fund_child.get(addr, ()))[:6]],
            "sent_to": sent_to,
            "recv_from": recv_from,
            "related": related,
            "profit_score": seed.get("score"),
            "early_token_n": seed.get("early_token_n"),
            "updated_at": _now(),
        }

    # cross-family patterns: families sharing pump tokens
    pump_to_fams: dict[str, set[str]] = defaultdict(set)
    for f in families:
        for t in f.get("pump_tokens") or []:
            pump_to_fams[t].add(f["id"])
    shared_pumps = []
    for t, fams in pump_to_fams.items():
        if len(fams) >= 2:
            shared_pumps.append({"token": t, "families": sorted(fams), "n": len(fams)})
    shared_pumps.sort(key=lambda x: -x["n"])

    # bridge addresses: members linking 2+ pump families via neighbor in other family
    bridges = []
    for addr, card in addresses.items():
        if addr in glue or addr.endswith("dead"):
            continue
        fams = set()
        my = card.get("family_id")
        if my:
            fams.add(my)
        for r in card.get("related") or []:
            if r.get("family"):
                fams.add(r["family"])
        if len(fams) >= 2 and card.get("pump_n", 0) >= 1:
            bridges.append(
                {
                    "address": addr,
                    "short": card["short"],
                    "families": sorted(fams),
                    "pump_n": card.get("pump_n"),
                    "tags": card.get("tags"),
                }
            )
    bridges.sort(key=lambda x: (-len(x["families"]), -int(x.get("pump_n") or 0)))

    patterns = []
    # profit-first patterns
    multi = [s for s in (profit_seeds or []) if int(s.get("early_token_n") or 0) >= 2]
    if multi:
        top = multi[0]
        patterns.append(
            {
                "type": "profit_multi",
                "score": min(100, max(85, int(top.get("score") or 50))),
                "title": (
                    f"profit {_short(top['address'])}: early×{top.get('early_token_n')} "
                    f"токенів · score {top.get('score')}"
                ),
                "address": top["address"],
                "addresses": [top["address"]],
                "tokens": top.get("early_tokens") or [],
            }
        )
        for s in multi[1:8]:
            patterns.append(
                {
                    "type": "profit_early",
                    "score": min(100, max(70, int(s.get("score") or 40))),
                    "title": (
                        f"early {_short(s['address'])}: {s.get('early_token_n')} пампів "
                        f"до ATH"
                    ),
                    "address": s["address"],
                    "addresses": [s["address"]],
                    "tokens": s.get("early_tokens") or [],
                }
            )
    if families:
        top = families[0]
        patterns.append(
            {
                "type": "largest_family",
                "score": top["score"],
                "title": f"сім'я {_short(top['hub'])}: {top['size']} адрес · pump×{top['pump_n']}",
                "family_id": top["id"],
                "addresses": [top["hub"]] + top["members"][:5],
            }
        )
    pump_fams = [f for f in families if f["pump_n"] >= 2]
    if pump_fams:
        f = pump_fams[0]
        patterns.append(
            {
                "type": "pump_family",
                "score": min(100, 50 + f["pump_n"] * 8),
                "title": f"памп-сім'я {_short(f['hub'])}: {f['pump_n']} токенів · {f['size']} адрес",
                "family_id": f["id"],
                "tokens": f["pump_tokens"][:8],
                "addresses": f["members"][:8],
            }
        )
    for sp in shared_pumps[:5]:
        patterns.append(
            {
                "type": "shared_pump",
                "score": min(100, 40 + sp["n"] * 15),
                "title": f"токен {sp['token']} зв'язує {sp['n']} сімей",
                "token": sp["token"],
                "families": sp["families"],
            }
        )
    for b in bridges[:6]:
        patterns.append(
            {
                "type": "bridge",
                "score": min(100, 45 + len(b["families"]) * 12),
                "title": f"міст {_short(b['address'])} між {len(b['families'])} сім'ями",
                "address": b["address"],
                "families": b["families"],
            }
        )
    # funding chains into pump contacts
    chain_hits = 0
    for parent, kids in list(fund_parent.items())[:200]:
        pump_kids = [k for k in kids if pump_touch.get(k)]
        if len(pump_kids) >= 2:
            chain_hits += 1
            if len(patterns) < 40:
                patterns.append(
                    {
                        "type": "funder_to_pump",
                        "score": min(100, 35 + len(pump_kids) * 10),
                        "title": f"фандер {_short(parent)} → {len(pump_kids)} pump-контактів",
                        "address": parent,
                        "kids": pump_kids[:8],
                    }
                )
    patterns.sort(key=lambda p: -int(p.get("score") or 0))

    return {
        "stats": {
            "edges_used": edge_n,
            "links": link_n,
            "families": len(families),
            "addresses": len(addresses),
            "pump_tokens": len(pump_tokens),
            "shared_pump_links": len(shared_pumps),
            "bridges": len(bridges),
            "funder_to_pump_chains": chain_hits,
            "profit_seeds": len(profit_by_addr),
            "interesting": len(interesting),
        },
        "families": families[:60],
        "addresses": addresses,
        "patterns": patterns[:40],
        "shared_pumps": shared_pumps[:20],
        "bridges": bridges[:20],
        "profit_top": (profit_seeds or [])[:25],
        "built_at": _now(),
    }


def persist_graph(result: dict[str, Any], *, wiki_sync: bool = True, limit_wiki: int = 40) -> dict[str, Any]:
    """Write rozvidka address/family DB. Only call from explicit --expand. Never from the loop."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    prev_addr = load_json(ADDR_DB, {})
    if not isinstance(prev_addr, dict):
        prev_addr = {}

    # merge history: keep first_seen
    merged = dict(prev_addr)
    for addr, card in (result.get("addresses") or {}).items():
        old = merged.get(addr) or {}
        card = dict(card)
        card["first_seen"] = old.get("first_seen") or card.get("updated_at") or _now()
        # merge tags
        tags = set(old.get("tags") or []) | set(card.get("tags") or [])
        card["tags"] = sorted(tags)
        # accumulate pump tokens
        pumps = set(old.get("pump_tokens") or []) | set(card.get("pump_tokens") or [])
        card["pump_tokens"] = sorted(pumps)[:30]
        card["pump_n"] = len(pumps)
        merged[addr] = card

    save_json(ADDR_DB, merged)
    save_json(
        FAMILY_DB,
        {
            "built_at": result.get("built_at"),
            "stats": result.get("stats"),
            "families": result.get("families") or [],
            "patterns": result.get("patterns") or [],
            "shared_pumps": result.get("shared_pumps") or [],
            "bridges": result.get("bridges") or [],
            "profit_top": result.get("profit_top") or [],
        },
    )

    # append relation findings
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with REL_DB.open("a", encoding="utf-8") as f:
        for p in (result.get("patterns") or [])[:20]:
            f.write(json.dumps({"ts": _now(), **p}, ensure_ascii=False) + "\n")

    wiki_written = []
    if wiki_sync:
        wiki.ensure()
        # clusters page summary
        lines = [
            f"families={result['stats'].get('families')} addresses={result['stats'].get('addresses')} "
            f"profit={result['stats'].get('profit_seeds')} pumps={result['stats'].get('pump_tokens')}"
        ]
        for s in (result.get("profit_top") or [])[:10]:
            lines.append(
                f"- **profit** `{_short(s.get('address'))}` sc {s.get('score')} · "
                f"early×{s.get('early_token_n')} · {', '.join((s.get('early_tokens') or [])[:5])}"
            )
        for fam in (result.get("families") or [])[:12]:
            lines.append(
                f"- **{fam['id']}** hub `{_short(fam['hub'])}` · size {fam['size']} · "
                f"pump×{fam['pump_n']} · score {fam['score']}"
            )
        for p in (result.get("patterns") or [])[:10]:
            lines.append(f"- _{p.get('type')}_ {p.get('title')}")
        path = wiki.append_page("clusters", "\n".join(lines), heading="зв'язки з історії")
        wiki_written.append({"page": "clusters", "path": path})

        # top address cards: profit first
        ranked = sorted(
            (result.get("addresses") or {}).values(),
            key=lambda c: (
                -int(c.get("profit_score") or 0),
                -int(c.get("pump_n") or 0),
                -int(c.get("funded_kids") or 0),
                -len(c.get("related") or []),
            ),
        )[:limit_wiki]
        for card in ranked:
            note = _card_note(card)
            tags = list(card.get("tags") or []) + ["family_db"]
            try:
                p = wiki.upsert_address(
                    card["address"],
                    note=note,
                    tags=tags,
                    meta={
                        "family_id": card.get("family_id"),
                        "pump_n": card.get("pump_n"),
                        "entity": card.get("entity"),
                    },
                )
                wiki_written.append({"address": card["address"], "path": p})
            except Exception as exc:
                logger.warning("wiki addr %s: %s", card.get("short"), exc)

        # memory: durable pattern hypotheses
        hyps = [p.get("title") for p in (result.get("patterns") or [])[:8]]
        if hyps:
            wiki.append_page(
                "memory",
                "\n".join(f"- {h}" for h in hyps),
                heading="гіпотези зі зв'язків",
            )

    try:
        from agents.wiki import rebuild_safe

        rebuild_safe("rozvidka-relations")
    except Exception:
        logger.debug("unified wiki skipped", exc_info=True)

    return {
        "addresses_total": len(merged),
        "families_saved": len(result.get("families") or []),
        "wiki_written": len(wiki_written),
        "wiki": wiki_written[:15],
        "stats": result.get("stats"),
    }


def _card_note(card: dict[str, Any]) -> str:
    parts = [
        f"tags: {', '.join(card.get('tags') or []) or '—'}",
        f"family: {card.get('family_id') or '—'}",
        f"entity: {card.get('entity') or '—'}",
        f"profit_score: {card.get('profit_score') or '—'}",
        f"pump_tokens ({card.get('pump_n') or 0}): {', '.join(card.get('pump_tokens') or []) or '—'}",
        f"funded_kids: {card.get('funded_kids') or 0}",
    ]
    if card.get("sent_to"):
        parts.append(
            "куда: "
            + ", ".join(f"{x['short']}×{x['n']}" for x in card["sent_to"][:5])
        )
    if card.get("recv_from"):
        parts.append(
            "откуда: "
            + ", ".join(f"{x['short']}×{x['n']}" for x in card["recv_from"][:5])
        )
    if card.get("related"):
        parts.append(
            "связанные: "
            + ", ".join(f"{x['short']}(w{x['w']})" for x in card["related"][:6])
        )
    return "\n".join(parts)


def run_family_pass(
    *,
    wiki_sync: bool = True,
    do_expand: bool = False,
    expand_limit: int | None = None,
) -> dict[str, Any]:
    """Read existing families, or opt-in Etherscan expand that rewrites rozvidka/db."""
    if not do_expand:
        return load_existing_graph()
    t0 = time.time()
    from rozvidka.profit import run_profit_pipeline

    pipeline = run_profit_pipeline(do_expand=do_expand, expand_limit=expand_limit)
    profit_seeds = (pipeline.get("profit") or {}).get("top") or []
    # full seed list for graph (reload from db if available)
    try:
        from rozvidka.profit import PROFIT_DB

        if PROFIT_DB.exists():
            profit_seeds = json.loads(PROFIT_DB.read_text(encoding="utf-8")).get("seeds") or profit_seeds
    except Exception:
        pass

    graph = build_relation_graph(profit_seeds=profit_seeds)
    persisted = persist_graph(graph, wiki_sync=wiki_sync, limit_wiki=60)
    return {
        "tool": "family_relations",
        "elapsed_sec": round(time.time() - t0, 2),
        "stats": graph.get("stats"),
        "patterns": graph.get("patterns") or [],
        "profit": pipeline.get("profit"),
        "expand": pipeline.get("expand"),
        "top_families": [
            {
                "id": f["id"],
                "hub": f["hub"],
                "short": f["hub_short"],
                "size": f["size"],
                "pump_n": f["pump_n"],
                "score": f["score"],
                "tokens": f.get("pump_tokens")[:6],
                "links": f.get("top_links")[:5],
            }
            for f in (graph.get("families") or [])[:12]
        ],
        "bridges": (graph.get("bridges") or [])[:8],
        "shared_pumps": (graph.get("shared_pumps") or [])[:8],
        "profit_top": (graph.get("profit_top") or [])[:15],
        "persisted": persisted,
        "sample_addresses": list((graph.get("addresses") or {}).values())[:8],
    }
