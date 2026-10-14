"""Network / process failure tape + backoff. Restart is decided by orch, not by workers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from agents.config import (
    BACKOFF_CAP_SEC,
    BACKOFF_START_SEC,
    DATA_DIR,
    NET_FAILS_BEFORE_RESTART,
    REPORTS_FILE,
    ROOT,
    STATE_FILE,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def classify(exc: BaseException | str, *, hint: str = "") -> str:
    text = f"{hint} {exc}".lower()
    if any(k in text for k in ("ollama", "11434", "inference", "llm")):
        return "net_llm"
    if any(k in text for k in ("telegram", "api.telegram")):
        return "net_tg"
    if any(
        k in text
        for k in (
            "timeout",
            "timed out",
            "connection",
            "urlopen",
            "etherscan",
            "rpc",
            "network",
            "name or service not known",
            "temporarily unavailable",
            "429",
            "502",
            "503",
            "reset by peer",
        )
    ):
        return "net_rpc"
    return "net_rpc" if hint.startswith("net_") else "code"


def load_orch_state() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        return {
            "bus_offset": 0,
            "backoff": {},
            "net_fails": {},
            "last_nudge_ts": 0,
            "last_event": None,
            "last_report": None,
            "ollama": {},
        }
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"bus_offset": 0, "backoff": {}, "net_fails": {}}


def save_orch_state(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    state["heartbeat_at"] = _now()
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(STATE_FILE)


def report(
    module: str,
    kind: str,
    detail: str,
    *,
    extra: dict[str, Any] | None = None,
    raise_hand: bool = True,
) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": _now(),
        "module": module,
        "kind": kind,
        "detail": (detail or "")[:800],
        "extra": extra or {},
    }
    with REPORTS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    st = load_orch_state()
    st["last_report"] = row
    fails = st.setdefault("net_fails", {})
    slot = fails.setdefault(module, {"n": 0, "kind": kind})
    if kind.startswith("net_") or kind.startswith("proc_"):
        if slot.get("kind") == kind:
            slot["n"] = int(slot.get("n") or 0) + 1
        else:
            slot = {"n": 1, "kind": kind}
            fails[module] = slot
        slot["last"] = row["ts"]
    save_orch_state(st)
    if raise_hand:
        _raise_hand(f"{kind} · {module}: {detail[:180]}")
    logger.warning("agents report %s %s %s", module, kind, detail[:200])
    return row


def clear_fails(module: str) -> None:
    st = load_orch_state()
    fails = st.setdefault("net_fails", {})
    if module in fails:
        fails[module] = {"n": 0, "kind": None}
        save_orch_state(st)


def should_restart_for_net(module: str, kind: str) -> bool:
    if kind == "net_tg":
        return False
    if kind == "net_llm":
        return False
    if kind != "net_rpc":
        return kind == "proc_down"
    st = load_orch_state()
    n = int(((st.get("net_fails") or {}).get(module) or {}).get("n") or 0)
    return n >= NET_FAILS_BEFORE_RESTART


def backoff_until(module: str) -> float:
    st = load_orch_state()
    return float(((st.get("backoff") or {}).get(module) or {}).get("until") or 0)


def note_restart(module: str) -> float:
    """Exponential backoff; returns delay applied."""
    import time

    st = load_orch_state()
    backoff = st.setdefault("backoff", {})
    slot = backoff.setdefault(module, {"fails": 0, "until": 0})
    n = int(slot.get("fails") or 0) + 1
    delay = min(BACKOFF_CAP_SEC, BACKOFF_START_SEC * (2 ** max(0, n - 1)))
    slot["fails"] = n
    slot["until"] = time.time() + delay
    slot["last_restart"] = _now()
    save_orch_state(st)
    return delay


def reset_backoff(module: str) -> None:
    st = load_orch_state()
    backoff = st.setdefault("backoff", {})
    if module in backoff:
        backoff[module] = {"fails": 0, "until": 0}
        save_orch_state(st)


def recent_reports(n: int = 12) -> list[dict[str, Any]]:
    if not REPORTS_FILE.exists():
        return []
    lines = REPORTS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: list[dict[str, Any]] = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return list(reversed(rows))


def _raise_hand(msg: str) -> None:
    path = ROOT / "data" / "rozvidka" / "state.json"
    if not path.exists():
        return
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
        st["raised_hand"] = msg[:240]
        st["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        logger.debug("raise_hand skipped", exc_info=True)
