"""Event bus — jsonl tape. Workers emit; orch tails and nudges speak."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.config import BUS_FILE, DATA_DIR, NUDGE_FILE, VOICE_MIN_SCORE, VOICES_FILE


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def emit(
    src: str,
    kind: str,
    *,
    level: str = "INFO",
    score: int = 0,
    ref: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure()
    row = {
        "ts": _now(),
        "src": src,
        "kind": kind,
        "level": level,
        "score": int(score or 0),
        "ref": ref or "",
        "extra": extra or {},
    }
    with BUS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return row


def should_wake_speak(row: dict[str, Any]) -> bool:
    """Mute/intel facts wake rozvidka. Rozvidka's own turns do not loop."""
    if (row.get("src") or "") == "rozvidka":
        return False
    kind = row.get("kind") or ""
    if kind.startswith("net_") or kind.startswith("proc_"):
        return False
    level = (row.get("level") or "").upper()
    if level in {"ACT", "CRITICAL"}:
        return True
    if level == "WATCH":
        return True
    return int(row.get("score") or 0) >= VOICE_MIN_SCORE


def tail(offset: int = 0, path: Any = None) -> tuple[list[dict[str, Any]], int]:
    """Read new jsonl rows from byte offset. Returns (rows, new_offset)."""
    path = path or BUS_FILE
    if not path.exists():
        return [], 0
    size = path.stat().st_size
    if offset > size:
        offset = 0
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        fh.seek(offset)
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        new_off = fh.tell()
    return rows, new_off


def write_nudge(reason: str, event: dict[str, Any] | None = None) -> None:
    ensure()
    payload = {"ts": _now(), "reason": reason, "event": event or {}, "epoch": time.time()}
    tmp = NUDGE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(NUDGE_FILE)


def peek_nudge() -> dict[str, Any] | None:
    if not NUDGE_FILE.exists():
        return None
    try:
        return json.loads(NUDGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def consume_nudge(*, after_epoch: float = 0.0) -> dict[str, Any] | None:
    """If a nudge is newer than after_epoch, consume it (unlink) and return payload."""
    row = peek_nudge()
    if not row:
        return None
    epoch = float(row.get("epoch") or 0)
    if epoch <= after_epoch:
        return None
    try:
        NUDGE_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return row


def append_voice(src: str, text: str, *, event: dict[str, Any] | None = None) -> None:
    ensure()
    row = {"ts": _now(), "src": src, "text": (text or "")[:800], "event": event or {}}
    with VOICES_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def atomic_write(path, data: dict[str, Any]) -> None:
    ensure()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
        Path(tmp).replace(path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
