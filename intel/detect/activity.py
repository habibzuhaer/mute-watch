"""Activity spike + pre-pump detectors over intel edges."""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from intel.config import (
    ACTIVITY_WINDOW_SEC,
    GRAPH_DIR,
    PREPUMP_DAYS,
    SPIKE_MIN_TX,
    SPIKE_MIN_UNIQUE,
)
from intel.normalize import short
from intel.store import append_signal, iter_all_edges, upsert_address


def _parse_ath_ts(ath_date: Any) -> int | None:
    if ath_date is None:
        return None
    if isinstance(ath_date, (int, float)) and ath_date > 1_000_000:
        return int(ath_date)
    s = str(ath_date).strip()
    if not s:
        return None
    try:
        if s.isdigit():
            return int(s)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return int(datetime.fromisoformat(s).timestamp())
    except Exception:
        return None


def load_pump_tokens() -> dict[str, dict[str, Any]]:
    """Legacy graph tokens with ATH — used for EVM/BNB pre-pump. Solana ATH later."""
    path = GRAPH_DIR / "tokens.jsonl"
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            t = json.loads(line)
        except Exception:
            continue
        ath = _parse_ath_ts(t.get("ath_date"))
        pumped = bool(t.get("had_pump")) or (
            t.get("ath_chg") is not None and float(t.get("ath_chg") or 0) <= -50
        )
        if not pumped or not ath:
            continue
        tid = str(t.get("id") or t.get("symbol") or "")
        if tid:
            out[tid.lower()] = {**t, "_ath_ts": ath}
        sym = (t.get("symbol") or "").lower()
        if sym:
            out[sym] = {**t, "_ath_ts": ath}
        c = (t.get("contract") or "").lower()
        if c.startswith("0x"):
            out[c] = {**t, "_ath_ts": ath}
    return out


def detect_activity_spikes(*, now: int | None = None) -> list[dict[str, Any]]:
    """Tokens with elevated unique wallets / tx in recent window."""
    now = now or int(time.time())
    window = ACTIVITY_WINDOW_SEC
    by_token: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"tx": 0, "wallets": set(), "chain": "", "edges": []}
    )
    for e in iter_all_edges():
        ts = int(e.get("timestamp") or 0)
        if ts and ts < now - window:
            continue
        tok = (e.get("token") or e.get("symbol") or "").lower()
        if not tok or tok in {"usdt", "usdc", "bnb", "eth", "sol", "native", "wbnb", "weth"}:
            continue
        key = f"{e.get('chain')}:{tok}"
        st = by_token[key]
        st["tx"] += 1
        st["chain"] = e.get("chain")
        st["wallets"].add(e.get("from"))
        st["wallets"].add(e.get("to"))
        st["symbol"] = e.get("symbol") or tok

    spikes = []
    for key, st in by_token.items():
        uniq = len({w for w in st["wallets"] if w})
        if st["tx"] < SPIKE_MIN_TX and uniq < SPIKE_MIN_UNIQUE:
            continue
        score = min(100, st["tx"] * 3 + uniq * 5)
        row = {
            "type": "activity_spike",
            "key": key,
            "chain": st["chain"],
            "symbol": st.get("symbol"),
            "tx": st["tx"],
            "unique": uniq,
            "score": score,
            "window_sec": window,
        }
        spikes.append(row)
        append_signal(row)
    spikes.sort(key=lambda x: -x["score"])
    return spikes[:50]


def detect_prepump(*, pumps: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Addresses that touched pump tokens before ATH (legacy ATH map + intel edges)."""
    pumps = pumps if pumps is not None else load_pump_tokens()
    early_window = int(PREPUMP_DAYS * 86400)
    # addr_key -> tokens
    hits: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"tokens": set(), "n": 0, "chain": "", "address": ""}
    )

    for e in iter_all_edges():
        tok = (e.get("token") or "").lower()
        sym = (e.get("symbol") or "").lower()
        meta = pumps.get(tok) or pumps.get(sym)
        if not meta:
            continue
        ath = int(meta["_ath_ts"])
        ts = int(e.get("timestamp") or 0)
        if not ts or ts >= ath:
            continue
        if ath - ts > early_window * 3 and (ath - ts) > early_window:
            # still count if within 3x window for multi-pump ranking
            pass
        for side in (e.get("from"), e.get("to")):
            if not side:
                continue
            key = f"{e.get('chain')}:{side}"
            st = hits[key]
            st["tokens"].add(str(meta.get("id") or meta.get("symbol") or sym))
            st["n"] += 1
            st["chain"] = e.get("chain")
            st["address"] = side

    out = []
    for key, st in hits.items():
        toks = sorted(st["tokens"])
        if not toks:
            continue
        score = min(100, len(toks) * 18 + min(20, st["n"]))
        if score < 18:
            continue
        row = {
            "type": "prepump",
            "key": key,
            "chain": st["chain"],
            "address": st["address"],
            "short": short(st["address"]),
            "tokens": toks[:15],
            "token_n": len(toks),
            "touches": st["n"],
            "score": score,
        }
        out.append(row)
        append_signal(row)
        upsert_address(
            st["chain"] or "evm",
            st["address"],
            tags=["prepump", "early_beneficiary"] + (["multi_pump"] if len(toks) >= 2 else []),
            meta={"prepump_tokens": toks[:10], "prepump_score": score},
        )
    out.sort(key=lambda x: (-x["score"], -x["token_n"]))
    return out[:80]


def run_detectors() -> dict[str, Any]:
    spikes = detect_activity_spikes()
    prepump = detect_prepump()
    return {
        "spikes": spikes,
        "prepump": prepump,
        "spike_n": len(spikes),
        "prepump_n": len(prepump),
    }
