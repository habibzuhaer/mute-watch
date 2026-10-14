"""Rozvidka durable turn journal + loop health / resume."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rozvidka.config import DATA_DIR, ROOT, TURN_SLEEP_SEC

CYCLES_FILE = DATA_DIR / "cycles.jsonl"
HEALTH_FILE = DATA_DIR / "cycles_health.json"
STALE_SEC = float(os.getenv("ROZVIDKA_STALE_SEC", "900"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def append_cycle(row: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CYCLES_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _now().isoformat(), **row}, ensure_ascii=False, default=str) + "\n")


def read_cycles(limit: int = 30) -> list[dict[str, Any]]:
    if not CYCLES_FILE.exists():
        return []
    lines = CYCLES_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return list(reversed(out))


def check_health(state: dict[str, Any] | None = None) -> dict[str, Any]:
    from rozvidka.runtime import load_state

    state = state or load_state()
    pid_file = ROOT / "rozvidka.pid"
    alive = False
    pid = None
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            alive = True
        except Exception:
            alive = False

    hb_s = state.get("heartbeat_at") or state.get("updated_at") or state.get("last_event")
    age = None
    if hb_s:
        try:
            hb = datetime.fromisoformat(str(hb_s).replace("Z", "+00:00"))
            if hb.tzinfo is None:
                hb = hb.replace(tzinfo=timezone.utc)
            age = (_now() - hb.astimezone(timezone.utc)).total_seconds()
        except Exception:
            age = None

    if alive and age is not None and age <= STALE_SEC:
        status = "ok"
    elif alive and age is not None and age > STALE_SEC:
        status = "stale"
    elif state.get("loop_interrupted"):
        status = "interrupted"
    else:
        status = "stopped"

    issues = []
    if not alive:
        issues.append("rozvidka process not running")
    if status == "stale":
        issues.append(f"heartbeat age {int(age or 0)}s")
    if state.get("raised_hand"):
        issues.append(f"hand: {state.get('raised_hand')}")
    if state.get("loop_interrupted"):
        issues.append("loop interrupted — restart resumes turn counter")

    out = {
        "ok": status == "ok",
        "cycle_status": status,
        "pid": pid,
        "running": alive,
        "turn": state.get("turn") or 0,
        "failures": state.get("failures") or 0,
        "silence_streak": state.get("silence_streak") or 0,
        "model": state.get("model"),
        "heartbeat_age_sec": round(age, 1) if age is not None else None,
        "stale_after_sec": STALE_SEC,
        "raised_hand": state.get("raised_hand"),
        "last_title": state.get("last_title"),
        "last_findings": state.get("last_findings"),
        "interrupted": bool(state.get("loop_interrupted")),
        "issues": issues,
        "sleep_sec": TURN_SLEEP_SEC,
        "ts": _now().isoformat(),
    }
    HEALTH_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        (ROOT / "out" / "rozvidka_cycles_health.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
    return out
