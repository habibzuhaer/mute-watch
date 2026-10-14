"""Deployer clusters + trade journal — connect graph → tradable patterns."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pump_prep import graph_store as gs
from pump_prep.config import MCAP_CACHE, OUT_DIR
from pump_prep.labels import save_discovered

TRADE_FILE = gs.GRAPH_DIR / "trades.jsonl"
CLUSTER_FILE = OUT_DIR / "deployer_clusters.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _had_pump(row: dict[str, Any]) -> bool:
    chg = row.get("ath_chg")
    try:
        if chg is not None and float(chg) <= -50:
            return True
    except (TypeError, ValueError):
        pass
    try:
        ath, price = row.get("ath"), row.get("price")
        if ath and price and float(price) > 0 and float(ath) / float(price) >= 2:
            return True
    except (TypeError, ValueError):
        pass
    return bool(row.get("had_pump"))


def build_deployer_clusters() -> dict[str, Any]:
    """Group scanned tokens by deployer; flag repeat / pump deployers."""
    by_id: dict[str, dict[str, Any]] = {}
    if MCAP_CACHE.exists():
        try:
            for t in json.loads(MCAP_CACHE.read_text()).get("tokens") or []:
                if t.get("id"):
                    by_id[t["id"]] = t
        except Exception:
            pass

    latest: dict[str, dict[str, Any]] = {}
    for row in gs.read_jsonl(gs.TOKEN_FILE):
        tid = row.get("id")
        if not tid:
            continue
        src = by_id.get(tid) or {}
        merged = {**src, **{k: v for k, v in row.items() if v not in (None, "")}}
        merged["had_pump"] = _had_pump(merged)
        latest[tid] = merged

    by_dep: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in latest.values():
        dep = (t.get("deployer") or "").lower()
        if not dep.startswith("0x"):
            continue
        by_dep[dep].append(t)

    clusters = []
    promote: list[dict[str, Any]] = []
    for dep, toks in by_dep.items():
        pumps = [t for t in toks if t.get("had_pump")]
        matches = sum(int(t.get("match_count") or 0) for t in toks)
        cluster = {
            "deployer": dep,
            "token_count": len(toks),
            "pump_count": len(pumps),
            "match_flows": matches,
            "symbols": [t.get("symbol") for t in toks][:20],
            "entities": sorted(
                {
                    t.get("deployer_entity")
                    for t in toks
                    if t.get("deployer_entity")
                }
            ),
            "best_ath_chg": min(
                (float(t["ath_chg"]) for t in toks if t.get("ath_chg") is not None),
                default=None,
            ),
            "score_hint": min(100, 20 * len(toks) + 25 * len(pumps) + min(30, matches * 5)),
            "tokens": [
                {
                    "id": t.get("id"),
                    "symbol": t.get("symbol"),
                    "age_days": t.get("age_days"),
                    "ath": t.get("ath"),
                    "ath_date": t.get("ath_date"),
                    "ath_chg": t.get("ath_chg"),
                    "had_pump": t.get("had_pump"),
                    "match_count": t.get("match_count"),
                    "status": t.get("status"),
                }
                for t in sorted(toks, key=lambda x: -(x.get("match_count") or 0))[:12]
            ],
        }
        clusters.append(cluster)
        if len(toks) >= 2 or (len(pumps) >= 1 and matches >= 1):
            promote.append(
                {
                    "address": dep,
                    "entity": "RepeatDeployer",
                    "label": f"deployer×{len(toks)} pump×{len(pumps)}",
                    "role": "watch",
                    "source": "cluster_promote",
                    "priority": 2 if len(pumps) else 3,
                }
            )

    clusters.sort(key=lambda c: (-c["score_hint"], -c["token_count"], -c["pump_count"]))
    if promote:
        save_discovered(promote[:200])

    out = {
        "generated_at": _now(),
        "cluster_count": len(clusters),
        "repeat_deployers": sum(1 for c in clusters if c["token_count"] >= 2),
        "pump_deployers": sum(1 for c in clusters if c["pump_count"] >= 1),
        "promoted_labels": len(promote[:200]),
        "clusters": clusters[:80],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CLUSTER_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def add_trade(**fields: Any) -> dict[str, Any]:
    """Append a human decision to the trade journal."""
    row = {
        "action": fields.get("action") or "watch",
        "symbol": fields.get("symbol"),
        "token_id": fields.get("token_id"),
        "deployer": fields.get("deployer"),
        "score": fields.get("score"),
        "tier": fields.get("tier"),
        "signal_kind": fields.get("signal_kind"),
        "match_entity": fields.get("match_entity"),
        "note": fields.get("note") or "",
        "tx": fields.get("tx") or "",
        "when_signal": fields.get("when_signal"),
        "result": fields.get("result") or "",  # win/loss/skip/open
        "pnl_note": fields.get("pnl_note") or "",
    }
    gs.append_jsonl(TRADE_FILE, row)
    return row


def recent_trades(n: int = 50) -> list[dict[str, Any]]:
    return gs.read_jsonl_tail(TRADE_FILE, n)


def trade_stats() -> dict[str, Any]:
    rows = gs.read_jsonl(TRADE_FILE) if TRADE_FILE.exists() else []
    by_action: dict[str, int] = defaultdict(int)
    by_result: dict[str, int] = defaultdict(int)
    for r in rows:
        by_action[r.get("action") or "?"] += 1
        if r.get("result"):
            by_result[r.get("result") or "?"] += 1
    return {
        "total": len(rows),
        "by_action": dict(by_action),
        "by_result": dict(by_result),
        "recent": rows[-20:][::-1],
    }
