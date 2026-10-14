"""Family clustering: addresses linked by ≥1 transfer (per chain, drop glue)."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from intel.normalize import short
from intel.store import FAMILY_FILE, iter_all_edges, load_addresses, save_json, upsert_address

GAS = {"eth", "bnb", "sol", "matic", "usdt", "usdc", "dai", "native", "wbnb", "weth"}


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
        g: dict[str, list[str]] = defaultdict(list)
        for x in self.p:
            g[self.find(x)].append(x)
        return dict(g)


def build_families(*, max_size: int = 80) -> dict[str, Any]:
    uf = UnionFind()
    neigh: dict[str, Counter[str]] = defaultdict(Counter)
    token_touch: dict[str, set[str]] = defaultdict(set)
    edge_n = 0

    for e in iter_all_edges():
        ch = e.get("chain") or "evm"
        frm, to = e.get("from"), e.get("to")
        if not frm or not to:
            continue
        a = f"{ch}:{frm}"
        b = f"{ch}:{to}"
        sym = (e.get("symbol") or "").lower()
        # link on any transfer; weight gas/stable higher for hub pick
        w = 3 if sym in GAS else 1
        uf.union(a, b)
        neigh[a][b] += w
        neigh[b][a] += w
        edge_n += 1
        tok = e.get("token") or sym
        if tok:
            token_touch[a].add(str(tok)[:48])
            token_touch[b].add(str(tok)[:48])

    families = []
    for root, members in uf.components().items():
        if len(members) < 2:
            continue
        if len(members) > max_size:
            members = sorted(
                members,
                key=lambda x: sum(neigh[x].values()),
                reverse=True,
            )[:max_size]
        hub = max(members, key=lambda x: sum(neigh[x].get(y, 0) for y in members if y != x))
        chain = hub.split(":", 1)[0]
        addr = hub.split(":", 1)[1] if ":" in hub else hub
        pumps = sorted({t for m in members for t in token_touch.get(m, ())})
        score = min(100, len(members) * 3 + min(30, len(pumps)))
        fam_id = f"fam_{chain}_{short(addr).replace('…', '')}"
        families.append(
            {
                "id": fam_id,
                "chain": chain,
                "hub": addr,
                "hub_key": hub,
                "short": short(addr),
                "size": len(members),
                "members": members,
                "tokens": pumps[:25],
                "token_n": len(pumps),
                "score": score,
            }
        )
        for m in members:
            ch2, ad2 = m.split(":", 1) if ":" in m else ("evm", m)
            upsert_address(ch2, ad2, family_id=fam_id, tags=["family"])

    families.sort(key=lambda f: (-f["score"], -f["size"]))
    _attach_patron_frames(families[:100])

    # token activity net: token → families
    tok_fams: dict[str, set[str]] = defaultdict(set)
    for f in families:
        for t in f.get("tokens") or []:
            tok_fams[t].add(f["id"])
    shared = [
        {"token": t, "families": sorted(fs), "n": len(fs)}
        for t, fs in tok_fams.items()
        if len(fs) >= 2
    ]
    shared.sort(key=lambda x: -x["n"])

    out = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "edges_used": edge_n,
        "families": families[:100],
        "shared_tokens": shared[:40],
        "stats": {
            "families": len(families),
            "edges_used": edge_n,
            "addresses": len(load_addresses()),
            "shared_token_links": len(shared),
        },
    }
    save_json(FAMILY_FILE, out)
    return out


def _attach_patron_frames(families: list[dict[str, Any]]) -> None:
    """Patron + numeric frames + go/submit/where on each saved family."""
    if not families:
        return
    try:
        from agents.frames import GAS_STABLE, RECENT_SEC, attach, fnum
    except Exception:
        return
    import time

    member_fam: dict[str, str] = {}
    for f in families:
        fid = str(f.get("id") or "")
        for m in f.get("members") or []:
            member_fam[str(m)] = fid
    out_w: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    amts: dict[str, list[float]] = defaultdict(list)
    rec: dict[str, list[float]] = defaultdict(list)
    tss: dict[str, list[int]] = defaultdict(list)
    rec_n: dict[str, int] = defaultdict(int)
    now_ts = time.time()
    for e in iter_all_edges():
        ch = e.get("chain") or "evm"
        frm, to = e.get("from"), e.get("to")
        if not frm or not to:
            continue
        a, b = f"{ch}:{frm}", f"{ch}:{to}"
        fid = member_fam.get(a) or member_fam.get(b)
        if not fid:
            continue
        amt = fnum(e.get("amount"))
        ts = int(e.get("timestamp") or 0)
        if amt is not None:
            amts[fid].append(amt)
            if ts and (now_ts - ts) <= RECENT_SEC:
                rec[fid].append(amt)
                rec_n[fid] += 1
        if ts:
            tss[fid].append(ts)
        if member_fam.get(a) == fid and member_fam.get(b) == fid:
            sym = (e.get("symbol") or "").lower()
            w = 3.0 if (sym in GAS_STABLE or sym in GAS) else 1.0
            out_w[fid][a] += w
    addrs = load_addresses()
    for f in families:
        fid = str(f.get("id") or "")
        attach(
            f,
            addrs=addrs,
            out_weight=dict(out_w.get(fid) or {}),
            amounts=amts.get(fid) or [],
            recent=rec.get(fid) or [],
            timestamps=tss.get(fid) or [],
            recent_n=rec_n.get(fid) or 0,
            now_ts=now_ts,
        )
        pat = f.get("patron") or {}
        key = str(pat.get("key") or "")
        if pat.get("confident") and ":" in key:
            ch2, ad2 = key.split(":", 1)
            upsert_address(ch2, ad2, role="patron", tags=["patron", "family"])
