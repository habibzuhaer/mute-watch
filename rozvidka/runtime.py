"""Turn runner: pattern watch → optional DeepSeek narrative → wiki."""

from __future__ import annotations

import json
import logging
import re
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from rozvidka import wiki
from rozvidka.config import (
    ACTIONS_FILE,
    DATA_DIR,
    LANG,
    MAX_CTX_CHARS,
    MODEL,
    STATE_FILE,
    TURN_SLEEP_SEC,
    TURNS_FILE,
)
from rozvidka.ollama_client import OllamaError, chat, ping
from rozvidka.patterns import analyze_turn, is_noise_turn
from rozvidka.relations import load_existing_graph, run_family_pass
from rozvidka.tools import dumps_compact, run_tool
from rozvidka.ui import write_ui

logger = logging.getLogger(__name__)

_STOP = False

SYSTEM_UK = """Ти — Розвідка. Тобі вже дали готові сімʼї адрес і памп-токени з вікі.
Не ходи в мережу. НЕ вигадуй адреси, токени, tx. Пиши лише про те, що є в контексті.
Українською, коротко.

TITLE: <сімʼя або звʼязок>
BODY:
<3–6 речень: хто в сімʼї, патрон якщо є, які памп-токени, що повторюється>
TARGETS:
- адреса_з_контексту | роль | навіщо дивитись
WIKI:
page=memory|clusters|journal ; нотатка або NONE
NOISE: yes|no
HAND: NONE
"""


def _now_local() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def load_state() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    wiki.ensure()
    if not STATE_FILE.exists():
        return {
            "turn": 0,
            "actions": 0,
            "failures": 0,
            "raised_hand": None,
            "last_event": None,
            "model": MODEL,
            "silence_streak": 0,
            "loop_interrupted": False,
            "heartbeat_at": None,
        }
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now().astimezone().isoformat()
    state["heartbeat_at"] = state.get("heartbeat_at") or state["updated_at"]
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def read_jsonl_tail(path: Path, n: int = 40) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
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


def _log_action(kind: str, name: str, detail: str = "", payload: Any = None) -> dict[str, Any]:
    row = {
        "ts": _now_local(),
        "kind": kind,
        "name": name,
        "detail": detail,
        "payload": payload,
    }
    append_jsonl(ACTIONS_FILE, row)
    try:
        from agents.hooks import on_action

        on_action("rozvidka", kind, name, detail=detail)
    except Exception:
        pass
    return row


def _parse_llm(text: str) -> dict[str, Any]:
    title = body = ""
    targets: list[str] = []
    wiki_line = "NONE"
    noise = False
    hand = None

    m = re.search(r"TITLE:\s*(.+)", text, re.I)
    if m:
        title = m.group(1).strip()
    m = re.search(r"BODY:\s*([\s\S]*?)(?=\nTARGETS:|\nWIKI:|\nNOISE:|\nHAND:|$)", text, re.I)
    if m:
        body = m.group(1).strip()
    m = re.search(r"TARGETS:\s*([\s\S]*?)(?=\nWIKI:|\nNOISE:|\nHAND:|$)", text, re.I)
    if m:
        for line in m.group(1).splitlines():
            line = line.strip().lstrip("-•").strip()
            if line and line.upper() != "NONE":
                targets.append(line)
    m = re.search(r"WIKI:\s*(.+)", text, re.I)
    if m:
        wiki_line = m.group(1).strip()
    m = re.search(r"NOISE:\s*(yes|no|так|ні)", text, re.I)
    if m:
        noise = m.group(1).lower() in ("yes", "так")
    m = re.search(r"HAND:\s*(.+)", text, re.I)
    if m:
        h = m.group(1).strip()
        if h.upper() not in {"NONE", "НЕМАЄ", "НЕМА"}:
            hand = h

    if not title:
        title = (text.splitlines()[0] if text else "оберт")[:120]
    if not body:
        body = text[:900]
    return {
        "title": title,
        "body": body,
        "targets": targets,
        "wiki_line": wiki_line,
        "noise": noise,
        "hand": hand,
        "raw": text,
    }


def _apply_wiki(parsed: dict[str, Any], turn: int, analysis: dict[str, Any]) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []

    # Always journal regularities
    regs = analysis.get("regularities") or []
    if regs:
        text = "\n".join(f"- {r.get('text')}" for r in regs[:6])
        try:
            path = wiki.append_page("journal", text, heading=f"оберт {turn} · закономірності")
            applied.append({"page": "journal", "path": path})
            _log_action("wiki", "wiki_append", detail="journal")
        except Exception as exc:
            logger.warning("journal wiki: %s", exc)

    # Clusters page for top findings about families/deployers
    cluster_bits = [
        f.get("title")
        for f in (analysis.get("findings") or [])
        if f.get("type") in {"new_family", "family_grew", "family_stable", "new_deployer", "deployer_grew", "deployer_stable", "wakeup"}
    ][:8]
    if cluster_bits:
        try:
            path = wiki.append_page(
                "clusters",
                "\n".join(f"- {t}" for t in cluster_bits),
                heading=f"оберт {turn}",
            )
            applied.append({"page": "clusters", "path": path})
            _log_action("wiki", "wiki_append", detail="clusters")
        except Exception:
            pass

    # LLM optional note
    line = (parsed.get("wiki_line") or "NONE").strip()
    if line and line.upper() != "NONE":
        page = "memory"
        text = line
        if ";" in line:
            left, right = line.split(";", 1)
            text = right.strip()
            if left.lower().startswith("page="):
                page = left.split("=", 1)[1].strip().lower()
            elif left.strip() in {"clusters", "journal", "memory", "tokens", "history"}:
                page = left.strip()
        if text:
            try:
                path = wiki.append_page(page, text, heading=f"оберт {turn} · LLM")
                applied.append({"page": page, "path": path})
            except Exception:
                pass

    # Address notes from findings + targets
    addrs: list[tuple[str, str]] = []
    for f in (analysis.get("findings") or [])[:12]:
        for a in f.get("addresses") or []:
            if a and str(a).startswith("0x"):
                addrs.append((str(a).lower(), f.get("title") or ""))
    for t in parsed.get("targets") or []:
        m = re.search(r"(0x[a-fA-F0-9]{40})", t)
        if m:
            addrs.append((m.group(1).lower(), t))
    seen: set[str] = set()
    for addr, note in addrs:
        if addr in seen:
            continue
        seen.add(addr)
        try:
            wiki.upsert_address(addr, note=note, tags=["watch", "prep"])
            applied.append({"address": addr})
            _log_action("wiki", "wiki_address_note", detail=addr[:10])
        except Exception:
            pass
    return applied


def _analysis_for_llm(analysis: dict[str, Any]) -> dict[str, Any]:
    rel = analysis.get("relations") or {}
    return {
        "turn": analysis.get("turn"),
        "relation_stats": rel.get("stats"),
        "top_families": rel.get("top_families"),
        "bridges": rel.get("bridges"),
        "shared_pumps": rel.get("shared_pumps"),
        "relation_patterns": (analysis.get("relation_patterns") or [])[:12],
        "regularities": (analysis.get("regularities") or [])[:10],
        "findings": [
            {
                "type": f.get("type"),
                "score": f.get("score"),
                "title": f.get("title"),
                "addresses": f.get("addresses"),
                "source": f.get("source"),
            }
            for f in (analysis.get("findings") or [])[:16]
        ],
    }


def narrate(analysis: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    ctx = _analysis_for_llm(analysis)
    ctx["silence_streak"] = state.get("silence_streak")
    ctx["wiki"] = wiki.snapshot_for_prompt(max_chars=1200)
    user = (
        f"Оберт {analysis.get('turn')}. Ось результат детектора закономірностей.\n"
        f"{dumps_compact(ctx, MAX_CTX_CHARS)}"
    )
    _log_action("дія", "deepseek_chat", detail=MODEL)
    text = chat(
        [
            {"role": "system", "content": SYSTEM_UK if LANG.startswith("uk") else SYSTEM_UK},
            {"role": "user", "content": user},
        ],
        model=MODEL,
    )
    return _parse_llm(text)


def _fallback_narrative(turn: int, analysis: dict[str, Any]) -> dict[str, Any]:
    regs = analysis.get("regularities") or []
    findings = analysis.get("findings") or []
    top = regs[0]["text"] if regs else f"Оберт {turn}"
    body_parts = [r["text"] for r in regs[:4]]
    for f in findings[:4]:
        body_parts.append(f.get("title") or "")
    body = " ".join(p for p in body_parts if p)
    targets = []
    for f in findings[:8]:
        addrs = f.get("addresses") or []
        if addrs:
            targets.append(f"{addrs[0]} | {f.get('type')} | {f.get('title')}")
        elif f.get("short"):
            targets.append(f"{f.get('short')} | {f.get('type')} | {f.get('title')}")
    noise = is_noise_turn(analysis)
    return {
        "title": top[:140],
        "body": body[:1200],
        "targets": targets,
        "wiki_line": "NONE",
        "noise": noise,
        "hand": None,
        "raw": "",
    }


def run_observe_phase(
    state: dict[str, Any],
    turn: int,
    *,
    do_expand: bool = False,
) -> dict[str, Any]:
    """Read existing families (default) or rebuild+expand when explicitly asked."""
    t0 = time.time()
    if do_expand:
        relations = run_family_pass(wiki_sync=True, do_expand=True)
    else:
        relations = load_existing_graph()
    state["actions"] = int(state.get("actions") or 0) + 1
    profit = relations.get("profit") or {}
    expand = relations.get("expand") or {}
    _log_action(
        "дія",
        "family_relations",
        detail=(
            f"{relations.get('elapsed_sec')}s · "
            f"profit={(profit.get('stats') or {}).get('seeds')} · "
            f"expand={expand.get('expanded')} edges+{expand.get('new_edges')} · "
            f"fam={((relations.get('stats') or {}).get('families'))} · "
            f"addr={((relations.get('stats') or {}).get('addresses'))}"
        ),
        payload={
            "stats": relations.get("stats"),
            "profit": profit.get("stats"),
            "expand": {
                "expanded": expand.get("expanded"),
                "new_edges": expand.get("new_edges"),
                "new_neighbors": expand.get("new_neighbors"),
            },
            "top_patterns": [p.get("type") for p in (relations.get("patterns") or [])[:8]],
            "wiki": (relations.get("persisted") or {}).get("wiki_written"),
        },
    )
    for p in (relations.get("patterns") or [])[:12]:
        state["actions"] = int(state.get("actions") or 0) + 1
        _log_action(
            "зв'язок",
            p.get("type") or "pattern",
            detail=p.get("title") or "",
            payload={"score": p.get("score"), "addresses": p.get("addresses") or ([p.get("address")] if p.get("address") else [])},
        )

    analysis = analyze_turn(turn)
    state["actions"] = int(state.get("actions") or 0) + 1
    _log_action(
        "дія",
        "patterns_watch",
        detail=f"{time.time() - t0:.1f}s · findings={len(analysis.get('findings') or [])}",
        payload={
            "stats": analysis.get("snapshot_stats"),
            "regs": [r.get("id") for r in (analysis.get("regularities") or [])],
        },
    )

    # Merge relation patterns into findings/regularities (primary signal)
    rel_findings = []
    for p in relations.get("patterns") or []:
        rel_findings.append(
            {
                "turn": turn,
                "type": p.get("type"),
                "score": p.get("score"),
                "title": p.get("title"),
                "addresses": p.get("addresses") or ([p["address"]] if p.get("address") else []),
                "short": (p.get("addresses") or [p.get("address") or ""])[0][:10] if (p.get("addresses") or p.get("address")) else p.get("type"),
                "detail": p,
                "source": "relations",
            }
        )
    merged_findings = rel_findings + list(analysis.get("findings") or [])
    merged_findings.sort(key=lambda f: -int(f.get("score") or 0))

    rel_regs = [
        {"id": "rel_" + (p.get("type") or "x"), "text": p.get("title"), "weight": p.get("score")}
        for p in (relations.get("patterns") or [])[:8]
    ]
    analysis["findings"] = merged_findings[:28]
    try:
        from alerts.push import push_rozvidka_findings

        push_rozvidka_findings(merged_findings[:6])
    except Exception:
        logger.debug("rozvidka alert push skipped", exc_info=True)
    analysis["regularities"] = rel_regs + list(analysis.get("regularities") or [])
    analysis["relations"] = {
        "stats": relations.get("stats"),
        "top_families": relations.get("top_families"),
        "bridges": relations.get("bridges"),
        "shared_pumps": relations.get("shared_pumps"),
        "profit_top": relations.get("profit_top"),
        "profit": profit,
        "expand": expand,
        "persisted": relations.get("persisted"),
    }
    analysis["relation_patterns"] = relations.get("patterns") or []
    analysis["profit_top"] = relations.get("profit_top") or []

    try:
        stats = run_tool("base_stats")
        state["actions"] = int(state.get("actions") or 0) + 1
        _log_action("дія", "base_stats", detail=str((stats.get("health") or {}).get("cycle_status")))
        analysis["base_stats"] = {
            "health": stats.get("health"),
            "board": stats.get("board"),
            "progress": stats.get("progress"),
        }
    except Exception as exc:
        logger.warning("base_stats: %s", exc)

    return analysis


def run_one_turn(*, use_llm: bool = True, do_expand: bool = False) -> dict[str, Any]:
    state = load_state()
    turn = int(state.get("turn") or 0) + 1
    state["turn"] = turn
    state["model"] = MODEL
    state["last_event"] = _now_local()

    analysis = run_observe_phase(state, turn, do_expand=do_expand)

    ollama_ok = False
    if use_llm:
        try:
            ollama_ok = bool(ping().get("ok"))
        except Exception:
            ollama_ok = False

    if use_llm and ollama_ok:
        try:
            parsed = narrate(analysis, state)
            if is_noise_turn(analysis) and not parsed.get("targets"):
                parsed["noise"] = True
        except OllamaError as exc:
            state["failures"] = int(state.get("failures") or 0) + 1
            parsed = _fallback_narrative(turn, analysis)
            parsed["hand"] = None
            parsed["noise"] = True
            _log_action("збій", "ollama", detail=str(exc))
            logger.warning("ollama error — silent fallback: %s", exc)
    else:
        parsed = _fallback_narrative(turn, analysis)
        parsed["hand"] = None
        if use_llm and not ollama_ok:
            parsed["noise"] = True
            logger.info("skip LLM — ollama offline")

    wiki_applied = _apply_wiki(parsed, turn, analysis)

    if parsed.get("noise"):
        state["silence_streak"] = int(state.get("silence_streak") or 0) + 1
    else:
        state["silence_streak"] = 0

    state["raised_hand"] = parsed.get("hand")
    if parsed.get("hand"):
        try:
            from agents.hooks import on_hand

            on_hand("rozvidka", str(parsed.get("hand")), detail=parsed.get("title") or "")
        except Exception:
            pass
    state["last_title"] = parsed.get("title")
    state["last_findings"] = len(analysis.get("findings") or [])
    state["last_regs"] = [r.get("id") for r in (analysis.get("regularities") or [])[:5]]

    turn_row = {
        "turn": turn,
        "ts": _now_local(),
        "title": parsed.get("title"),
        "body": parsed.get("body"),
        "targets": parsed.get("targets") or [],
        "noise": bool(parsed.get("noise")),
        "hand": parsed.get("hand"),
        "wiki": wiki_applied,
        "model": MODEL if use_llm else "rules",
        "findings": analysis.get("findings") or [],
        "regularities": analysis.get("regularities") or [],
        "stats": analysis.get("snapshot_stats"),
        "watched_n": len(analysis.get("watched") or []),
        "relations": analysis.get("relations") or {},
        "relation_patterns": analysis.get("relation_patterns") or [],
    }
    append_jsonl(TURNS_FILE, turn_row)
    _log_action("wiki", "turn_saved", detail=f"оберт {turn}")
    if not parsed.get("noise"):
        try:
            from agents.hooks import on_signal

            on_signal(
                "rozvidka",
                "turn",
                level="ACT" if (analysis.get("findings") or parsed.get("hand")) else "WATCH",
                score=int((analysis.get("findings") or [{}])[0].get("score") or 0) if analysis.get("findings") else 40,
                ref=(parsed.get("title") or "")[:80],
                extra={"turn": turn, "findings": len(analysis.get("findings") or [])},
            )
        except Exception:
            pass

    state["heartbeat_at"] = datetime.now().astimezone().isoformat()
    state["loop_interrupted"] = False
    try:
        from rozvidka.cycles import append_cycle

        append_cycle(
            {
                "turn": turn,
                "title": turn_row.get("title"),
                "findings": len(turn_row.get("findings") or []),
                "noise": turn_row.get("noise"),
                "model": turn_row.get("model"),
                "hand": turn_row.get("hand"),
            }
        )
    except Exception:
        pass

    save_state(state)
    snapshot = build_snapshot(state, analysis=analysis, last_turn=turn_row)
    snap_path = DATA_DIR / "snapshot.json"
    snap_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_ui(snapshot)
    return turn_row


def build_snapshot(
    state: dict[str, Any] | None = None,
    *,
    analysis: dict[str, Any] | None = None,
    last_turn: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = state or load_state()
    turns = list(reversed(read_jsonl_tail(TURNS_FILE, 30)))
    actions = list(reversed(read_jsonl_tail(ACTIONS_FILE, 50)))
    ollama = ping()
    # Prefer live analysis; else last turn embed
    findings = (analysis or {}).get("findings") or (turns[0].get("findings") if turns else []) or []
    regs = (analysis or {}).get("regularities") or (turns[0].get("regularities") if turns else []) or []
    watched = (analysis or {}).get("watched") or []
    if not watched:
        try:
            from rozvidka.patterns import load_watchbook

            watched = sorted(
                (load_watchbook().get("subjects") or {}).values(),
                key=lambda s: -int(s.get("score") or 0),
            )[:30]
        except Exception:
            watched = []

    relations = (analysis or {}).get("relations") or (turns[0].get("relations") if turns else {}) or {}
    if not relations.get("stats"):
        try:
            from rozvidka.relations import FAMILY_DB, load_json

            fam = load_json(FAMILY_DB, {})
            if fam:
                relations = {
                    "stats": fam.get("stats"),
                    "top_families": [
                        {
                            "id": f.get("id"),
                            "hub": f.get("hub"),
                            "short": f.get("hub_short"),
                            "size": f.get("size"),
                            "pump_n": f.get("pump_n"),
                            "score": f.get("score"),
                            "tokens": (f.get("pump_tokens") or [])[:6],
                        }
                        for f in (fam.get("families") or [])[:12]
                    ],
                    "bridges": fam.get("bridges") or [],
                    "shared_pumps": fam.get("shared_pumps") or [],
                    "profit_top": fam.get("profit_top") or [],
                }
                if not findings:
                    findings = [
                        {
                            "type": p.get("type"),
                            "score": p.get("score"),
                            "title": p.get("title"),
                            "source": "relations",
                        }
                        for p in (fam.get("patterns") or [])[:15]
                    ]
                if not regs:
                    regs = [
                        {"id": "rel_" + (p.get("type") or "x"), "text": p.get("title"), "weight": p.get("score")}
                        for p in (fam.get("patterns") or [])[:8]
                    ]
        except Exception:
            relations = relations or {}

    if not relations.get("profit_top"):
        try:
            from rozvidka.profit import PROFIT_DB
            from rozvidka.relations import FAMILY_DB, load_json

            fam = load_json(FAMILY_DB, {})
            top = fam.get("profit_top") if isinstance(fam, dict) else None
            if not top and PROFIT_DB.exists():
                top = (json.loads(PROFIT_DB.read_text(encoding="utf-8")).get("seeds") or [])[:15]
            if top:
                relations = dict(relations or {})
                relations["profit_top"] = top[:15]
        except Exception:
            pass

    return {
        "ok": True,
        "version": "1.3",
        "name": "Розвідка",
        "subtitle": "сімʼї з інтел · патрон/рамки · локальна модель",
        "state": state,
        "turns": turns,
        "actions": actions,
        "findings": findings[:20],
        "regularities": regs,
        "watched": watched[:20],
        "relations": relations,
        "relation_patterns": (analysis or {}).get("relation_patterns")
        or (turns[0].get("relation_patterns") if turns else [])
        or relations.get("patterns")
        or [],
        "profit_top": relations.get("profit_top") or (analysis or {}).get("profit_top") or [],
        "fresh_signals": (analysis or {}).get("fresh_signals") or (turns[0].get("fresh_signals") if turns else []) or [],
        "stats": (analysis or {}).get("snapshot_stats") or (turns[0].get("stats") if turns else {}) or relations.get("stats") or {},
        "wiki": wiki.list_pages(),
        "ollama": ollama,
        "model": MODEL,
        "goal": "читати готові сімʼї → пояснити звʼязки → вікі (без expand)",
        "ts": _now_local(),
        "last_turn": last_turn,
        "health": __import__("rozvidka.cycles", fromlist=["check_health"]).check_health(state),
        "cycle_history": __import__("rozvidka.cycles", fromlist=["read_cycles"]).read_cycles(20),
    }


def run_forever(
    *,
    sleep_sec: float | None = None,
    use_llm: bool = True,
    do_expand: bool | None = None,
) -> int:
    global _STOP
    from rozvidka.config import EXPAND_DEFAULT

    if do_expand is None:
        do_expand = EXPAND_DEFAULT
    sleep_sec = TURN_SLEEP_SEC if sleep_sec is None else sleep_sec

    def _stop(*_a: Any) -> None:
        global _STOP
        _STOP = True
        logger.info("stop requested")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    wiki.ensure()
    state0 = load_state()
    state0["loop_interrupted"] = False
    state0["loop_started_at"] = datetime.now().astimezone().isoformat()
    state0["heartbeat_at"] = state0["loop_started_at"]
    save_state(state0)
    write_ui(build_snapshot())
    logger.info("Розвідка loop model=%s sleep=%ss expand=%s (resume turns from %s)", MODEL, sleep_sec, do_expand, state0.get("turn"))
    last_nudge = 0.0

    while not _STOP:
        ollama_ok = True
        if use_llm:
            try:
                ollama_ok = bool(ping().get("ok"))
            except Exception:
                ollama_ok = False
        if use_llm and not ollama_ok:
            logger.info("idle — ollama offline")
            st = load_state()
            st["heartbeat_at"] = datetime.now().astimezone().isoformat()
            save_state(st)
        else:
            try:
                row = run_one_turn(use_llm=use_llm, do_expand=do_expand)
                logger.info(
                    "turn %s — %s · findings=%s",
                    row.get("turn"),
                    row.get("title"),
                    len(row.get("findings") or []),
                )
            except Exception:
                logger.exception("turn failed")
                state = load_state()
                state["failures"] = int(state.get("failures") or 0) + 1
                state["heartbeat_at"] = datetime.now().astimezone().isoformat()
                save_state(state)
                _log_action("збій", "turn", detail="exception")
                try:
                    from agents.hooks import on_net_fail

                    on_net_fail("rozvidka", "turn exception", hint="code")
                except Exception:
                    pass
        for _ in range(int(max(1, sleep_sec))):
            if _STOP:
                break
            try:
                from agents.bus import consume_nudge

                nudged = consume_nudge(after_epoch=last_nudge)
                if nudged:
                    last_nudge = float(nudged.get("epoch") or time.time())
                    if use_llm and not ollama_ok:
                        logger.info("nudge ignored — ollama offline (%s)", nudged.get("reason"))
                    else:
                        logger.info("nudge speak %s", nudged.get("reason"))
                        break
            except Exception:
                logger.debug("nudge check skipped", exc_info=True)
            time.sleep(1)
            if _ % 20 == 0:
                st = load_state()
                st["heartbeat_at"] = datetime.now().astimezone().isoformat()
                save_state(st)

    st = load_state()
    st["loop_interrupted"] = True
    st["loop_stopped_at"] = datetime.now().astimezone().isoformat()
    st["heartbeat_at"] = st["loop_stopped_at"]
    save_state(st)
    write_ui(build_snapshot(st))
    logger.info("Розвідка stopped — turn=%s saved for resume", st.get("turn"))
    return 0
