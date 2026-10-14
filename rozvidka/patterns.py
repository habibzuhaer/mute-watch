"""Pattern watchbook — track groups/addresses across turns and find regularities."""

from __future__ import annotations

import json
import logging
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rozvidka.config import DATA_DIR

logger = logging.getLogger(__name__)

WATCHBOOK_FILE = DATA_DIR / "watchbook.json"
FINDINGS_FILE = DATA_DIR / "findings.jsonl"

CEX_ROLES = {"cex", "bridge"}
GAS_STABLE = {
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


def _short(addr: str | None) -> str:
    a = (addr or "").strip().lower()
    if len(a) < 10:
        return a
    return a[:4] + a[-4:]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_watchbook() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not WATCHBOOK_FILE.exists():
        return {"version": 1, "subjects": {}, "updated_at": None}
    try:
        return json.loads(WATCHBOOK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "subjects": {}, "updated_at": None}


def save_watchbook(book: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    book["updated_at"] = _now()
    tmp = WATCHBOOK_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(WATCHBOOK_FILE)


def append_finding(row: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with FINDINGS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


# ---------------------------------------------------------------------------
# Snapshot builders (what is happening right now)
# ---------------------------------------------------------------------------


def snapshot_graph(*, edge_limit: int = 14000) -> dict[str, Any]:
    """Build a compact live snapshot for pattern engines."""
    from pump_prep import graph_store as gs
    from pump_prep.clusters import build_deployer_clusters
    from pump_prep.labels import load_known

    known = load_known()
    now = time.time()

    # --- funder families (gas/stable outs, exclude CEX parents) ---
    parents: dict[str, set[str]] = defaultdict(set)
    parent_sym: dict[str, Counter[str]] = defaultdict(Counter)
    for edge in gs.read_jsonl_tail(gs.EDGE_FILE, edge_limit):
        if edge.get("is_token_itself"):
            continue
        sym = (edge.get("symbol") or edge.get("asset") or "").lower()
        if sym not in GAS_STABLE:
            continue
        frm = (edge.get("from_addr") or edge.get("from") or "").lower()
        to = (edge.get("to_addr") or edge.get("to") or "").lower()
        if not frm.startswith("0x") or not to.startswith("0x") or frm == to:
            continue
        direction = (edge.get("direction") or "out").lower()
        if direction != "out":
            continue
        meta = known.get(frm) or {}
        if (meta.get("role") or "").lower() in CEX_ROLES:
            continue
        parents[frm].add(to)
        parent_sym[frm][sym] += 1

    families = []
    for parent, kids in parents.items():
        if len(kids) < 4:
            continue
        meta = known.get(parent) or {}
        role = (meta.get("role") or "").lower()
        known_boost = 18 if role in {"seed", "mm", "fund", "watch", "accused"} or meta.get("entity") else 0
        # Prefer multi-asset funding (ETH+USDT) over single-token spray
        assets = len(parent_sym[parent])
        score = min(100, len(kids) * 3 + known_boost + assets * 4)
        if score < 20 and not known_boost:
            continue
        families.append(
            {
                "address": parent,
                "short": _short(parent),
                "kind": "funder_family",
                "children": len(kids),
                "sample_kids": sorted({_short(k) for k in kids})[:8],
                "assets": dict(parent_sym[parent].most_common(4)),
                "entity": meta.get("entity"),
                "role": meta.get("role"),
                "label": meta.get("label"),
                "score": score,
            }
        )
    families.sort(key=lambda x: (-x["score"], -x["children"]))

    # --- deployer clusters ---
    dep = build_deployer_clusters()
    deployers = []
    for c in dep.get("clusters") or []:
        tc = int(c.get("token_count") or 0)
        pc = int(c.get("pump_count") or 0)
        if tc < 2 and pc < 1:
            continue
        addr = (c.get("deployer") or "").lower()
        meta = known.get(addr) or {}
        score = min(100, int(c.get("score_hint") or 0))
        deployers.append(
            {
                "address": addr,
                "short": _short(addr),
                "kind": "deployer_cluster",
                "children": tc,
                "pump_count": pc,
                "symbols": (c.get("symbols") or [])[:10],
                "entity": meta.get("entity") or ((c.get("entities") or [None])[0]),
                "score": score,
            }
        )
    deployers.sort(key=lambda x: (-x["score"], -x["pump_count"], -x["children"]))

    # --- recent signals / entity bursts ---
    signals = gs.read_jsonl_tail(gs.SIGNAL_FILE, 500)
    by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fresh_sigs: list[dict[str, Any]] = []
    for s in signals:
        ent = s.get("match_entity") or ""
        if not ent:
            continue
        row = {
            "entity": ent,
            "symbol": s.get("symbol"),
            "kind": s.get("signal_kind") or s.get("kind"),
            "tier": s.get("tier"),
            "score": s.get("score"),
            "timestamp": s.get("timestamp"),
            "saved_at": s.get("saved_at"),
        }
        by_entity[ent].append(row)
        # prefer saved_at freshness (live prep)
        age = _age_hours(s.get("saved_at"), s.get("timestamp"), now=now)
        if age is not None and age <= 72:
            fresh_sigs.append({**row, "age_h": round(age, 1)})

    bursts = []
    for ent, rows in by_entity.items():
        symbols = {r.get("symbol") for r in rows if r.get("symbol")}
        if len(rows) < 3 or len(symbols) < 2:
            continue
        # skip pure CEX noise unless mixed with non-cex kinds
        kinds = {r.get("kind") for r in rows}
        if kinds <= {"cex_deposit", "cex_touch"} and not any(
            x in (ent or "").lower() for x in ("dwf", "gotbit", "wintermute", "gsr", "jump", "cls")
        ):
            continue
        score = min(100, len(rows) * 4 + len(symbols) * 6)
        bursts.append(
            {
                "entity": ent,
                "kind": "entity_burst",
                "hits": len(rows),
                "symbols": sorted(symbols)[:12],
                "kinds": sorted(k for k in kinds if k),
                "score": score,
                "short": ent[:24],
                "address": None,
            }
        )
    bursts.sort(key=lambda x: -x["score"])

    # --- co-occurrence: wallets that share ≥2 tokens via matches ---
    by_token: dict[str, set[str]] = defaultdict(set)
    addr_tokens: dict[str, set[str]] = defaultdict(set)
    for m in gs.read_jsonl_tail(gs.MATCH_FILE, 4000):
        tid = m.get("token_id") or m.get("symbol")
        cp = (m.get("counterparty") or "").lower()
        if not tid or not cp.startswith("0x"):
            continue
        role = (m.get("match_role") or "").lower()
        if role in CEX_ROLES:
            continue
        by_token[str(tid)].add(cp)
        addr_tokens[cp].add(str(tid))

    # addresses appearing on many tokens
    serial = []
    for addr, toks in addr_tokens.items():
        if len(toks) < 3:
            continue
        meta = known.get(addr) or {}
        if (meta.get("role") or "").lower() in CEX_ROLES:
            continue
        score = min(100, len(toks) * 12)
        serial.append(
            {
                "address": addr,
                "short": _short(addr),
                "kind": "serial_touch",
                "children": len(toks),
                "tokens": sorted(toks)[:10],
                "entity": meta.get("entity"),
                "role": meta.get("role"),
                "score": score,
            }
        )
    serial.sort(key=lambda x: (-x["score"], -x["children"]))

    # pair co-occurrence
    pair_count: Counter[tuple[str, str]] = Counter()
    for tid, addrs in by_token.items():
        alist = sorted(addrs)
        if len(alist) > 40:
            continue
        for i, a in enumerate(alist):
            for b in alist[i + 1 : i + 12]:
                pair_count[(a, b)] += 1
    pairs = []
    for (a, b), n in pair_count.most_common(40):
        if n < 2:
            continue
        pairs.append(
            {
                "a": a,
                "b": b,
                "short_a": _short(a),
                "short_b": _short(b),
                "shared_tokens": n,
                "kind": "cooccur_pair",
                "score": min(100, n * 25),
            }
        )

    return {
        "families": families[:40],
        "deployers": deployers[:30],
        "bursts": bursts[:20],
        "serial": serial[:20],
        "pairs": pairs[:20],
        "fresh_signals": sorted(fresh_sigs, key=lambda x: x.get("age_h") or 999)[:25],
        "stats": {
            "families": len(families),
            "deployers": len(deployers),
            "bursts": len(bursts),
            "serial": len(serial),
            "pairs": len(pairs),
            "fresh_signals": len(fresh_sigs),
        },
    }


def _age_hours(saved_at: Any, timestamp: Any, *, now: float) -> float | None:
    if saved_at:
        try:
            # 2026-08-21T20:59:20.460948+00:00
            dt = datetime.fromisoformat(str(saved_at).replace("Z", "+00:00"))
            return max(0.0, (now - dt.timestamp()) / 3600)
        except Exception:
            pass
    if timestamp:
        try:
            return max(0.0, (now - int(timestamp)) / 3600)
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Watchbook update + findings
# ---------------------------------------------------------------------------



def _finding(turn: int, typ: str, subj: dict[str, Any], prev: dict[str, Any], title: str) -> dict[str, Any]:
    return {
        "turn": turn,
        "type": typ,
        "score": int(subj.get("score") or prev.get("score") or 40),
        "title": title,
        "addresses": [subj["address"]] if subj.get("address") else [],
        "short": subj.get("short") or prev.get("short"),
        "detail": {
            "kind": subj.get("kind"),
            "metric": prev.get("metric"),
            "stable_streak": prev.get("stable_streak"),
            "grew_streak": prev.get("grew_streak"),
            "entity": subj.get("entity") or prev.get("entity"),
            "extra": prev.get("extra"),
        },
    }


def analyze_turn(turn: int) -> dict[str, Any]:
    """Snapshot + watchbook with proper wakeup detection."""
    snap = snapshot_graph()
    book = load_watchbook()
    subjects: dict[str, Any] = book.setdefault("subjects", {})

    # Capture silence before update
    pre_silence = {sid: int(s.get("silence_streak") or 0) for sid, s in subjects.items()}

    # Temporarily use analyze but with wakeup patch via pre_silence
    # Inline update for correctness
    findings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def touch(subj: dict[str, Any], *, metric_key: str = "children") -> tuple[str, dict[str, Any]]:
        addr = (subj.get("address") or subj.get("entity") or "").lower()
        kind = subj.get("kind") or "address"
        sid = f"{kind}:{addr}"
        seen_ids.add(sid)
        prev = subjects.get(sid) or {
            "id": sid,
            "address": subj.get("address"),
            "entity": subj.get("entity"),
            "short": subj.get("short") or _short(subj.get("address")) or str(subj.get("entity") or "")[:12],
            "kind": kind,
            "seen_turns": 0,
            "stable_streak": 0,
            "silence_streak": 0,
            "grew_streak": 0,
            "metric": 0,
            "score": 0,
            "last_turn": 0,
            "history": [],
        }
        was_silent = pre_silence.get(sid, 0)
        metric = int(subj.get(metric_key) or subj.get("hits") or subj.get("children") or 0)
        old = int(prev.get("metric") or 0)
        if prev.get("seen_turns", 0) == 0:
            event = "new"
        elif metric > old:
            event = "grew"
            prev["grew_streak"] = int(prev.get("grew_streak") or 0) + 1
            prev["stable_streak"] = 0
        elif metric == old and old > 0:
            event = "stable"
            prev["stable_streak"] = int(prev.get("stable_streak") or 0) + 1
            prev["grew_streak"] = 0
        elif metric < old:
            event = "shrunk"
            prev["grew_streak"] = 0
            prev["stable_streak"] = 0
        else:
            event = "seen"
        prev["silence_streak"] = 0
        prev["seen_turns"] = int(prev.get("seen_turns") or 0) + 1
        prev["metric"] = metric
        prev["score"] = int(subj.get("score") or prev.get("score") or 0)
        prev["last_turn"] = turn
        prev["entity"] = subj.get("entity") or prev.get("entity")
        prev["role"] = subj.get("role") or prev.get("role")
        prev["label"] = subj.get("label") or prev.get("label")
        prev["extra"] = {
            k: subj.get(k)
            for k in ("pump_count", "symbols", "assets", "tokens", "kinds", "sample_kids", "hits")
            if subj.get(k) is not None
        }
        hist = list(prev.get("history") or [])
        hist.append({"turn": turn, "event": event, "metric": metric})
        prev["history"] = hist[-24:]
        subjects[sid] = prev

        if was_silent >= 3:
            findings.append(
                {
                    "turn": turn,
                    "type": "wakeup",
                    "score": min(90, 50 + was_silent * 4),
                    "title": f"прокинувся {prev.get('short')} після {was_silent} обертів тиші",
                    "addresses": [prev.get("address")] if prev.get("address") else [],
                    "short": prev.get("short"),
                    "detail": {"sid": sid, "was_silent": was_silent, "event": event, "metric": metric},
                }
            )
        return event, prev

    for fam in (snap.get("families") or [])[:30]:
        ev, prev = touch(fam)
        if ev == "new" and fam["score"] >= 30:
            findings.append(_finding(turn, "new_family", fam, prev, f"нова сім'я {_short(fam['address'])}: {fam['children']} дітей · score {fam['score']}"))
        elif ev == "grew":
            findings.append(_finding(turn, "family_grew", fam, prev, f"сім'я {_short(fam['address'])} → {fam['children']} дітей (grew×{prev.get('grew_streak')})"))
        elif ev == "stable" and int(prev.get("stable_streak") or 0) in (3, 6, 10, 15):
            findings.append(_finding(turn, "family_stable", fam, prev, f"сім'я {_short(fam['address'])} тримається {prev.get('stable_streak')}×"))

    for dep in (snap.get("deployers") or [])[:25]:
        ev, prev = touch(dep)
        if ev == "new" and ((dep.get("pump_count") or 0) >= 1 or dep["children"] >= 3):
            findings.append(_finding(turn, "new_deployer", dep, prev, f"деплоєр {_short(dep['address'])}: tok×{dep['children']} pump×{dep.get('pump_count')}"))
        elif ev == "grew":
            findings.append(_finding(turn, "deployer_grew", dep, prev, f"деплоєр {_short(dep['address'])} зріс → tok×{dep['children']}"))
        elif ev == "stable" and int(prev.get("stable_streak") or 0) in (4, 8, 12) and (dep.get("pump_count") or 0) >= 2:
            findings.append(_finding(turn, "deployer_stable", dep, prev, f"деплоєр {_short(dep['address'])} стабільний {prev.get('stable_streak')}× · pump×{dep.get('pump_count')}"))

    for ser in (snap.get("serial") or [])[:20]:
        ev, prev = touch(ser)
        if ser["score"] >= 36 and (ev in {"new", "grew"} or ser["children"] >= 4):
            findings.append(_finding(turn, "serial_touch", ser, prev, f"серія {_short(ser['address'])}: {ser['children']} токенів"))

    for burst in (snap.get("bursts") or [])[:15]:
        burst_subj = {
            "address": None,
            "entity": burst["entity"],
            "short": burst.get("short"),
            "kind": "entity_burst",
            "children": burst["hits"],
            "hits": burst["hits"],
            "symbols": burst.get("symbols"),
            "kinds": burst.get("kinds"),
            "score": burst["score"],
        }
        ev, prev = touch(burst_subj, metric_key="hits")
        if burst["score"] >= 40 and (
            ev in {"new", "grew"}
            or (ev == "stable" and int(prev.get("stable_streak") or 0) in (5, 10, 20))
        ):
            findings.append(
                _finding(
                    turn,
                    "entity_burst",
                    burst_subj,
                    prev,
                    f"сплеск «{burst['entity']}»: {burst['hits']} · symb {len(burst.get('symbols') or [])}",
                )
            )

    for pair in (snap.get("pairs") or [])[:12]:
        if pair.get("shared_tokens", 0) >= 2:
            findings.append(
                {
                    "turn": turn,
                    "type": "cooccur",
                    "score": pair["score"],
                    "title": f"разом {_short(pair['a'])}+{_short(pair['b'])} у {pair['shared_tokens']} токенах",
                    "addresses": [pair["a"], pair["b"]],
                    "short": f"{pair['short_a']}/{pair['short_b']}",
                    "detail": pair,
                }
            )

    for sid, prev in subjects.items():
        if sid in seen_ids:
            continue
        if int(prev.get("last_turn") or 0) <= 0:
            continue
        prev["silence_streak"] = int(prev.get("silence_streak") or 0) + 1
        prev["stable_streak"] = 0
        prev["grew_streak"] = 0
        subjects[sid] = prev
        ss = prev["silence_streak"]
        if ss in (3, 5, 8, 11) or (ss >= 15 and ss % 5 == 0):
            findings.append(
                {
                    "turn": turn,
                    "type": "silence",
                    "score": min(70, 18 + ss * 4),
                    "title": f"тиша {prev.get('short')}: уже {ss} обертів",
                    "addresses": [prev.get("address")] if prev.get("address") else [],
                    "short": prev.get("short"),
                    "detail": {"sid": sid, "silence_streak": ss, "kind": prev.get("kind")},
                }
            )

    findings.sort(key=lambda f: -int(f.get("score") or 0))
    uniq: list[dict[str, Any]] = []
    seen_k: set[tuple] = set()
    for f in findings:
        key = (f.get("type"), f.get("short") or f.get("title"))
        if key in seen_k:
            continue
        seen_k.add(key)
        uniq.append(f)
    findings = uniq[:28]

    book["subjects"] = subjects
    book["last_turn"] = turn
    book["last_stats"] = snap.get("stats")
    save_watchbook(book)
    for f in findings:
        append_finding({**f, "saved_at": _now()})

    watched = sorted(
        subjects.values(),
        key=lambda s: (-int(s.get("score") or 0), -int(s.get("seen_turns") or 0)),
    )[:30]

    # Regularities summary (deterministic)
    regularities = _regularities(findings, watched, snap)

    return {
        "turn": turn,
        "snapshot_stats": snap.get("stats"),
        "findings": findings,
        "regularities": regularities,
        "watched": watched,
        "fresh_signals": snap.get("fresh_signals") or [],
        "top_families": (snap.get("families") or [])[:8],
        "top_deployers": (snap.get("deployers") or [])[:8],
        "top_serial": (snap.get("serial") or [])[:8],
        "top_pairs": (snap.get("pairs") or [])[:8],
        "top_bursts": (snap.get("bursts") or [])[:8],
    }


def _regularities(
    findings: list[dict[str, Any]],
    watched: list[dict[str, Any]],
    snap: dict[str, Any],
) -> list[dict[str, Any]]:
    """Higher-level pattern statements for the human / LLM."""
    out: list[dict[str, Any]] = []
    by_type: Counter[str] = Counter(f.get("type") for f in findings)
    if by_type.get("wakeup"):
        out.append({"id": "wakeups", "text": f"Прокинулись суб'єкти: {by_type['wakeup']}", "weight": 80})
    stable = [w for w in watched if int(w.get("stable_streak") or 0) >= 3]
    if stable:
        names = ", ".join(str(w.get("short")) for w in stable[:5])
        out.append({"id": "holding", "text": f"Тримаються ≥3 оберти: {names}", "weight": 70})
    silent = [w for w in watched if int(w.get("silence_streak") or 0) >= 5]
    if silent:
        names = ", ".join(str(w.get("short")) for w in silent[:5])
        out.append({"id": "deep_silence", "text": f"Глибока тиша (≥5): {names}", "weight": 55})
    pumps = [d for d in (snap.get("deployers") or []) if int(d.get("pump_count") or 0) >= 3]
    if pumps:
        names = ", ".join(f"{d['short']}×{d['pump_count']}" for d in pumps[:4])
        out.append({"id": "pump_factories", "text": f"Фабрики пампів: {names}", "weight": 85})
    pairs = [p for p in (snap.get("pairs") or []) if int(p.get("shared_tokens") or 0) >= 3]
    if pairs:
        out.append(
            {
                "id": "tight_pairs",
                "text": f"Щільні пари кошельків (≥3 токени разом): {len(pairs)}",
                "weight": 75,
            }
        )
    bursts = snap.get("bursts") or []
    if bursts:
        top = bursts[0]
        out.append(
            {
                "id": "top_burst",
                "text": f"Найгучніший ентіті: {top.get('entity')} ({top.get('hits')} хітів)",
                "weight": int(top.get("score") or 50),
            }
        )
    fresh = snap.get("fresh_signals") or []
    if fresh:
        out.append(
            {
                "id": "fresh",
                "text": f"Свіжі сигнали ≤72г: {len(fresh)} (напр. {fresh[0].get('symbol')} / {fresh[0].get('entity')})",
                "weight": 65,
            }
        )
    if not out:
        out.append({"id": "quiet", "text": "Явних закономірностей мало — тихий оберт / шум", "weight": 20})
    out.sort(key=lambda x: -int(x.get("weight") or 0))
    return out


def is_noise_turn(analysis: dict[str, Any]) -> bool:
    findings = analysis.get("findings") or []
    regs = analysis.get("regularities") or []
    strong = [f for f in findings if int(f.get("score") or 0) >= 55 and f.get("type") not in {"silence", "family_stable"}]
    if strong:
        return False
    if regs and regs[0].get("id") == "quiet":
        return True
    return len(strong) == 0 and not any(r.get("weight", 0) >= 70 for r in regs)
