"""Paper trades first. Real is refused unless TRADES_ALLOW_REAL=1 — and still no order routing."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from typing import Any

from agents.config import DATA_DIR, ROOT

PAPER_FILE = DATA_DIR / "paper.jsonl"
ALLOW_REAL = os.getenv("TRADES_ALLOW_REAL", "0").strip() in {"1", "true", "yes"}


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read() -> list[dict[str, Any]]:
    if not PAPER_FILE.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in PAPER_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _append(row: dict[str, Any]) -> dict[str, Any]:
    _ensure()
    with PAPER_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _ref_key(family_id: str, symbol: str) -> str:
    return f"{(family_id or '').strip()}|{(symbol or '').strip().upper()}"


def open_paper(
    *,
    family_id: str = "",
    symbol: str = "",
    move: dict[str, Any] | None = None,
    patron: dict[str, Any] | None = None,
    frames: dict[str, Any] | None = None,
    note: str = "",
    source: str = "wiki",
) -> dict[str, Any]:
    mv = move or {}
    where = mv.get("where") or {}
    key = _ref_key(family_id, symbol)
    for old in reversed(_read()[-80:]):
        if old.get("ref") == key and old.get("status") in {"paper", "pending_real"}:
            return old
    row = {
        "id": uuid.uuid4().hex[:12],
        "ts": _now(),
        "status": "paper",
        "ref": key,
        "family_id": family_id,
        "symbol": symbol,
        "move": mv.get("move") or "submit",
        "move_uk": mv.get("move_uk") or "",
        "where": where,
        "why": mv.get("why") or note,
        "patron": (patron or {}).get("short") or (patron or {}).get("address") or "",
        "frames": (frames or {}).get("status") or "",
        "source": source,
        "real": False,
    }
    _append(row)
    try:
        from agents.board import post

        post(
            "trades",
            f"папір · {mv.get('move_uk') or row['move']} · {symbol or family_id}",
            kind="paper",
            detail=(row.get("why") or "")[:200],
            ref=key[:80],
            col="trades",
        )
    except Exception:
        pass
    return row


def promote_real(paper_id: str) -> dict[str, Any]:
    """Mark a paper row as real only if explicitly allowed. Never sends an order."""
    rows = _read()
    found = next((r for r in rows if r.get("id") == paper_id), None)
    if not found:
        return {"ok": False, "error": "not found"}
    if not ALLOW_REAL:
        try:
            from agents.board import raise_hand

            raise_hand(
                "trades",
                f"реал вимкнено · {found.get('symbol') or found.get('family_id')}",
                detail="TRADES_ALLOW_REAL=0 — спочатку папір. Ордерів немає.",
            )
        except Exception:
            pass
        return {
            "ok": False,
            "error": "real disabled",
            "hint": "TRADES_ALLOW_REAL=0 — paper only",
            "paper": found,
        }
    found = dict(found)
    found["status"] = "real"
    found["real"] = True
    found["real_at"] = _now()
    found["note"] = "marked real locally — no venue order was sent"
    _append(found)
    try:
        from agents.board import post

        post(
            "trades",
            f"реал-мітка · {found.get('symbol')}",
            kind="real_mark",
            detail="без ордера на біржу",
            ref=found.get("ref") or "",
            col="trades",
        )
    except Exception:
        pass
    return {"ok": True, "trade": found}


def sync_goes(families: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fam in families:
        mv = fam.get("move") or {}
        if mv.get("move") != "go":
            continue
        toks = fam.get("tokens") or fam.get("pump_tokens") or []
        symbol = str((toks[0] if toks else "") or fam.get("id") or "")[:24]
        out.append(
            open_paper(
                family_id=str(fam.get("id") or ""),
                symbol=symbol,
                move=mv,
                patron=fam.get("patron") or {},
                frames=fam.get("frames") or {},
                source="wiki-go",
            )
        )
        if len(out) >= limit:
            break
    return out


def snapshot(limit: int = 40) -> dict[str, Any]:
    rows = list(reversed(_read()[-limit:]))
    n_paper = sum(1 for r in rows if r.get("status") == "paper")
    n_real = sum(1 for r in rows if r.get("status") == "real")
    return {
        "ok": True,
        "allow_real": ALLOW_REAL,
        "paper_n": n_paper,
        "real_n": n_real,
        "recent": rows,
        "root": str(ROOT),
        "file": str(PAPER_FILE),
        "ts": time.time(),
    }
