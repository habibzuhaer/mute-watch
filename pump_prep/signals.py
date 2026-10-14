"""Explicit signal scoring — why a match/event matters, 0–100 + reasons."""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

# Telegram / actionable threshold (override via SIGNAL_MIN_SCORE)
MIN_SCORE = int(os.getenv("SIGNAL_MIN_SCORE", "55"))
WATCH_SCORE = int(os.getenv("SIGNAL_WATCH_SCORE", "35"))

# Role weights (who is on the other side)
_ROLE_BASE: dict[str, int] = {
    "seed": 42,
    "mm": 42,
    "fund": 38,
    "accused": 40,
    "watch": 28,
    "cex": 14,
    "bridge": 18,
    "": 0,
}

# Known high-interest entities get a bump
_ENTITY_BUMP: dict[str, int] = {
    "dwf labs": 12,
    "gotbit": 18,
    "cls global": 16,
    "zm quant": 14,
    "wintermute": 10,
    "gsr": 8,
    "jump": 8,
}


@dataclass
class ScoredSignal:
    score: int
    tier: str  # actionable | watch | noise
    reasons: list[str] = field(default_factory=list)  # English (default / Telegram)
    reasons_uk: list[str] = field(default_factory=list)
    kind: str = ""  # cex_deposit | fund_touch | new_token_in | expand_hit
    summary: str = ""
    summary_uk: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rb(en: str, uk: str, reasons: list[str], reasons_uk: list[str]) -> None:
    reasons.append(en)
    reasons_uk.append(uk)


def _tier(score: int) -> str:
    if score >= MIN_SCORE:
        return "actionable"
    if score >= WATCH_SCORE:
        return "watch"
    return "noise"


def _age_points(age_days: Any) -> tuple[int, str | None, str | None]:
    if age_days is None or age_days == "":
        return 0, None, None
    try:
        d = int(float(age_days))
    except (TypeError, ValueError):
        return 0, None, None
    if d < 14:
        return 22, f"very young token ({d}d)", f"дуже молодий токен ({d} дн)"
    if d < 45:
        return 16, f"young token ({d}d)", f"молодий токен ({d} дн)"
    if d < 120:
        return 10, f"age {d}d", f"вік {d} дн"
    if d < 365:
        return 4, f"age {d}d", f"вік {d} дн"
    return 0, f"old token ({d}d)", f"старий токен ({d} дн)"


def _recency_points(timestamp: Any) -> tuple[int, str | None, str | None]:
    if not timestamp:
        return 0, None, None
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return 0, None, None
    age_sec = max(0, int(time.time()) - ts)
    days = age_sec / 86400
    if days <= 2:
        return 18, f"fresh link (on-chain {days:.1f}d ago)", f"зв’язок свіжий (on-chain {days:.1f} дн тому)"
    if days <= 14:
        return 12, f"recent link ({days:.0f}d ago)", f"зв’язок недавній ({days:.0f} дн тому)"
    if days <= 60:
        return 6, f"link {days:.0f}d ago", f"зв’язок {days:.0f} дн тому"
    if days <= 180:
        return 2, f"old link ({days:.0f}d ago)", f"зв’язок старий ({days:.0f} дн тому)"
    return 0, f"very old link ({days:.0f}d ago)", f"зв’язок давно ({days:.0f} дн тому)"


def _had_pump(ath_chg: Any, ath: Any, price: Any) -> bool:
    if ath_chg is not None:
        try:
            if float(ath_chg) <= -50.0:
                return True
        except (TypeError, ValueError):
            pass
    try:
        if ath and price and float(price) > 0 and float(ath) / float(price) >= 2.0:
            return True
    except (TypeError, ValueError):
        pass
    return False


def score_match(
    *,
    match_role: str | None = None,
    match_entity: str | None = None,
    direction: str | None = None,
    is_token_itself: bool = False,
    age_days: Any = None,
    ath_chg: Any = None,
    ath: Any = None,
    price: Any = None,
    timestamp: Any = None,
    via: str | None = None,
    wallet_known: bool = True,
    hop: int | None = None,
    same_amount: bool = False,
    same_amount_hint: str | None = None,
    fresh_wallet: bool = False,
    fresh_wallet_days: float | None = None,
    amount_human: float | None = None,
) -> ScoredSignal:
    """Score a graph match (deployer/expand ↔ known entity/CEX/bridge)."""
    from pump_prep.obfuscation import hop_from_via

    reasons: list[str] = []
    reasons_uk: list[str] = []
    score = 0
    role = (match_role or "").lower().strip()
    entity = (match_entity or "").strip()
    entity_l = entity.lower()
    direction = (direction or "").lower()
    hop_n = hop if hop is not None else hop_from_via(via)

    base = _ROLE_BASE.get(role, 8 if entity else 0)
    score += base
    if role in ("seed", "mm", "fund", "accused", "watch"):
        _rb(
            f"counterparty = known player ({entity or role})",
            f"контрагент = відомий гравець ({entity or role})",
            reasons,
            reasons_uk,
        )
    elif role == "cex":
        _rb(
            f"counterparty = CEX hot ({entity or 'cex'})",
            f"контрагент = CEX hot ({entity or 'cex'})",
            reasons,
            reasons_uk,
        )
    elif role == "bridge":
        _rb(
            f"counterparty = bridge ({entity or 'bridge'}) — possible cross-chain hop",
            f"контрагент = bridge ({entity or 'bridge'}) — можливий cross-chain hop",
            reasons,
            reasons_uk,
        )
    elif entity:
        _rb(f"counterparty labelled: {entity}", f"контрагент позначений: {entity}", reasons, reasons_uk)
        score += 8

    for key, bump in _ENTITY_BUMP.items():
        if key in entity_l:
            score += bump
            _rb(
                f"+entity weight «{entity}» (+{bump})",
                f"+вага сутності «{entity}» (+{bump})",
                reasons,
                reasons_uk,
            )
            break

    kind = "fund_touch"
    if role == "bridge":
        kind = "bridge_hop"
        if direction == "out":
            score += 10
            _rb(
                "OUT to bridge → chain switch / graph break",
                "OUT на bridge → зміна мережі / обрив графа",
                reasons,
                reasons_uk,
            )
        elif direction == "in":
            score += 6
            _rb(
                "IN from bridge → arrival from another chain",
                "IN з bridge → прихід з іншої мережі",
                reasons,
                reasons_uk,
            )
    elif role == "cex":
        kind = "cex_deposit" if direction == "out" else "cex_touch"
        if direction == "out":
            score += 16
            _rb(
                "OUT to CEX → possible sale/listing prep",
                "OUT на CEX → можлива підготовка до продажу/лістингу",
                reasons,
                reasons_uk,
            )
        elif direction == "in":
            score += 6
            _rb(
                "IN from CEX → withdrawal/top-up from exchange",
                "IN з CEX → вивід/поповнення з біржі",
                reasons,
                reasons_uk,
            )
    else:
        if direction == "out":
            score += 12
            _rb("OUT to known address", "OUT до відомої адреси", reasons, reasons_uk)
        elif direction == "in":
            score += 10
            _rb("IN from known address", "IN від відомої адреси", reasons, reasons_uk)

    if is_token_itself and direction == "out":
        score += 8
        _rb(
            "distributing the token itself (not a foreign ERC-20)",
            "це роздача самого токена (не чужий ERC-20)",
            reasons,
            reasons_uk,
        )

    ap, ar_en, ar_uk = _age_points(age_days)
    score += ap
    if ar_en:
        _rb(ar_en, ar_uk or ar_en, reasons, reasons_uk)

    rp, rr_en, rr_uk = _recency_points(timestamp)
    score += rp
    if rr_en:
        _rb(rr_en, rr_uk or rr_en, reasons, reasons_uk)

    if _had_pump(ath_chg, ath, price):
        score -= 14
        _rb(
            "already had a strong ATH pump (−14: not a long thesis on ATH)",
            "вже був сильний ATH-памп (−14: не long-тезис по ATH)",
            reasons,
            reasons_uk,
        )
        try:
            if ath_chg is not None:
                _rb(
                    f"now {float(ath_chg):+.0f}% from ATH",
                    f"зараз {float(ath_chg):+.0f}% від ATH",
                    reasons,
                    reasons_uk,
                )
        except (TypeError, ValueError):
            pass

    if hop_n == 1 or via == "expand":
        score += 4
        _rb("found on 1-hop expand", "знайдено на 1-hop expand", reasons, reasons_uk)
        kind = kind if kind not in ("fund_touch",) else "expand_hit"
    elif hop_n >= 2:
        score += 10
        _rb(
            f"found on {hop_n}-hop (intermediate wallet / obfuscation)",
            f"знайдено на {hop_n}-hop (проміжний гаманець / обфускація)",
            reasons,
            reasons_uk,
        )
        kind = "hop_chain"

    if same_amount:
        score += 14
        hint = same_amount_hint or (f"≈{amount_human:g}" if amount_human else "similar amount")
        _rb(
            f"same-amount hop ({hint}, ±0.5%) — classic A→B→C chain",
            f"same-amount hop ({hint}, ±0.5%) — класичний ланцюжок A→B→C",
            reasons,
            reasons_uk,
        )
        if kind in ("fund_touch", "expand_hit"):
            kind = "hop_chain"

    if fresh_wallet:
        d = f"{fresh_wallet_days:.0f}" if fresh_wallet_days is not None else "?"
        score += 12
        _rb(
            f"fresh wallet (~{d}d since first activity) — typical transit EOA",
            f"fresh wallet (~{d} дн з першої активності) — типовий проміжний EOA",
            reasons,
            reasons_uk,
        )
        if kind in ("fund_touch", "expand_hit"):
            kind = "fresh_hop"

    if not wallet_known:
        score = max(0, score - 20)
        _rb("address not in seed/CEX — downgraded", "адреса не в seed/CEX — знижено", reasons, reasons_uk)

    score = max(0, min(100, int(score)))
    tier = _tier(score)
    who = entity or role or "?"
    if tier == "actionable":
        summary, summary_uk = f"ACT · score {score}/100 · {who}", f"ДІЯТИ · score {score}/100 · {who}"
    elif tier == "watch":
        summary, summary_uk = f"WATCH · score {score}/100 · {who}", f"СПОСТЕРІГАТИ · score {score}/100 · {who}"
    else:
        summary, summary_uk = f"noise · score {score}/100 · {who}", f"шум · score {score}/100 · {who}"
    return ScoredSignal(
        score=score,
        tier=tier,
        reasons=reasons,
        reasons_uk=reasons_uk,
        kind=kind,
        summary=summary,
        summary_uk=summary_uk,
    )


def score_prep_event(event: dict[str, Any]) -> ScoredSignal:
    """Score a live MUTE prep alert (obscure IN or CEX OUT)."""
    reasons: list[str] = []
    reasons_uk: list[str] = []
    score = 0
    prep = event.get("prep_type") or ""
    symbol = event.get("symbol") or "?"
    cex = event.get("cex")
    ts = event.get("timestamp")

    if prep == "cex_deposit":
        score += 48
        kind = "cex_deposit"
        _rb(
            f"live: OUT obscure token → CEX ({cex or '?'})",
            f"live: OUT obscure token → CEX ({cex or '?'})",
            reasons,
            reasons_uk,
        )
        _rb(
            "classic prep pattern before sale/listing",
            "класичний prep-патерн перед продажем/лістингом",
            reasons,
            reasons_uk,
        )
        if cex:
            score += 8
            _rb(f"exchange: {cex}", f"біржа: {cex}", reasons, reasons_uk)
    else:
        score += 36
        kind = "new_token_in"
        _rb(
            f"live: obscure token IN ({symbol})",
            f"live: obscure token IN ({symbol})",
            reasons,
            reasons_uk,
        )
        _rb(
            "new/rare asset onto a seed wallet",
            "новий/рідкісний актив на seed-гаманець",
            reasons,
            reasons_uk,
        )

    label = (event.get("wallet_label") or "").lower()
    for key, bump in _ENTITY_BUMP.items():
        if key in label:
            score += bump
            _rb(
                f"wallet linked to «{key}» (+{bump})",
                f"гаманець пов’язаний з «{key}» (+{bump})",
                reasons,
                reasons_uk,
            )
            break
    if "dwf" in label:
        score += 6
        _rb("DWF-related watchlist", "DWF-пов’язаний watchlist", reasons, reasons_uk)

    rp, rr_en, rr_uk = _recency_points(ts)
    score += rp
    if rr_en:
        _rb(rr_en, rr_uk or rr_en, reasons, reasons_uk)

    score += 10
    _rb("live-monitor event (+10)", "подія з live-монітора (+10)", reasons, reasons_uk)

    score = max(0, min(100, int(score)))
    tier = _tier(score)
    tag = prep or kind
    if tier == "actionable":
        summary = f"ACT · score {score}/100 · {tag} · {symbol}"
        summary_uk = f"ДІЯТИ · score {score}/100 · {tag} · {symbol}"
    elif tier == "watch":
        summary = f"WATCH · score {score}/100 · {tag} · {symbol}"
        summary_uk = f"СПОСТЕРІГАТИ · score {score}/100 · {tag} · {symbol}"
    else:
        summary = f"noise · score {score}/100 · {tag} · {symbol}"
        summary_uk = f"шум · score {score}/100 · {tag} · {symbol}"
    return ScoredSignal(
        score=score,
        tier=tier,
        reasons=reasons,
        reasons_uk=reasons_uk,
        kind=kind,
        summary=summary,
        summary_uk=summary_uk,
    )


def passes_telegram(scored: ScoredSignal, min_score: int | None = None) -> bool:
    return scored.score >= (MIN_SCORE if min_score is None else min_score)
