"""Normalize activity payloads from mute / graph / intel / rozvidka."""

from __future__ import annotations

from typing import Any


def short_addr(value: str, n: int = 6) -> str:
    if not value:
        return "?"
    if len(value) <= n * 2 + 2:
        return value
    if value.startswith("0x"):
        return f"{value[: n + 2]}…{value[-n:]}"
    return f"{value[:n]}…{value[-n:]}"


def from_live_prep(event: dict[str, Any]) -> dict[str, Any]:
    prep = event.get("prep_type") or "prep_live"
    atype = {
        "new_token_in": "prep_new_token_in",
        "cex_deposit": "prep_cex_deposit",
    }.get(prep, "prep_live")
    direction = "out" if "OUT" in (event.get("kind") or "").upper() else "in"
    return {
        "source": "live_prep",
        "activity_type": atype,
        "score": int(event.get("score") or 0),
        "tier": event.get("tier"),
        "chain": event.get("chain"),
        "symbol": event.get("symbol"),
        "amount_fmt": event.get("amount_fmt"),
        "kind": event.get("kind"),
        "wallet_label": event.get("wallet_label"),
        "address": event.get("address"),
        "address_short": short_addr(event.get("address") or ""),
        "from_address": event.get("from_address"),
        "from_address_short": short_addr(event.get("from_address") or ""),
        "to_address": event.get("to_address"),
        "to_address_short": short_addr(event.get("to_address") or ""),
        "cex": event.get("cex"),
        "direction": direction,
        "signal_kind": event.get("signal_kind"),
        "reasons": event.get("reasons") or [],
        "reasons_uk": event.get("reasons_uk") or [],
        "tx_hash": event.get("tx_hash"),
        "explorer_tx": event.get("explorer_tx"),
        "timestamp": event.get("timestamp"),
        "dedupe_key": event.get("dedupe_key"),
    }


def from_dwf_inbound(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "dwf",
        "activity_type": "dwf_inbound",
        "score": 60,
        "tier": "actionable",
        "chain": event.get("chain"),
        "symbol": event.get("symbol"),
        "amount_fmt": event.get("amount_fmt"),
        "kind": event.get("kind"),
        "wallet_label": event.get("wallet_label", "DWF Labs"),
        "address": event.get("address"),
        "address_short": short_addr(event.get("address") or ""),
        "from_address": event.get("from_address"),
        "from_address_short": short_addr(event.get("from_address") or ""),
        "usd_hint": event.get("usd_hint"),
        "tx_hash": event.get("tx_hash"),
        "explorer_tx": event.get("explorer_tx"),
        "timestamp": event.get("timestamp"),
        "dedupe_key": event.get("dedupe_key"),
    }


def from_graph_signal(sig: dict[str, Any]) -> dict[str, Any]:
    score = int(sig.get("score") or 0)
    tier = sig.get("tier") or ("actionable" if score >= 55 else "watch" if score >= 40 else "noise")
    return {
        "source": "graph",
        "activity_type": "graph_act" if tier == "actionable" else "graph_watch",
        "score": score,
        "tier": tier,
        "chain": sig.get("chain"),
        "symbol": sig.get("symbol"),
        "signal_kind": sig.get("signal_kind"),
        "match_entity": sig.get("match_entity"),
        "direction": sig.get("direction"),
        "reasons": sig.get("reasons") or [],
        "reasons_uk": sig.get("reasons_uk") or [],
        "summary": sig.get("summary"),
        "hash": sig.get("hash"),
        "timestamp": sig.get("timestamp"),
        "dedupe_key": f"graph:{sig.get('hash') or sig.get('symbol')}:{sig.get('signal_kind')}:{sig.get('match_entity')}",
    }


def from_intel_spike(row: dict[str, Any]) -> dict[str, Any]:
    score = min(100, int(row.get("score") or 50))
    return {
        "source": "intel",
        "activity_type": "intel_spike",
        "type": "intel_spike",
        "score": score,
        "tier": "actionable" if score >= 55 else "watch",
        "chain": row.get("chain"),
        "symbol": row.get("symbol") or row.get("token"),
        "tx_n": row.get("tx") or row.get("tx_n"),
        "wallet_n": row.get("unique") or row.get("wallet_n"),
        "reasons": [f"spike tx={row.get('tx')} wallets={row.get('unique')}"],
        "dedupe_key": f"intel:spike:{row.get('chain')}:{row.get('symbol')}",
    }


def from_intel_prepump(row: dict[str, Any]) -> dict[str, Any]:
    score = int(row.get("score") or 0)
    toks = row.get("tokens") or []
    return {
        "source": "intel",
        "activity_type": "intel_prepump",
        "type": "intel_prepump",
        "score": score,
        "tier": "actionable" if score >= 55 else "watch" if score >= 36 else "noise",
        "chain": row.get("chain"),
        "address": row.get("address"),
        "address_short": row.get("short") or short_addr(row.get("address") or ""),
        "tokens": toks,
        "token_list": ", ".join(str(t) for t in toks[:8]),
        "token_n": row.get("token_n") or len(toks),
        "touches": row.get("touches"),
        "reasons": [f"early before ATH on {len(toks)} pump token(s)"],
        "reasons_uk": [f"ранній контакт до ATH · {len(toks)} pump token(s)"],
        "dedupe_key": f"intel:prepump:{row.get('key') or row.get('address')}",
    }


def from_rozvidka_finding(f: dict[str, Any]) -> dict[str, Any]:
    score = int(f.get("score") or 0)
    ftype = f.get("type") or "pattern"
    critical_types = {"wakeup", "entity_burst", "deployer_cluster", "serial_touch", "bridge"}
    is_crit = score >= 70 or ftype in critical_types
    return {
        "source": "rozvidka",
        "activity_type": "rozvidka_critical" if is_crit else "rozvidka_watch",
        "finding_type": ftype,
        "type": ftype,
        "score": score,
        "tier": "actionable" if is_crit else "watch",
        "title": f.get("title"),
        "entity": f.get("entity"),
        "address": f.get("address") or f.get("hub"),
        "address_short": f.get("short") or short_addr(f.get("address") or f.get("hub") or ""),
        "reasons": [f.get("title") or ftype],
        "reasons_uk": [f.get("title") or ftype],
        "dedupe_key": f"roz:{ftype}:{f.get('id') or f.get('title') or score}",
    }


def from_system_stale(proc: str, detail: str) -> dict[str, Any]:
    return {
        "source": "system",
        "activity_type": "system_stale",
        "score": 45,
        "tier": "watch",
        "process": proc,
        "detail": detail,
        "dedupe_key": f"stale:{proc}:{detail[:40]}",
    }
