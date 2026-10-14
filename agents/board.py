"""Real kanban: persistent cards, workflow columns, synced from live agent state."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any

from agents.config import BOARD_FILE, DATA_DIR, HANDS_FILE, KANBAN_FILE, ROOT
from agents.modules import ORDER

OWNERS = ("mute", "intel", "rozvidka", "trades", "orch")
STATUSES = ("backlog", "doing", "hand", "done")
HAND_KINDS = {"рука", "hand", "net_rpc", "net_llm", "net_tg"}
OWNER_ROLE = {
    "mute": "збір",
    "intel": "звʼязки",
    "rozvidka": "патерни",
    "trades": "папір",
    "orch": "диригент",
}
COL_ROLE = {
    **OWNER_ROLE,
    "hand": "рука",
    "backlog": "черга",
    "doing": "в роботі",
    "done": "готово",
}
_PER_COL = 60
_DONE_KEEP = 80
_AUDIT_MAX = 400


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _owner(src: str) -> str:
    s = (src or "orch").strip().lower()
    return s if s in OWNERS else "orch"


def _status(raw: str | None, *, kind: str = "") -> str:
    s = (raw or "").strip().lower()
    if s in STATUSES:
        return s
    if s == "hand" or kind in HAND_KINDS:
        return "hand"
    return "doing"


EPHEMERAL_KINDS = {"turn", "цикл", "дія", "wiki", "orch", "робота", "collect", "підняв"}


def _ref(src: str, kind: str, title: str, ref: str) -> str:
    r = (ref or "").strip()
    owner = _owner(src)
    kind = (kind or "дія").strip() or "дія"
    title = (title or "")[:80]
    if kind in EPHEMERAL_KINDS and (not r or r == title or r.startswith(title[:24])):
        return f"{owner}:{kind}"[:80]
    if r:
        return r[:80]
    if kind in HAND_KINDS:
        return f"hand:{owner}:{(title or '')[:48]}"[:80]
    return f"{owner}:{kind}"[:80]


def _empty_store() -> dict[str, Any]:
    return {"version": 2, "updated_at": _now(), "cards": {}}


def _load_store() -> dict[str, Any]:
    _ensure()
    if KANBAN_FILE.exists():
        try:
            data = json.loads(KANBAN_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("cards"), dict):
                return data
        except Exception:
            pass
    store = _migrate_legacy()
    _save_store(store)
    return store


def _save_store(store: dict[str, Any]) -> None:
    _ensure()
    store["version"] = 2
    store["updated_at"] = _now()
    cards = store.get("cards") or {}
    done = [c for c in cards.values() if (c.get("status") or "") == "done"]
    done.sort(key=lambda x: x.get("ts") or "", reverse=True)
    drop = {c["id"] for c in done[_DONE_KEEP:]}
    if drop:
        store["cards"] = {i: c for i, c in cards.items() if i not in drop}
    tmp = KANBAN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(KANBAN_FILE)
    _sync_hands_file(store)


def _sync_hands_file(store: dict[str, Any]) -> None:
    hands = {
        cid: dict(c)
        for cid, c in (store.get("cards") or {}).items()
        if (c.get("status") or "") == "hand"
    }
    tmp = HANDS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(hands, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(HANDS_FILE)


def _load_hands() -> dict[str, dict[str, Any]]:
    store = _load_store()
    return {
        cid: dict(c)
        for cid, c in (store.get("cards") or {}).items()
        if (c.get("status") or "") == "hand"
    }


def _save_hands(hands: dict[str, dict[str, Any]]) -> None:
    store = _load_store()
    cards = store.get("cards") or {}
    keep = set(hands)
    for cid, card in list(cards.items()):
        if (card.get("status") or "") == "hand" and cid not in keep:
            card["status"] = "doing"
            card["col"] = "doing"
            card["open"] = False
            card["acked_at"] = _now()
            cards[cid] = card
    for cid, card in hands.items():
        row = dict(card)
        row["id"] = cid
        row["status"] = "hand"
        row["col"] = "hand"
        row["open"] = True
        cards[cid] = row
    store["cards"] = cards
    _save_store(store)


def _by_ref(store: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for card in (store.get("cards") or {}).values():
        r = str(card.get("ref") or "").strip()
        if r:
            out[r] = card
    return out


def _migrate_legacy() -> dict[str, Any]:
    """Hands file only. jsonl is an audit tape, not the live board."""
    store = _empty_store()
    cards: dict[str, dict[str, Any]] = {}
    if HANDS_FILE.exists():
        try:
            raw = json.loads(HANDS_FILE.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        if isinstance(raw, dict):
            for hid, row in raw.items():
                card = _normalize_card(row if isinstance(row, dict) else {})
                card["id"] = str(hid or card["id"])
                card["status"] = "hand"
                card["col"] = "hand"
                card["open"] = True
                cards[card["id"]] = card
    # last write per ref wins
    latest: dict[str, dict[str, Any]] = {}
    for card in cards.values():
        key = str(card.get("ref") or card["id"])
        prev = latest.get(key)
        if prev is None or str(card.get("ts") or "") >= str(prev.get("ts") or ""):
            latest[key] = card
    store["cards"] = {c["id"]: c for c in latest.values()}
    return store


def _normalize_card(row: dict[str, Any]) -> dict[str, Any]:
    src = _owner(str(row.get("src") or row.get("owner") or "orch"))
    kind = str(row.get("kind") or "дія")
    title = str(row.get("title") or kind)[:180]
    col_raw = str(row.get("col") or row.get("status") or "")
    if col_raw in STATUSES:
        status = col_raw
    elif col_raw == "hand" or kind in HAND_KINDS or row.get("open"):
        status = "hand"
    elif col_raw in OWNERS:
        status = "doing"
        src = col_raw
    else:
        status = "doing"
    cid = str(row.get("id") or uuid.uuid4().hex[:12])
    ref = _ref(src, kind, title, str(row.get("ref") or ""))
    return {
        "id": cid,
        "ts": str(row.get("ts") or _now()),
        "src": src,
        "owner": src,
        "col": status,
        "status": status,
        "kind": kind[:80],
        "title": title,
        "detail": str(row.get("detail") or "")[:400],
        "level": str(row.get("level") or "").upper()[:16],
        "ref": ref,
        "open": status == "hand",
        "manual": bool(row.get("manual")),
        "system": bool(row.get("system")),
        "acked_at": row.get("acked_at"),
    }


def _audit(card: dict[str, Any], op: str) -> None:
    _ensure()
    row = {k: card.get(k) for k in ("id", "ts", "src", "col", "status", "kind", "title", "detail", "level", "ref")}
    row["op"] = op
    row["open"] = card.get("status") == "hand"
    with BOARD_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _upsert(
    src: str,
    title: str,
    *,
    kind: str = "дія",
    detail: str = "",
    level: str = "",
    ref: str = "",
    status: str = "doing",
    system: bool = False,
    manual: bool | None = None,
    force_status: bool = False,
) -> dict[str, Any]:
    store = _load_store()
    cards = store.setdefault("cards", {})
    owner = _owner(src)
    kind = (kind or "дія")[:80]
    title = (title or kind)[:180]
    detail = (detail or "")[:400]
    status = _status(status, kind=kind)
    key = _ref(owner, kind, title, ref)
    index = _by_ref(store)
    old = index.get(key)
    now = _now()
    if old:
        card = dict(old)
        card["ts"] = now
        card["src"] = owner
        card["owner"] = owner
        card["kind"] = kind
        card["title"] = title
        card["detail"] = detail
        card["level"] = (level or card.get("level") or "").upper()[:16]
        card["ref"] = key
        if system:
            card["system"] = True
        keep = bool(card.get("manual")) and not force_status
        if not keep:
            card["status"] = status
        card["col"] = card["status"]
        card["open"] = card["status"] == "hand"
        if manual is True:
            card["manual"] = True
        cards[card["id"]] = card
        store["cards"] = cards
        _save_store(store)
        _audit(card, "upsert")
        return card
    card = {
        "id": uuid.uuid4().hex[:12],
        "ts": now,
        "src": owner,
        "owner": owner,
        "col": status,
        "status": status,
        "kind": kind,
        "title": title,
        "detail": detail,
        "level": (level or "").upper()[:16],
        "ref": key,
        "open": status == "hand",
        "manual": bool(manual),
        "system": bool(system),
        "acked_at": None,
    }
    cards[card["id"]] = card
    store["cards"] = cards
    _save_store(store)
    _audit(card, "post")
    return card


def post(
    src: str,
    title: str,
    *,
    kind: str = "дія",
    detail: str = "",
    level: str = "",
    ref: str = "",
    col: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    owner = _owner(src)
    st = status
    if col:
        c = col.strip().lower()
        if c in STATUSES:
            st = c
        elif c in OWNERS:
            owner = c
    if st is None:
        st = "hand" if kind in HAND_KINDS else "doing"
    return _upsert(owner, title, kind=kind, detail=detail, level=level, ref=ref, status=st)


def raise_hand(
    src: str,
    question: str,
    *,
    kind: str = "рука",
    detail: str = "",
    ref: str = "",
) -> dict[str, Any]:
    return _upsert(
        src,
        question,
        kind=kind or "рука",
        detail=detail,
        ref=ref,
        status="hand",
        force_status=True,
    )


def add(
    src: str,
    title: str,
    *,
    kind: str = "нотатка",
    detail: str = "",
    status: str = "backlog",
) -> dict[str, Any]:
    return _upsert(
        src,
        title,
        kind=kind,
        detail=detail,
        ref=f"note:{_owner(src)}:{uuid.uuid4().hex[:8]}",
        status=status or "backlog",
        manual=True,
        force_status=True,
    )


def get(card_id: str) -> dict[str, Any] | None:
    store = _load_store()
    card = (store.get("cards") or {}).get(card_id)
    return dict(card) if card else None


def move(card_id: str, status: str, *, follow: bool = False) -> dict[str, Any]:
    store = _load_store()
    cards = store.get("cards") or {}
    card = cards.get(card_id)
    if not card:
        return {"ok": False, "error": "not found", "id": card_id}
    st = _status(status, kind=str(card.get("kind") or ""))
    card = dict(card)
    card["status"] = st
    card["col"] = st
    card["open"] = st == "hand"
    card["ts"] = _now()
    card["manual"] = not follow
    if st != "hand":
        card["acked_at"] = _now()
    cards[card_id] = card
    store["cards"] = cards
    _save_store(store)
    _audit(card, "move")
    if st != "hand" and (card.get("src") == "rozvidka" or "Ollama" in str(card.get("title") or "")):
        _clear_rozvidka_hand()
    return {"ok": True, "card": card}


def done(card_id: str) -> dict[str, Any]:
    return move(card_id, "done")


def follow(card_id: str) -> dict[str, Any]:
    store = _load_store()
    cards = store.get("cards") or {}
    card = cards.get(card_id)
    if not card:
        return {"ok": False, "error": "not found", "id": card_id}
    card = dict(card)
    card["manual"] = False
    card["ts"] = _now()
    cards[card_id] = card
    store["cards"] = cards
    _save_store(store)
    return {"ok": True, "card": card}


def ack(hand_id: str) -> dict[str, Any]:
    store = _load_store()
    cards = store.get("cards") or {}
    card = cards.get(hand_id)
    if not card:
        return {"ok": True, "id": hand_id, "acked": False}
    card = dict(card)
    card["status"] = "doing"
    card["col"] = "doing"
    card["open"] = False
    card["manual"] = True
    card["acked_at"] = _now()
    card["ts"] = _now()
    cards[hand_id] = card
    store["cards"] = cards
    _save_store(store)
    _audit(card, "ack")
    if card.get("src") == "rozvidka" or "Ollama" in str(card.get("title") or ""):
        _clear_rozvidka_hand()
    return {"ok": True, "id": hand_id, "acked": True, "card": card}


def ack_all() -> dict[str, Any]:
    store = _load_store()
    cards = store.get("cards") or {}
    n = 0
    now = _now()
    for cid, card in list(cards.items()):
        if (card.get("status") or "") != "hand":
            continue
        row = dict(card)
        row["status"] = "doing"
        row["col"] = "doing"
        row["open"] = False
        row["manual"] = True
        row["acked_at"] = now
        row["ts"] = now
        cards[cid] = row
        n += 1
    store["cards"] = cards
    _save_store(store)
    _clear_rozvidka_hand()
    return {"ok": True, "acked": n}


def _clear_rozvidka_hand() -> None:
    path = ROOT / "data" / "rozvidka" / "state.json"
    if not path.exists():
        return
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
        if st.get("raised_hand"):
            st["raised_hand"] = None
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
    except Exception:
        pass


def _tail_board(n: int = 160) -> list[dict[str, Any]]:
    if not BOARD_FILE.exists():
        return []
    lines = BOARD_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: list[dict[str, Any]] = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _read_json(path: Any) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _job(
    owner: str,
    ref: str,
    title: str,
    *,
    status: str,
    detail: str = "",
    kind: str = "робота",
    level: str = "",
) -> dict[str, Any]:
    return _upsert(
        owner,
        title,
        kind=kind,
        detail=detail,
        level=level,
        ref=ref,
        status=status,
        system=True,
    )


def sync_reality() -> dict[str, Any]:
    """Upsert cards from live processes, wiki moves, paper ledger."""
    from agents.health import pid_alive, pid_stale, snapshot_module
    from agents.config import PID_FILE

    changed: list[str] = []

    mute = snapshot_module("mute")
    intel = snapshot_module("intel")
    roz = snapshot_module("rozvidka")
    orch_on, _orch_pid = pid_alive(PID_FILE)

    if pid_stale(ROOT / "mute.pid"):
        _job("mute", "job:mute", "збір · процес упав", status="hand", detail="pid файл є, процесу немає", kind="crash", level="ACT")
        changed.append("job:mute")
    elif mute.get("running"):
        _job("mute", "job:mute", "збір · mute в роботі", status="doing", detail="поллер Solana + BNB", kind="робота")
        changed.append("job:mute")
    else:
        _job("mute", "job:mute", "збір · mute стоїть", status="backlog", detail="процес не запущено", kind="робота")
        changed.append("job:mute")

    ist = _read_json(ROOT / "data" / "intel" / "state.json")
    qn = len(ist.get("queue") or [])
    inflight = len(ist.get("in_flight") or [])
    cycle = ist.get("cycle") or 0
    intel_detail = f"цикл {cycle} · черга {qn} · в польоті {inflight}"
    if pid_stale(ROOT / "intel.pid"):
        _job("intel", "job:intel", "звʼязки · intel упав", status="hand", detail=intel_detail, kind="crash", level="ACT")
    elif intel.get("running"):
        _job("intel", "job:intel", "звʼязки · збір адрес", status="doing", detail=intel_detail, kind="collect")
    elif ist.get("collect_interrupted"):
        _job("intel", "job:intel", "звʼязки · збір обірвано", status="hand", detail=intel_detail, kind="collect", level="WATCH")
    elif ist.get("collect_finished_at") and not qn:
        _job("intel", "job:intel", "звʼязки · вікно збору закрито", status="done", detail=intel_detail, kind="collect")
    elif qn:
        _job("intel", "job:intel", "звʼязки · черга адрес", status="backlog", detail=intel_detail, kind="collect")
    else:
        _job("intel", "job:intel", "звʼязки · intel стоїть", status="backlog", detail=intel_detail or "процес не запущено", kind="collect")
    changed.append("job:intel")

    rst = _read_json(ROOT / "data" / "rozvidka" / "state.json")
    turn = rst.get("turn") or 0
    hand_q = (rst.get("raised_hand") or "").strip()
    roz_detail = f"хід {turn}"
    if pid_stale(ROOT / "rozvidka.pid"):
        _job("rozvidka", "job:rozvidka", "патерни · розвідка впала", status="hand", detail=roz_detail, kind="crash", level="ACT")
    elif roz.get("running"):
        _job("rozvidka", "job:rozvidka", "патерни · розвідка в роботі", status="doing", detail=roz_detail, kind="turn")
    else:
        _job("rozvidka", "job:rozvidka", "патерни · розвідка стоїть", status="backlog", detail=roz_detail, kind="turn")
    changed.append("job:rozvidka")
    if hand_q:
        raise_hand("rozvidka", hand_q, kind="рука", detail="state.raised_hand", ref="hand:rozvidka:state")
        changed.append("hand:rozvidka:state")

    if orch_on:
        _job("orch", "job:orch", "диригент веде", status="doing", detail="оркестр запущено", kind="orch")
    else:
        _job("orch", "job:orch", "диригент мовчить", status="backlog", detail="orch не запущено", kind="orch")
    changed.append("job:orch")

    wiki = _read_json(ROOT / "data" / "wiki" / "snapshot.json")
    st = wiki.get("stats") or {}
    if st:
        _job(
            "intel",
            "job:wiki",
            f"вікі · сімʼї {st.get('families')} · ходити {st.get('go')} · подати {st.get('submit')} · рука {st.get('hand')}",
            status="doing" if intel.get("running") else "backlog",
            detail=str(wiki.get("reason") or wiki.get("built_at") or ""),
            kind="wiki",
        )
        changed.append("job:wiki")
    for row in (wiki.get("moves") or [])[:24]:
        mv = row.get("move") or {}
        move_id = str(mv.get("move") or "watch")
        fid = str(row.get("id") or "").strip()
        if not fid:
            continue
        title = f"{mv.get('move_uk') or move_id} · {row.get('short') or fid[:10]} · {(mv.get('where') or {}).get('hint') or ''}"
        if move_id == "hand":
            mstat = "hand"
        elif move_id == "go":
            mstat = "doing"
        else:
            mstat = "backlog"
        _upsert(
            str(row.get("source") or "intel"),
            title.strip(" ·"),
            kind=move_id,
            detail=str(mv.get("why") or "")[:400],
            ref=f"move:{fid}"[:80],
            status=mstat,
            system=True,
        )
        changed.append(f"move:{fid}")

    paper_path = DATA_DIR / "paper.jsonl"
    if paper_path.exists():
        seen: set[str] = set()
        lines = paper_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines[-120:]):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            pref = str(row.get("ref") or row.get("id") or "")
            if not pref or pref in seen:
                continue
            seen.add(pref)
            pst = str(row.get("status") or "paper")
            if pst in {"paper", "pending_real"}:
                kstat = "hand" if pst == "pending_real" else "doing"
            else:
                kstat = "done"
            _upsert(
                "trades",
                f"папір · {row.get('move_uk') or row.get('move') or pst} · {row.get('symbol') or row.get('family_id')}",
                kind="paper" if pst != "real" else "real_mark",
                detail=str(row.get("why") or row.get("note") or "")[:400],
                ref=f"paper:{pref}"[:80],
                status=kstat,
                system=True,
            )
            changed.append(f"paper:{pref}")
            if len(seen) >= 24:
                break

    return {"ok": True, "synced": len(changed), "refs": changed[:40]}


def snapshot() -> dict[str, Any]:
    from agents.health import pid_alive, snapshot_module
    from agents.config import PID_FILE
    from agents.netguard import load_orch_state, recent_reports

    try:
        sync_reality()
    except Exception:
        pass

    store = _load_store()
    cards = list((store.get("cards") or {}).values())
    cards.sort(key=lambda x: x.get("ts") or "", reverse=True)
    cols: dict[str, list[dict[str, Any]]] = {c: [] for c in STATUSES}
    by_owner: dict[str, list[dict[str, Any]]] = {o: [] for o in OWNERS}
    for card in cards:
        st = card.get("status") or "doing"
        if st not in cols:
            st = "doing"
        if len(cols[st]) < (_DONE_KEEP if st == "done" else _PER_COL):
            cols[st].append(card)
        owner = card.get("src") or "orch"
        if owner in by_owner and st != "done" and len(by_owner[owner]) < 24:
            by_owner[owner].append(card)

    hands = cols["hand"]
    players = {}
    for name in ORDER:
        snap = snapshot_module(name)
        last = next((c for c in cards if c.get("src") == name), {}) or {}
        players[name] = {
            **snap,
            "role": OWNER_ROLE[name],
            "last_title": last.get("title"),
            "last_ts": last.get("ts"),
        }
    orch_on, orch_pid = pid_alive(PID_FILE)
    st = load_orch_state()
    last_rep = st.get("last_report") or {}
    last_ev = st.get("last_event") or {}
    conductor = (
        f"диригент {'веде' if orch_on else 'мовчить'}"
        f" · збір {'грає' if players['mute']['running'] else 'тиша'}"
        f" · звʼязки {'грають' if players['intel']['running'] else 'тиша'}"
        f" · голос {'грає' if players['rozvidka']['running'] else 'тиша'}"
        f" · черга {len(cols['backlog'])} · в роботі {len(cols['doing'])}"
    )
    if hands:
        conductor += f" · рук {len(hands)}"
    if last_ev:
        conductor += f" · подія {last_ev.get('src')}:{last_ev.get('kind')}"
    return {
        "ok": True,
        "version": 2,
        "conductor": conductor,
        "orch": {"running": orch_on, "pid": orch_pid},
        "players": players,
        "columns": cols,
        "by_owner": by_owner,
        "open_hands": len(hands),
        "counts": {k: len(v) for k, v in cols.items()},
        "roles": COL_ROLE,
        "owners": OWNER_ROLE,
        "workflow": STATUSES,
        "last_report": last_rep or None,
        "reports": recent_reports(6),
        "ts": _now(),
        "epoch": time.time(),
    }
