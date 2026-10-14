"""Burst of small prep transfers → score boost without lowering global money floor.

Single weak events stay below MONEY_MIN_SCORE.
≥N events on the same wallet (optionally same token) within a window
get a boost so the *cluster* can reach ACT / ДІЯ.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from mute.amount_filter import parse_amount_human

ROOT = Path(__file__).resolve().parent.parent
STORE_PATH = Path(os.getenv("ALERTS_BURST_FILE", str(ROOT / "data" / "alerts" / "burst.json")))

WINDOW_SEC = int(os.getenv("ALERTS_BURST_WINDOW_SEC", str(60 * 60)))
MIN_COUNT = int(os.getenv("ALERTS_BURST_MIN_COUNT", "3"))
SCORE_BOOST = int(os.getenv("ALERTS_BURST_SCORE_BOOST", "18"))
# Treat as "small" when human amount known and below this (non-stable tokens often unknown → count-only)
SMALL_AMT = float(os.getenv("ALERTS_BURST_SMALL_AMT", "500"))


def _load() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return {"buckets": {}}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"buckets": {}}


def _save(data: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STORE_PATH)


def _bucket_key(event: dict[str, Any]) -> str:
    addr = (event.get("address") or "").lower()
    sym = (event.get("symbol") or "?").upper()
    prep = event.get("prep_type") or "prep"
    return f"{addr}|{sym}|{prep}"


def _is_small(event: dict[str, Any]) -> bool:
    """Prefer amount when known; otherwise count every prep touch as potentially small."""
    amt = parse_amount_human(event)
    if amt is None:
        return True
    return amt + 1e-9 < SMALL_AMT


def record_and_boost(event: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """Record event into burst window; if cluster, bump score/reasons in-place."""
    now = now if now is not None else time.time()
    if not _is_small(event):
        return event

    key = _bucket_key(event)
    if not (event.get("address") and event.get("symbol")):
        return event

    data = _load()
    buckets: dict[str, list] = data.setdefault("buckets", {})
    row = {
        "ts": float(event.get("timestamp") or now),
        "tx": event.get("tx_hash") or event.get("dedupe_key"),
        "score": int(event.get("score") or 0),
        "amt": parse_amount_human(event),
    }
    # use wall clock if chain ts missing/old
    if row["ts"] < now - WINDOW_SEC * 3:
        row["ts"] = now

    entries = [e for e in buckets.get(key, []) if now - float(e.get("ts") or 0) <= WINDOW_SEC]
    # dedupe same tx
    tx = row.get("tx")
    if tx and any(e.get("tx") == tx for e in entries):
        buckets[key] = entries
        data["buckets"] = buckets
        _save(data)
        return event
    entries.append(row)
    buckets[key] = entries[-40:]
    # prune other buckets lightly
    stale = [k for k, v in buckets.items() if not v or now - float(v[-1].get("ts") or 0) > WINDOW_SEC * 2]
    for k in stale[:50]:
        buckets.pop(k, None)
    data["buckets"] = buckets
    _save(data)

    n = len(entries)
    if n < MIN_COUNT:
        return event

    boost = min(30, SCORE_BOOST + max(0, n - MIN_COUNT) * 3)
    old = int(event.get("score") or 0)
    new = max(0, min(100, old + boost))
    if new == old:
        return event

    event["score"] = new
    event["burst_n"] = n
    event["burst_boost"] = boost
    reasons = list(event.get("reasons") or [])
    reasons_uk = list(event.get("reasons_uk") or [])
    reasons.append(f"burst: {n} small transfers same wallet/token in {WINDOW_SEC // 60}m (+{boost})")
    reasons_uk.append(f"пачка: {n} дрібних переказів той самий гаманець/токен за {WINDOW_SEC // 60}хв (+{boost})")
    event["reasons"] = reasons
    event["reasons_uk"] = reasons_uk
    # re-tier lightly
    if new >= 55:
        event["tier"] = "actionable"
    elif new >= 35:
        event["tier"] = "watch"
    event["summary"] = f"ACT · score {new}/100 · burst×{n} · {event.get('symbol')}"
    event["summary_uk"] = f"ДІЯТИ · score {new}/100 · пачка×{n} · {event.get('symbol')}"
    return event
