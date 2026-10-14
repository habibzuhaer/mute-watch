"""Wiki pages EN/UK for intel address DB."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from intel.config import DATA_DIR, LANG
from intel.i18n import t
from intel.normalize import short

WIKI = DATA_DIR / "wiki"


def ensure() -> None:
    WIKI.mkdir(parents=True, exist_ok=True)
    (WIKI / "addresses").mkdir(parents=True, exist_ok=True)
    for name, body in {
        "memory": "# memory / памʼять\n\n",
        "journal": "# journal / журнал\n\n",
        "clusters": "# clusters / сімʼї\n\n",
        "tokens": "# tokens / токени\n\n",
    }.items():
        p = WIKI / f"{name}.md"
        if not p.exists():
            p.write_text(body, encoding="utf-8")


def append(page: str, text: str, *, heading: str | None = None) -> Path:
    ensure()
    path = WIKI / f"{page}.md"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    block = f"\n---\n_{ts}_\n\n"
    if heading:
        block += f"## {heading}\n\n"
    block += text.rstrip() + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(block)
    return path


def upsert_address_card(card: dict[str, Any]) -> Path:
    ensure()
    addr = card.get("address") or ""
    chain = card.get("chain") or ""
    safe = f"{chain}_{addr}".replace("/", "_")[:120]
    path = WIKI / "addresses" / f"{safe}.md"
    lang = LANG
    lines = [
        f"# {short(addr)} ({chain})",
        "",
        f"- address: `{addr}`",
        f"- chain: {chain}",
        f"- tags: {', '.join(card.get('tags') or [])}",
        f"- family: {card.get('family_id') or '—'}",
        f"- in/out: {card.get('in_n')}/{card.get('out_n')}",
        f"- tokens: {', '.join((card.get('tokens') or [])[:12])}",
        "",
        f"_{t('wiki', lang)}_",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def sync_top(cards: list[dict[str, Any]], *, limit: int = 40) -> int:
    n = 0
    for c in cards[:limit]:
        upsert_address_card(c)
        n += 1
    return n
