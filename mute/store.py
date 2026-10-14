from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


class SeenStore:
    """Dedup store so we only alert once per chain+tx+transfer key."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
                key TEXT PRIMARY KEY,
                seen_at REAL NOT NULL DEFAULT (strftime('%s','now'))
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def has(self, key: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM seen WHERE key=?", (key,))
        return cur.fetchone() is not None

    def add(self, key: str) -> None:
        self._conn.execute("INSERT OR IGNORE INTO seen(key) VALUES (?)", (key,))
        self._conn.commit()

    def add_many(self, keys: list[str]) -> None:
        self._conn.executemany(
            "INSERT OR IGNORE INTO seen(key) VALUES (?)",
            [(k,) for k in keys],
        )
        self._conn.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        cur = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
