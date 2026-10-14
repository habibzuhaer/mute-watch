"""Family frames, patron role, and go/submit/where — first cut, numbers not LLM."""

from __future__ import annotations

from typing import Any

GAS_STABLE = {
    "eth",
    "bnb",
    "sol",
    "matic",
    "avax",
    "usdt",
    "usdc",
    "dai",
    "native",
    "wbnb",
    "weth",
    "usdce",
    "usdbc",
}

PATRON_HINTS = ("mm", "seed", "fund", "dwf", "patron", "market_maker", "lab", "jump", "wintermute")
CEX_HINTS = ("cex", "exchange", "binance", "gate", "okx", "bybit", "kucoin", "mexc")

MOVE_UK = {"go": "ходити", "submit": "подати", "watch": "стежити", "hand": "рука"}
RECENT_SEC = 86400
AMOUNT_DEV = 2.0
BURST_DEV = 2.0


def fnum(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def median(xs: list[float]) -> float | None:
    if not xs:
        return None
    ys = sorted(xs)
    n = len(ys)
    mid = n // 2
    if n % 2:
        return float(ys[mid])
    return (ys[mid - 1] + ys[mid]) / 2.0


def _blob(card: dict[str, Any] | None) -> str:
    c = card or {}
    tags = " ".join(str(t) for t in (c.get("tags") or []))
    return " ".join(
        str(x or "") for x in (c.get("role"), c.get("entity"), c.get("label"), tags)
    ).lower()


def is_cex_card(card: dict[str, Any] | None) -> bool:
    b = _blob(card)
    return any(h in b for h in CEX_HINTS) and "mm" not in b


def is_patron_card(card: dict[str, Any] | None) -> bool:
    if is_cex_card(card):
        return False
    b = _blob(card)
    return any(h in b for h in PATRON_HINTS)


def pick_patron(
    members: list[str],
    *,
    addrs: dict[str, dict[str, Any]] | None = None,
    out_weight: dict[str, float] | None = None,
    hub_key: str | None = None,
) -> dict[str, Any]:
    addrs = addrs or {}
    out_weight = out_weight or {}
    best = hub_key or (members[0] if members else "")
    best_s = -1.0
    for m in members:
        card = addrs.get(m) or {}
        s = float(out_weight.get(m) or 0)
        s += min(40.0, float(card.get("out_n") or 0))
        if is_patron_card(card):
            s += 120.0
        if is_cex_card(card):
            s -= 40.0
        if m == hub_key:
            s += 8.0
        if s > best_s:
            best_s = s
            best = m
    card = addrs.get(best) or {}
    chain, addr = ("", best)
    if best and ":" in best:
        chain, addr = best.split(":", 1)
    labeled = is_patron_card(card)
    return {
        "key": best,
        "address": addr,
        "chain": chain,
        "short": (card.get("short") or (addr[:4] + "…" + addr[-4:] if len(addr) > 10 else addr)),
        "score": round(best_s, 1),
        "confident": bool(labeled or best_s >= 20),
        "source": "label" if labeled else "flow",
        "entity": card.get("entity") or card.get("label") or "",
    }


def frames_from_amounts(
    amounts: list[float],
    recent: list[float],
    timestamps: list[int],
    *,
    recent_n: int = 0,
    chain: str = "",
    now_ts: float | None = None,
) -> dict[str, Any]:
    med = median(amounts)
    rec_med = median(recent)
    ratio = (rec_med / med) if med and rec_med and med > 0 else None
    span = 0
    if timestamps:
        span = max(timestamps) - min(timestamps)
    expected = 1.0
    if span and now_ts is not None:
        # how many txs we'd expect in RECENT_SEC given historical density
        density = len(timestamps) / max(span, 1)
        expected = max(1.0, density * RECENT_SEC)
    burst = (recent_n or len(recent)) / expected if expected else None
    amt_dev = bool(ratio is not None and ratio >= AMOUNT_DEV)
    burst_dev = bool(burst is not None and burst >= BURST_DEV)
    deviant = amt_dev or burst_dev
    status = "вихід" if deviant else "норма"
    return {
        "chain": chain,
        "n": len(amounts),
        "recent_n": recent_n or len(recent),
        "median": round(med, 6) if med is not None else None,
        "recent_median": round(rec_med, 6) if rec_med is not None else None,
        "amount_ratio": round(ratio, 2) if ratio is not None else None,
        "burst": round(burst, 2) if burst is not None else None,
        "span_sec": span or None,
        "deviant": deviant,
        "amount_dev": amt_dev,
        "burst_dev": burst_dev,
        "status": status,
    }


def venue_of(signal: dict[str, Any] | None, *, default_chain: str = "") -> dict[str, str]:
    s = signal or {}
    kind = str(s.get("signal_kind") or s.get("kind") or "").lower()
    role = str(s.get("match_role") or s.get("role") or "").lower()
    chain = str(s.get("chain") or default_chain or "unknown")
    venue = "dex"
    if "bridge" in kind or "bridge" in role:
        venue = "bridge"
    elif "cex" in kind or "cex" in role or any(h in kind for h in CEX_HINTS):
        venue = "cex"
    hint = f"{chain} / {venue}"
    return {"chain": chain, "venue": venue, "hint": hint}


def decide_move(
    *,
    frames: dict[str, Any] | None = None,
    patron: dict[str, Any] | None = None,
    family_score: int = 0,
    signal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """go = ходити; submit = подати сигнал; watch = стежити; hand = спитати."""
    fr = frames or {}
    pat = patron or {}
    sig = signal or {}
    score = int(sig.get("score") or family_score or 0)
    where = venue_of(sig, default_chain=str(fr.get("chain") or pat.get("chain") or ""))
    thin = not fr.get("n") and not pat.get("confident")

    if thin and score < 35:
        move, why = "hand", "мало даних по сімʼї — рука"
    elif score >= 55 and where["venue"] == "cex":
        move, why = "submit", "сильний бал, але CEX — подати, не ходити вслід"
    elif score >= 55 and fr.get("deviant"):
        move, why = "go", "вихід за рамки сімʼї · сильний бал"
    elif score >= 55 and fr.get("n"):
        move, why = "go", "сильний бал · рамки в нормі, все одно перевірити tx"
    elif score >= 55:
        move, why = "submit", "сильний бал, але рамок сімʼї ще немає — подати"
    elif fr.get("deviant") and score >= 35:
        move, why = "submit", "рамки зламані, бал середній — подати"
    elif score >= 35:
        move, why = "submit", "стежити / подати, не ходити"
    elif fr.get("deviant"):
        move, why = "submit", "вихід за рамки, бал слабкий — подати"
    else:
        move, why = "watch", "в нормі сімʼї"

    return {
        "move": move,
        "move_uk": MOVE_UK.get(move, move),
        "where": where,
        "why": why,
        "score": score,
    }


def attach(
    family: dict[str, Any],
    *,
    addrs: dict[str, dict[str, Any]] | None = None,
    out_weight: dict[str, float] | None = None,
    amounts: list[float] | None = None,
    recent: list[float] | None = None,
    timestamps: list[int] | None = None,
    recent_n: int = 0,
    now_ts: float | None = None,
    signal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    members = list(family.get("members") or [])
    hub_key = family.get("hub_key") or ""
    if not hub_key and family.get("chain") and family.get("hub"):
        hub_key = f"{family.get('chain')}:{family.get('hub')}"
    patron = pick_patron(members, addrs=addrs, out_weight=out_weight, hub_key=hub_key)
    frames = frames_from_amounts(
        amounts or [],
        recent or [],
        timestamps or [],
        recent_n=recent_n,
        chain=str(family.get("chain") or patron.get("chain") or ""),
        now_ts=now_ts,
    )
    move = decide_move(
        frames=frames,
        patron=patron,
        family_score=int(family.get("score") or 0),
        signal=signal,
    )
    family["patron"] = patron
    family["frames"] = frames
    family["move"] = move
    return family
