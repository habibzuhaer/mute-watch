"""Durable cycle journal + resume after crash / reconnect."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from intel.config import DATA_DIR, CYCLE_SLEEP_SEC
from intel.store import load_json, load_state, save_json, save_state

CYCLES_FILE = DATA_DIR / "cycles.jsonl"
HEALTH_FILE = DATA_DIR / "cycles_health.json"
STALE_SEC = float(os.getenv("INTEL_STALE_SEC", "600"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        t = str(s).replace("Z", "+00:00")
        return datetime.fromisoformat(t)
    except Exception:
        return None


def append_cycle(row: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CYCLES_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _now().isoformat(), **row}, ensure_ascii=False, default=str) + "\n")


def read_cycles(limit: int = 40) -> list[dict[str, Any]]:
    if not CYCLES_FILE.exists():
        return []
    lines = CYCLES_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return list(reversed(out))


def recover_in_flight(state: dict[str, Any]) -> int:
    """Re-queue addresses that were claimed but not acked (crash mid-cycle)."""
    inflight = list(state.get("in_flight") or [])
    if not inflight:
        return 0
    q = list(state.get("queue") or [])
    keys = {f"{x.get('chain')}:{x.get('address')}" for x in q}
    n = 0
    for item in inflight:
        key = f"{item.get('chain')}:{item.get('address')}"
        if key in keys:
            continue
        item = dict(item)
        item["reason"] = f"resume:{item.get('reason') or ''}"
        item["priority"] = max(int(item.get("priority") or 0), 20)
        q.insert(0, item)
        n += 1
    state["queue"] = q
    state["in_flight"] = []
    state["last_recover_at"] = _now().isoformat()
    state["last_recover_n"] = n
    return n


def begin_session(
    state: dict[str, Any],
    *,
    hours: float,
    resume: bool = True,
) -> dict[str, Any]:
    """Start or resume a collect window. Preserves queue/done/cycle counter."""
    recovered = recover_in_flight(state)
    now = _now()
    sessions = list(state.get("sessions") or [])
    until = _parse_iso(state.get("collect_until"))
    status = "new"

    if resume and until and until > now and not state.get("collect_finished_at"):
        # continue existing window
        status = "resumed"
        if not state.get("collect_started_at"):
            state["collect_started_at"] = now.isoformat()
    elif resume and state.get("collect_interrupted"):
        # interrupted before — open fresh window but keep counters/queue
        from datetime import timedelta

        state["collect_started_at"] = now.isoformat()
        state["collect_until"] = (now + timedelta(hours=hours)).isoformat()
        state["collect_finished_at"] = None
        state["collect_interrupted"] = False
        status = "resume_new_window"
    else:
        from datetime import timedelta

        state["collect_started_at"] = now.isoformat()
        state["collect_until"] = (now + timedelta(hours=hours)).isoformat()
        state["collect_finished_at"] = None
        state["collect_interrupted"] = False
        status = "new"

    sessions.append(
        {
            "started_at": state.get("collect_started_at"),
            "until": state.get("collect_until"),
            "status": status,
            "recovered_in_flight": recovered,
            "cycle_at_start": state.get("cycle") or 0,
            "at": now.isoformat(),
        }
    )
    state["sessions"] = sessions[-50:]
    state["running"] = True
    state["heartbeat_at"] = now.isoformat()
    save_state(state)
    return {
        "status": status,
        "until": state.get("collect_until"),
        "recovered": recovered,
        "cycle": state.get("cycle"),
        "queue": len(state.get("queue") or []),
    }


def mark_interrupted(state: dict[str, Any] | None = None) -> None:
    state = state or load_state()
    state["running"] = False
    state["collect_interrupted"] = True
    state["interrupted_at"] = _now().isoformat()
    state["heartbeat_at"] = _now().isoformat()
    # keep collect_until so resume can continue if still in window
    if state.get("in_flight"):
        recover_in_flight(state)
    save_state(state)


def mark_finished(state: dict[str, Any] | None = None) -> None:
    state = state or load_state()
    state["running"] = False
    state["collect_finished_at"] = _now().isoformat()
    state["collect_interrupted"] = False
    state["heartbeat_at"] = _now().isoformat()
    if state.get("in_flight"):
        recover_in_flight(state)
    save_state(state)


def heartbeat(state: dict[str, Any]) -> None:
    state["heartbeat_at"] = _now().isoformat()
    state["running"] = True
    save_state(state)


def check_health(*, pid_running: bool | None = None) -> dict[str, Any]:
    """Health for HTML / dashboard."""
    from pathlib import Path

    state = load_state()
    root = Path(__file__).resolve().parents[1]  # .../MUTE (package lives in MUTE/intel/)
    pid_file = root / "intel.pid"
    alive = False
    pid = None
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            alive = True
        except Exception:
            alive = False
    if pid_running is not None:
        alive = pid_running

    hb = _parse_iso(state.get("heartbeat_at") or state.get("updated_at"))
    age = ( _now() - hb ).total_seconds() if hb else None
    until = _parse_iso(state.get("collect_until"))
    remaining = (until - _now()).total_seconds() if until else None

    if alive and age is not None and age <= STALE_SEC:
        status = "ok"
    elif alive and age is not None and age > STALE_SEC:
        status = "stale"
    elif state.get("collect_interrupted"):
        status = "interrupted"
    elif state.get("collect_finished_at") and not alive:
        status = "finished"
    else:
        status = "stopped"

    issues = []
    if not alive:
        issues.append("intel process not running")
    if status == "stale":
        issues.append(f"heartbeat age {int(age or 0)}s > {int(STALE_SEC)}s")
    if state.get("collect_interrupted"):
        issues.append("last session interrupted — restart to resume")
    if state.get("in_flight"):
        issues.append(f"in_flight={len(state['in_flight'])} (will requeue on start)")
    err = list(state.get("errors") or [])[-3:]
    for e in err:
        issues.append(f"err: {e}")

    last = state.get("last_cycle") or {}
    out = {
        "ok": status == "ok",
        "cycle_status": status,
        "pid": pid,
        "running": alive,
        "cycle": state.get("cycle") or 0,
        "queue": len(state.get("queue") or []),
        "done": len(state.get("done") or []),
        "in_flight": len(state.get("in_flight") or []),
        "heartbeat_age_sec": round(age, 1) if age is not None else None,
        "stale_after_sec": STALE_SEC,
        "collect_until": state.get("collect_until"),
        "collect_started_at": state.get("collect_started_at"),
        "remaining_sec": round(remaining, 0) if remaining is not None else None,
        "interrupted": bool(state.get("collect_interrupted")),
        "last_cycle": {
            "cycle": last.get("cycle"),
            "elapsed": last.get("elapsed"),
            "edges": (last.get("stats") or {}).get("edges"),
            "addresses": (last.get("stats") or {}).get("addresses"),
            "detect": last.get("detect"),
            "errors": last.get("errors") or [],
        },
        "sessions_n": len(state.get("sessions") or []),
        "last_session": (state.get("sessions") or [None])[-1],
        "issues": issues,
        "sleep_sec": CYCLE_SLEEP_SEC,
        "ts": _now().isoformat(),
    }
    save_json(HEALTH_FILE, out)
    # also mirror for dashboard
    try:
        dash = root / "out" / "intel_cycles_health.json"
        dash.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return out
