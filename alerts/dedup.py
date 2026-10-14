"""Alert deduplication store."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from alerts.config import DEDUP_FILE, DEDUP_TTL_SEC


class AlertDedup:
    def __init__(self, path: Path | None = None, ttl_sec: int | None = None) -> None:
        self.path = path or DEDUP_FILE
        self.ttl_sec = ttl_sec if ttl_sec is not None else DEDUP_TTL_SEC
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = {k: float(v) for k, v in (raw or {}).items()}
        except Exception:
            self._data = {}
        self._gc()

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def _gc(self) -> None:
        now = time.time()
        stale = [k for k, ts in self._data.items() if now - ts > self.ttl_sec]
        for k in stale:
            del self._data[k]

    def seen(self, key: str) -> bool:
        if not key:
            return False
        self._gc()
        ts = self._data.get(key)
        if ts is None:
            return False
        return time.time() - ts <= self.ttl_sec

    def mark(self, key: str) -> None:
        if not key:
            return
        self._data[key] = time.time()
        self._save()

    def key_for(self, activity: dict[str, Any]) -> str:
        return str(
            activity.get("dedupe_key")
            or f"{activity.get('source')}:{activity.get('activity_type')}:{activity.get('symbol')}:{activity.get('address')}"
        )
