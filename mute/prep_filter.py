"""Filter MUTE events for pump-prep alert mode + explicit score."""

from __future__ import annotations

from typing import Any

from pump_prep.cex_labels import cex_name, is_major_symbol
from pump_prep.signals import MIN_SCORE, passes_telegram, score_prep_event


def is_prep_signal(event: dict[str, Any]) -> bool:
    """Keep obscure token inbound, or token outbound to known CEX."""
    symbol = event.get("symbol") or ""
    kind = event.get("kind") or ""
    direction = event.get("direction") or ("in" if "IN" in kind else "out" if "OUT" in kind else "")

    if direction == "in" or kind.endswith("IN"):
        if kind.startswith("NATIVE"):
            return False
        return not is_major_symbol(symbol)

    if direction == "out" or "OUT" in kind:
        if is_major_symbol(symbol):
            return False
        dest = (event.get("to_address") or "").lower()
        return cex_name(dest) is not None

    return False


def annotate_prep(event: dict[str, Any]) -> dict[str, Any]:
    ev = dict(event)
    kind = ev.get("kind") or ""
    if "OUT" in kind:
        cex = cex_name(ev.get("to_address"))
        ev["prep_type"] = "cex_deposit"
        ev["cex"] = cex
    else:
        ev["prep_type"] = "new_token_in"
    scored = score_prep_event(ev)
    ev["score"] = scored.score
    ev["tier"] = scored.tier
    ev["reasons"] = scored.reasons
    ev["reasons_uk"] = scored.reasons_uk
    ev["signal_kind"] = scored.kind
    ev["summary"] = scored.summary
    ev["summary_uk"] = scored.summary_uk
    ev["telegram_worthy"] = passes_telegram(scored)
    ev["min_score_rule"] = MIN_SCORE
    return ev
