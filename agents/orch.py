"""Sleeping supervisor: crash restart, bus → nudge speak, network reports."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from datetime import datetime
from typing import Any

from agents.bus import append_voice, should_wake_speak, tail, write_nudge
from agents.config import NUDGE_COOLDOWN_SEC, PID_FILE, POLL_SEC, ROOT
from agents.health import pid_alive, snapshot_module
from agents.inference import load_tokens, ping
from agents.modules import ORDER, SWARM
from agents.netguard import (
    backoff_until,
    clear_fails,
    load_orch_state,
    note_restart,
    recent_reports,
    report,
    reset_backoff,
    save_orch_state,
    should_restart_for_net,
)

logger = logging.getLogger(__name__)

_STOP = False


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _start_module(name: str, *, reason: str = "wanted") -> dict[str, Any]:
    mod = SWARM[name]
    delay = backoff_until(name)
    if delay > time.time():
        wait = delay - time.time()
        logger.info("backoff %s %.0fs left", name, wait)
        return {"ok": False, "reason": "backoff", "wait": wait}
    applied = note_restart(name)
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    logger.info("restart %s via %s (%s, backoff %.0fs)", name, mod.start_script.name, reason, applied)
    r = subprocess.run(
        ["bash", str(mod.start_script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    out = ((r.stdout or "") + (r.stderr or ""))[-500:]
    ok = r.returncode == 0
    report(
        name,
        "proc_restart",
        f"rc={r.returncode} delay={applied:.0f}s {out[:200]}",
        extra={"ok": ok},
        raise_hand=not ok,
    )
    clear_fails(name)
    try:
        from agents.hooks import on_action

        on_action("orch", "підняв", f"{name} · {reason}", detail=out[:120], ref=name)
    except Exception:
        pass
    return {"ok": ok, "out": out, "delay": applied}


def _ensure(name: str, *, reason: str = "wanted") -> dict[str, Any]:
    """Keep a swarm worker up while orch is alive. Missing pid = start, not 'user off'."""
    alive, _ = pid_alive(SWARM[name].pid_file)
    if alive:
        reset_backoff(name)
        return {"ok": True, "already": True}
    logger.info("ensure %s (%s)", name, reason)
    return _start_module(name, reason=reason)


def _maybe_restart_net(name: str, kind: str) -> None:
    if not should_restart_for_net(name, kind):
        return
    report(name, "proc_restart", f"net {kind} threshold")
    _ensure(name, reason=f"net:{kind}")
    clear_fails(name)


def nudge_speak(event: dict[str, Any]) -> dict[str, Any]:
    st = load_orch_state()
    last = float(st.get("last_nudge_ts") or 0)
    now = time.time()
    if now - last < NUDGE_COOLDOWN_SEC:
        return {"ok": True, "skipped": "cooldown"}
    write_nudge(f"{event.get('src')}:{event.get('kind')}", event)
    st["last_nudge_ts"] = now
    st["last_event"] = event
    save_orch_state(st)
    append_voice(
        event.get("src") or "bus",
        f"{event.get('level') or ''} {event.get('kind')} {event.get('ref') or ''}".strip(),
        event=event,
    )
    src = event.get("src") or ""
    if src in {"mute", "intel"}:
        _ensure("intel", reason="bus")
    started = _ensure("rozvidka", reason="bus-speak")
    return {**started, "nudge": True, "started": not started.get("already")}


def tick() -> dict[str, Any]:
    """One orch pass: keep trio up, bus → nudge speak, ollama ping."""
    st = load_orch_state()
    for name in ORDER:
        _ensure(name, reason="wanted")

    fails = dict(load_orch_state().get("net_fails") or {})
    for name, slot in fails.items():
        kind = slot.get("kind") or ""
        if kind == "net_rpc":
            _maybe_restart_net(name, kind)

    events, new_off = tail(int(st.get("bus_offset") or 0))
    st = load_orch_state()
    st["bus_offset"] = new_off
    nudged = []
    for ev in events:
        if should_wake_speak(ev):
            nudged.append(nudge_speak(ev))
    last_ping = float((st.get("ollama") or {}).get("ping_at") or 0)
    ollama = st.get("ollama") or {}
    if time.time() - last_ping >= 15:
        ollama = ping()
        prev_ok = (st.get("ollama") or {}).get("ok")
        if prev_ok and not ollama.get("ok"):
            report("orch", "net_llm", ollama.get("error") or "ollama down")
        elif (not prev_ok) and ollama.get("ok") and st.get("ollama"):
            report("orch", "net_llm_ok", "ollama back", raise_hand=False)
        st["ollama"] = {
            "ok": ollama.get("ok"),
            "error": ollama.get("error"),
            "ts": _now(),
            "ping_at": time.time(),
        }
    save_orch_state(st)
    return {"events": len(events), "nudged": len(nudged), "ollama": (st.get("ollama") or {}).get("ok")}


def build_snapshot() -> dict[str, Any]:
    st = load_orch_state()
    workers = {name: snapshot_module(name) for name in ORDER}
    orch_alive, orch_pid = pid_alive(PID_FILE)
    last = st.get("last_report") or {}
    last_ev = st.get("last_event") or {}
    line = (
        f"орк {'ON' if orch_alive else 'off'}"
        f" · mute {'ON' if workers['mute']['running'] else 'off'}"
        f" · intel {'ON' if workers['intel']['running'] else 'off'}"
        f" · roz {'ON' if workers['rozvidka']['running'] else 'off'}"
    )
    if last:
        line += f" · звіт {last.get('kind')} {last.get('module')}"
    if last_ev:
        line += f" · подія {last_ev.get('src')}:{last_ev.get('kind')}"
    return {
        "ok": True,
        "line": line,
        "running": orch_alive,
        "pid": orch_pid,
        "workers": workers,
        "ollama": st.get("ollama") or {},
        "last_event": last_ev or None,
        "last_report": last or None,
        "reports": recent_reports(8),
        "tokens": load_tokens(),
        "heartbeat_at": st.get("heartbeat_at"),
        "ts": _now(),
    }


def run_forever() -> int:
    global _STOP

    def _stop(*_a: Any) -> None:
        global _STOP
        _STOP = True
        logger.info("orch stop requested")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    logger.info("orch up pid=%s poll=%.1fs", os.getpid(), POLL_SEC)
    report("orch", "proc_up", f"pid={os.getpid()}", raise_hand=False)
    for name in ORDER:
        reset_backoff(name)
    try:
        while not _STOP:
            try:
                tick()
            except Exception:
                logger.exception("orch tick failed")
                report("orch", "code", "tick exception")
            for _ in range(int(max(1, POLL_SEC))):
                if _STOP:
                    break
                time.sleep(1)
    finally:
        st = load_orch_state()
        st["stopped_at"] = _now()
        save_orch_state(st)
        try:
            if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
                PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        logger.info("orch stopped")
    return 0
