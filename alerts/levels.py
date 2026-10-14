"""Alert LEVELS with explicit → ACTION guidance (uk + en).

Levels: CRITICAL > ACT > WATCH > INFO > NOISE
Each level defines push policy and default operator action.
Per-template actions override via ACTIONS registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LevelDef:
    name: str
    push: bool
    priority: int
    min_score: int
    action_en: str
    action_uk: str
    emoji: str


LEVELS: dict[str, LevelDef] = {
    "CRITICAL": LevelDef(
        name="CRITICAL",
        push=True,
        priority=100,
        min_score=70,
        emoji="🔴",
        action_en=(
            "→ ACTION NOW: stop other tasks · open Hub + Intel · trace funders/deployer · "
            "add all counterparties to watch · prepare entry/exit plan before crowd."
        ),
        action_uk=(
            "→ ДІЯ ЗАРАЗ: зупинити інше · Hub + Intel · простежити funder/deployer · "
            "додати контрагентів у watch · план входу/виходу до натовпу."
        ),
    ),
    "ACT": LevelDef(
        name="ACT",
        push=True,
        priority=80,
        min_score=55,
        emoji="🚨",
        action_en=(
            "→ ACTION: open Signals Hub · check {symbol} mcap/liquidity · add wallet to Intel queue · "
            "enable watch · verify MM/CEX match on graph."
        ),
        action_uk=(
            "→ ДІЯ: відкрити Signals Hub · перевірити {symbol} mcap/ліквідність · додати гаманець у Intel queue · "
            "увімкнути watch · перевірити MM/CEX на графі."
        ),
    ),
    "WATCH": LevelDef(
        name="WATCH",
        push=True,
        priority=50,
        min_score=40,
        emoji="👀",
        action_en=(
            "→ WATCH: add to panel watchlist · no trade yet · recheck in next cycle · "
            "note score/reasons in journal."
        ),
        action_uk=(
            "→ СТЕЖИТИ: додати в watchlist панелі · без угоди · перепровірити наступний цикл · "
            "записати score/причини в журнал."
        ),
    ),
    "INFO": LevelDef(
        name="INFO",
        push=False,
        priority=20,
        min_score=0,
        emoji="ℹ️",
        action_en="→ LOG: journal only · review in daily pass · no Telegram unless escalated.",
        action_uk="→ ЛОГ: лише журнал · перегляд раз на день · без Telegram без ескалації.",
    ),
    "NOISE": LevelDef(
        name="NOISE",
        push=False,
        priority=0,
        min_score=0,
        emoji="·",
        action_en="→ IGNORE: deduped noise · do nothing.",
        action_uk="→ ІГНОР: шум · dedup · нічого не робити.",
    ),
}

# Per activity_type action overrides (placeholders allowed)
ACTIONS: dict[str, dict[str, str]] = {
    "prep_live": {
        "en": (
            "→ ACTION: obscure token touch on seed wallet · open Prep report · "
            "check if deployer/MM linked · Intel expand from {from_address_short}."
        ),
        "uk": (
            "→ ДІЯ: obscure token на seed · Prep report · "
            "перевірити deployer/MM · Intel expand з {from_address_short}."
        ),
    },
    "prep_new_token_in": {
        "en": "→ ACTION: new token IN before pump · score deployer cluster · add token to hub watch.",
        "uk": "→ ДІЯ: новий token IN до пампа · оцінити deployer cluster · token у hub watch.",
    },
    "prep_cex_deposit": {
        "en": "→ ACTION: funds moving to CEX {cex} · possible distribution · track outflow chain.",
        "uk": "→ ДІЯ: кошти на CEX {cex} · можливий розподіл · стежити outflow chain.",
    },
    "dwf_inbound": {
        "en": "→ ACTION: MM/seed inbound · confirm amount · cross-check graph signals for same token.",
        "uk": "→ ДІЯ: MM/seed inbound · підтвердити суму · зіставити з graph signals по token.",
    },
    "graph_act": {
        "en": "→ ACTION: graph match {signal_kind} · open graph_live · expand hop-1 neighbors · Intel enqueue.",
        "uk": "→ ДІЯ: graph match {signal_kind} · graph_live · expand hop-1 · Intel enqueue.",
    },
    "graph_watch": {
        "en": "→ WATCH: graph pattern {signal_kind} · monitor next scanner cycle.",
        "uk": "→ СТЕЖИТИ: graph pattern {signal_kind} · наступний цикл scanner.",
    },
    "intel_spike": {
        "en": "→ ACTION: activity spike on {symbol} · check pre-pump wallets · rozvidka family pass.",
        "uk": "→ ДІЯ: spike активності {symbol} · pre-pump гаманці · rozvidka family pass.",
    },
    "intel_prepump": {
        "en": "→ ACTION: early beneficiary before ATH · expand {address_short} on ethereum+bnb · wiki label.",
        "uk": "→ ДІЯ: early beneficiary до ATH · expand {address_short} eth+bnb · wiki label.",
    },
    "rozvidka_critical": {
        "en": "→ ACTION: rozvidka pattern {finding_type} · read wiki card · Intel priority queue · DeepSeek turn.",
        "uk": "→ ДІЯ: rozvidka pattern {finding_type} · wiki · Intel priority queue · DeepSeek turn.",
    },
    "rozvidka_watch": {
        "en": "→ WATCH: rozvidka {finding_type} · review on next turn · no trade.",
        "uk": "→ СТЕЖИТИ: rozvidka {finding_type} · наступний turn · без угоди.",
    },
    "system_stale": {
        "en": "→ ACTION: process stale · ./scripts/status.sh · restart affected service from panel.",
        "uk": "→ ДІЯ: процес stale · ./scripts/status.sh · перезапуск з панелі.",
    },
    "hub_priority": {
        "en": "→ ACTION: multi-pump hub touch · open hub wiki · Intel p100 queue already set · trace sent_to.",
        "uk": "→ ДІЯ: multi-pump hub · hub wiki · Intel p100 · простежити sent_to.",
    },
}


def resolve_level(activity: dict[str, Any]) -> str:
    """Map score/tier/type to LEVEL name."""
    explicit = (activity.get("level") or "").upper()
    if explicit in LEVELS:
        return explicit

    tier = (activity.get("tier") or "").lower()
    score = int(activity.get("score") or 0)
    atype = activity.get("activity_type") or activity.get("type") or ""

    if tier == "noise" or score < 25:
        return "NOISE"
    if tier == "actionable" or score >= LEVELS["CRITICAL"].min_score:
        if score >= 85 or atype in {"rozvidka_critical", "hub_priority"}:
            return "CRITICAL"
        return "ACT"
    if tier == "watch" or score >= LEVELS["WATCH"].min_score:
        return "WATCH"
    if score >= 25:
        return "INFO"
    return "NOISE"


def action_text(activity: dict[str, Any], level: str, lang: str) -> str:
    lang = "uk" if lang in {"uk", "ua"} else "en"
    atype = activity.get("activity_type") or activity.get("type") or "generic"
    base = ACTIONS.get(atype, {})
    text = base.get(lang) or LEVELS.get(level, LEVELS["INFO"]).action_uk if lang == "uk" else LEVELS.get(level, LEVELS["INFO"]).action_en
    try:
        return text.format_map(_SafeFmt(activity))
    except Exception:
        return text


class _SafeFmt(dict):
    def __missing__(self, key: str) -> str:
        return "?"


def should_push(level: str, *, push_watch: bool = True) -> bool:
    lv = LEVELS.get(level)
    if not lv:
        return False
    if level == "WATCH" and not push_watch:
        return False
    return lv.push
