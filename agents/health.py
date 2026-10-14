"""PID / heartbeat for the three worker processes. Crash = pid file exists, process dead."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.config import ROOT, STALE_SEC
from agents.modules import SWARM, Module


def pid_alive(pid_file: Path) -> tuple[bool, int | None]:
    if not pid_file.exists():
        return False, None
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip() or "0")
    except Exception:
        return False, None
    if pid <= 0:
        return False, None
    try:
        os.kill(pid, 0)
        return True, pid
    except OSError:
        return False, pid


def pid_stale(pid_file: Path) -> bool:
    """User-stopped: no pid file. Crash: file left behind, process gone."""
    if not pid_file.exists():
        return False
    alive, _pid = pid_alive(pid_file)
    return not alive


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        t = str(s).replace("Z", "+00:00")
        return datetime.fromisoformat(t)
    except Exception:
        return None


def intel_session_active() -> bool:
    """Restart intel only if a collect window is still open or was interrupted."""
    state_file = ROOT / "data" / "intel" / "state.json"
    if not state_file.exists():
        return False
    try:
        st = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return False
    if st.get("collect_finished_at") and not st.get("collect_interrupted"):
        return False
    if st.get("collect_interrupted"):
        return True
    until = _parse_iso(st.get("collect_until"))
    if until is None:
        return False
    now = datetime.now(timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return now < until


def heartbeat_age_sec(mod: Module) -> float | None:
    path = mod.heartbeat_file
    if path is None or not path.exists():
        # fall back to package state.json
        state_path = ROOT / "data" / mod.name / "state.json"
        if not state_path.exists() and mod.name == "mute":
            return None
        if not state_path.exists():
            return None
        try:
            st = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        ts = st.get("heartbeat_at") or st.get("updated_at")
        dt = _parse_iso(ts)
        if dt is None:
            return None
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        dt = _parse_iso(raw.get("ts"))
        if dt is None:
            return None
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds()
    except Exception:
        return None


def beat(name: str) -> None:
    mod = SWARM.get(name)
    if not mod:
        return
    path = mod.heartbeat_file
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": datetime.now().astimezone().isoformat(), "name": name}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def snapshot_module(name: str) -> dict[str, Any]:
    mod = SWARM[name]
    alive, pid = pid_alive(mod.pid_file)
    stale = pid_stale(mod.pid_file)
    age = heartbeat_age_sec(mod)
    hb_stale = bool(alive and age is not None and age > STALE_SEC)
    return {
        "name": name,
        "role": mod.role,
        "running": alive,
        "pid": pid,
        "pid_file": str(mod.pid_file),
        "crash": stale,
        "heartbeat_age_sec": round(age, 1) if age is not None else None,
        "heartbeat_stale": hb_stale,
    }
