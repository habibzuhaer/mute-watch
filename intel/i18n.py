"""EN / UK strings for intel UI and logs."""

from __future__ import annotations

from typing import Any

PACK: dict[str, dict[str, str]] = {
    "en": {
        "name": "Intel",
        "subtitle": "Solana + BNB families · pre-pump · address DB",
        "goal": "Collect transfers → families (≥1 edge) → spike/pre-pump tags → wiki DB",
        "cycle": "cycle",
        "queue": "queue",
        "addresses": "addresses",
        "edges": "edges",
        "families": "families",
        "spikes": "activity spikes",
        "prepump": "pre-pump",
        "sol": "Solana",
        "bnb": "BNB",
        "evm": "EVM legacy",
        "collect_running": "collect ON",
        "collect_off": "collect off",
        "profit": "early / profit",
        "neighbors": "new neighbors",
        "wiki": "wiki",
        "lang": "EN",
    },
    "uk": {
        "name": "Інтел",
        "subtitle": "Solana + BNB сімʼї · пре-памп · база адрес",
        "goal": "Збір переказів → сімʼї (≥1 ребро) → спайки/пре-памп → вікі-БД",
        "cycle": "цикл",
        "queue": "черга",
        "addresses": "адреси",
        "edges": "ребра",
        "families": "сімʼї",
        "spikes": "спайки активності",
        "prepump": "пре-памп",
        "sol": "Solana",
        "bnb": "BNB",
        "evm": "EVM (старий граф)",
        "collect_running": "збір ON",
        "collect_off": "збір off",
        "profit": "early / profit",
        "neighbors": "нові сусіди",
        "wiki": "вікі",
        "lang": "UK",
    },
}


def t(key: str, lang: str | None = None) -> str:
    from intel.config import LANG

    lang = (lang or LANG or "uk").lower()
    if lang not in PACK:
        lang = "uk"
    return PACK[lang].get(key) or PACK["en"].get(key) or key


def both(key: str) -> dict[str, str]:
    return {"en": t(key, "en"), "uk": t(key, "uk")}


def snapshot_i18n() -> dict[str, Any]:
    return {"en": PACK["en"], "uk": PACK["uk"]}
