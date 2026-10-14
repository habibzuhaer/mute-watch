"""Thin entry points for mute / intel / rozvidka — never raise into the worker loop."""

from __future__ import annotations

import logging
import time
from typing import Any

from agents.config import VOICE_MIN_SCORE

logger = logging.getLogger(__name__)

_SRC = {
    "live_prep": "mute",
    "dwf": "mute",
    "intel": "intel",
    "rozvidka": "rozvidka",
    "graph": "intel",
    "system": "orch",
}

_sig_seen: dict[str, float] = {}
_net_seen: dict[str, float] = {}
_SIG_TTL = 90.0
_NET_TTL = {
    "net_tg": 60.0,
    "net_llm": 60.0,
    "net_rpc": 15.0,
    "code": 30.0,
}


def swarm_src(activity_or_name: str) -> str:
    raw = (activity_or_name or "").strip().lower()
    return _SRC.get(raw, raw if raw in {"mute", "intel", "rozvidka", "orch", "trades"} else "mute")


def _prune(store: dict[str, float], now: float, ttl: float) -> None:
    dead = [k for k, ts in store.items() if now - ts > ttl * 4]
    for k in dead:
        store.pop(k, None)


def on_signal(
    src: str,
    kind: str,
    *,
    level: str = "INFO",
    score: int = 0,
    ref: str = "",
    extra: dict[str, Any] | None = None,
) -> bool:
    """Return True if the row was written to the bus (not dropped as dup/low)."""
    try:
        level_u = (level or "INFO").upper()
        sc = int(score or 0)
        if level_u not in {"ACT", "CRITICAL", "WATCH"} and sc < VOICE_MIN_SCORE:
            return False
        key = f"{swarm_src(src)}|{kind}|{(ref or '').lower()}"
        now = time.monotonic()
        _prune(_sig_seen, now, _SIG_TTL)
        if now - _sig_seen.get(key, 0) < _SIG_TTL:
            return False
        _sig_seen[key] = now
        from agents.bus import emit

        emit(swarm_src(src), kind, level=level_u, score=sc, ref=ref, extra=extra)
        on_action(swarm_src(src), kind, ref or kind, detail=level_u, level=level_u, ref=ref)
        return True
    except Exception:
        logger.debug("agents bus emit skipped", exc_info=True)
        return False


def on_activity(activity: dict[str, Any], level: str, *, reason: str = "") -> bool:
    src = swarm_src(str(activity.get("source") or "mute"))
    kind = str(activity.get("activity_type") or activity.get("type") or "signal")
    ref = str(
        activity.get("symbol")
        or activity.get("address")
        or activity.get("match_entity")
        or activity.get("tx_hash")
        or ""
    )[:80]
    return on_signal(
        src,
        kind,
        level=level,
        score=int(activity.get("score") or 0),
        ref=ref,
        extra={"reason": reason, "chain": activity.get("chain"), "tier": activity.get("tier")},
    )


def on_net_fail(module: str, exc: BaseException | str, *, hint: str = "") -> None:
    try:
        from agents.netguard import classify, report

        kind = hint if str(hint).startswith("net_") or hint == "code" else classify(exc, hint=hint)
        key = f"{swarm_src(module)}|{kind}"
        now = time.monotonic()
        ttl = _NET_TTL.get(kind, 20.0)
        _prune(_net_seen, now, ttl)
        if now - _net_seen.get(key, 0) < ttl:
            return
        _net_seen[key] = now
        report(swarm_src(module), kind, str(exc), extra={"hint": hint})
        on_hand(swarm_src(module), f"{kind}: {exc}", kind=kind, detail=hint)
    except Exception:
        logger.debug("agents net report skipped", exc_info=True)


_act_seen: dict[str, float] = {}
_ACT_TTL = 12.0


def on_action(
    src: str,
    kind: str,
    title: str,
    *,
    detail: str = "",
    level: str = "",
    ref: str = "",
) -> None:
    try:
        now = time.monotonic()
        key = f"{swarm_src(src)}|{kind}|{(title or '')[:60]}"
        _prune(_act_seen, now, _ACT_TTL)
        if now - _act_seen.get(key, 0) < _ACT_TTL:
            return
        _act_seen[key] = now
        from agents.board import post

        post(swarm_src(src), title, kind=kind, detail=detail, level=level, ref=ref)
    except Exception:
        logger.debug("agents board action skipped", exc_info=True)


def on_hand(src: str, question: str, *, kind: str = "рука", detail: str = "") -> None:
    try:
        q = (question or "").strip()
        if not q or q.upper() in {"NONE", "НЕМАЄ", "НЕМА"}:
            return
        from agents.board import raise_hand

        raise_hand(swarm_src(src), q, kind=kind, detail=detail)
    except Exception:
        logger.debug("agents hand skipped", exc_info=True)


def beat(name: str) -> None:
    try:
        from agents.health import beat as _beat

        _beat(swarm_src(name))
    except Exception:
        logger.debug("agents heartbeat skipped", exc_info=True)
