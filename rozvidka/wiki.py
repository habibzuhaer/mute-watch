"""Wiki: address base + notes pages (memory / journal / clusters / tokens / history)."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rozvidka.config import DATA_DIR, WIKI_DIR

_lock = threading.Lock()

PAGES = ("memory", "journal", "clusters", "tokens", "history", "identity")

_BOOTSTRAP = {
    "memory": (
        "# memory\n\n"
        "Цель цикла: искать **группы** и **отдельные адреса** для пампа (prep).\n"
        "Пиши сюда устойчивые гипотезы. Короткие ID — суффикс адреса.\n"
    ),
    "journal": "# journal\n\nХронология важных находок по обертам.\n",
    "clusters": "# clusters\n\nАктивные кластеры / семьи фандеров.\n",
    "tokens": "# tokens\n\nТокены и ранние покупатели под наблюдением.\n",
    "history": "# history\n\nСводка прошлых серий (тиша / шум / chase).\n",
    "identity": (
        "# identity\n\n"
        "Локальный агент Розвідка. Не торгует — только разведка.\n"
        "locked: true\n"
    ),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    (WIKI_DIR / "addresses").mkdir(parents=True, exist_ok=True)
    for name in PAGES:
        path = WIKI_DIR / f"{name}.md"
        if not path.exists():
            path.write_text(_BOOTSTRAP[name], encoding="utf-8")


def list_pages() -> list[dict[str, Any]]:
    ensure()
    out: list[dict[str, Any]] = []
    for name in PAGES:
        path = WIKI_DIR / f"{name}.md"
        locked = name == "identity"
        out.append(
            {
                "id": name,
                "path": str(path.relative_to(DATA_DIR)),
                "locked": locked,
                "bytes": path.stat().st_size if path.exists() else 0,
            }
        )
    addr_n = len(list((WIKI_DIR / "addresses").glob("*.md")))
    out.append({"id": "addresses", "path": "wiki/addresses/", "locked": False, "count": addr_n})
    return out


def read_page(name: str, *, max_chars: int = 6000) -> str:
    ensure()
    name = _safe_name(name)
    if name == "addresses":
        return _index_addresses(max_chars=max_chars)
    path = WIKI_DIR / f"{name}.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:max_chars]


def append_page(name: str, text: str, *, heading: str | None = None) -> str:
    ensure()
    name = _safe_name(name)
    if name == "identity":
        raise ValueError("identity page is locked")
    if name == "addresses":
        raise ValueError("use upsert_address for address notes")
    path = WIKI_DIR / f"{name}.md"
    block = text.strip()
    if heading:
        block = f"## {heading.strip()}\n\n{block}"
    with _lock:
        prev = path.read_text(encoding="utf-8") if path.exists() else ""
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        chunk = f"\n\n---\n_{stamp}_\n\n{block}\n"
        path.write_text(prev + chunk, encoding="utf-8")
    return str(path)


def upsert_address(
    address: str,
    *,
    note: str,
    tags: list[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> str:
    ensure()
    addr = _norm_addr(address)
    if not addr:
        raise ValueError("bad address")
    path = WIKI_DIR / "addresses" / f"{addr}.md"
    tags = tags or []
    meta = meta or {}
    with _lock:
        prev = path.read_text(encoding="utf-8") if path.exists() else ""
        if not prev:
            short = addr[:6] + "…" + addr[-4:]
            prev = (
                f"# {short}\n\n"
                f"- address: `{addr}`\n"
                f"- tags: {', '.join(tags) or '—'}\n"
                f"- updated: {_now()}\n\n"
            )
            if meta:
                prev += "```json\n" + json.dumps(meta, ensure_ascii=False, indent=2) + "\n```\n\n"
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        path.write_text(prev + f"\n### {stamp}\n\n{note.strip()}\n", encoding="utf-8")
    return str(path)


def read_address(address: str, *, max_chars: int = 4000) -> str:
    ensure()
    addr = _norm_addr(address)
    path = WIKI_DIR / "addresses" / f"{addr}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:max_chars]


def search(query: str, *, limit: int = 12) -> list[dict[str, Any]]:
    ensure()
    q = (query or "").strip().lower()
    if not q:
        return []
    hits: list[dict[str, Any]] = []
    for path in list(WIKI_DIR.glob("*.md")) + list((WIKI_DIR / "addresses").glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if q in text.lower() or q in path.name.lower():
            hits.append(
                {
                    "path": str(path.relative_to(DATA_DIR)),
                    "snippet": _snippet(text, q),
                }
            )
        if len(hits) >= limit:
            break
    return hits


def snapshot_for_prompt(*, max_chars: int = 5000) -> str:
    """Compact wiki digest for the LLM."""
    ensure()
    parts: list[str] = []
    budget = max_chars
    for name in ("memory", "clusters", "journal", "tokens"):
        body = read_page(name, max_chars=min(1200, budget))
        if not body:
            continue
        parts.append(f"### wiki/{name}\n{body}")
        budget -= len(body)
        if budget < 400:
            break
    return "\n\n".join(parts)[:max_chars]


def _index_addresses(*, max_chars: int) -> str:
    files = sorted((WIKI_DIR / "addresses").glob("*.md"), key=lambda p: -p.stat().st_mtime)[:40]
    lines = [f"# addresses ({len(list((WIKI_DIR / 'addresses').glob('*.md')))} total)\n"]
    for p in files:
        lines.append(f"- `{p.stem}`")
    return "\n".join(lines)[:max_chars]


def _safe_name(name: str) -> str:
    name = (name or "").strip().lower().replace(".md", "")
    if name not in PAGES and name != "addresses":
        raise ValueError(f"unknown wiki page: {name}")
    return name


def _norm_addr(address: str) -> str:
    a = (address or "").strip().lower()
    if a.startswith("0x") and len(a) == 42 and re.fullmatch(r"0x[0-9a-f]{40}", a):
        return a
    return ""


def _snippet(text: str, q: str, radius: int = 80) -> str:
    low = text.lower()
    i = low.find(q)
    if i < 0:
        return text[:160].replace("\n", " ")
    a = max(0, i - radius)
    b = min(len(text), i + len(q) + radius)
    return text[a:b].replace("\n", " ")
