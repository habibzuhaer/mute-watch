"""Resumable continuous scanner: token → deployer → flows → persist graph.

Survives stop/restart via data/graph/state.json + jsonl append logs.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from typing import Any

import requests

from pump_prep.config import ETHERSCAN_API_KEY, EXPLORERS, MCAP_CACHE, OUT_DIR, REQUEST_DELAY_SEC
from pump_prep.deployer_trace import (
    PLATFORM_CHAIN,
    _contract_from_map,
    _get_creators,
    _load_known,
    _load_platform_map,
    write_deployer_html,
)
from pump_prep.etherscan import Pace, fetch_token_transfers
from pump_prep import graph_store as gs
from pump_prep.bridge_labels import bridge_name
from pump_prep.cex_labels import cex_name
from pump_prep.i18n_ui import DEFAULT_LANG, STORAGE_KEY, normalize_lang, packs_json, t
from pump_prep.obfuscation import (
    amounts_match,
    detect_same_amount_vs_edges,
    human_amount,
    is_fresh_wallet,
    wallet_age_days,
)
from pump_prep.signals import MIN_SCORE, score_match

logger = logging.getLogger(__name__)

_STOP = False

_TIER_KEY = {"actionable": "tier_act", "watch": "tier_watch", "noise": "tier_noise"}


def _had_pump(token: dict[str, Any]) -> bool:
    """Token had a significant peak if price is well below ATH."""
    chg = token.get("ath_chg")
    if chg is not None:
        try:
            return float(chg) <= -50.0
        except (TypeError, ValueError):
            pass
    ath = token.get("ath")
    price = token.get("price")
    try:
        if ath and price and float(price) > 0:
            return float(ath) / float(price) >= 2.0
    except (TypeError, ValueError):
        pass
    return False


def _emit_scored_match(
    *,
    token: dict[str, Any] | None,
    symbol: str | None,
    token_id: str,
    contract: str,
    chain_id: int,
    deployer: str,
    direction: str,
    counterparty: str,
    flow_symbol: str | None,
    is_token_itself: bool,
    tx_hash: str | None,
    timestamp: Any,
    match_entity: str | None,
    match_label: str | None,
    match_role: str | None,
    via: str = "deployer",
    amount_human: float | None = None,
    value_raw: Any = None,
    decimals: Any = None,
    same_amount: bool = False,
    same_amount_hint: str | None = None,
    fresh_wallet: bool = False,
    fresh_wallet_days: float | None = None,
    hop: int | None = None,
) -> dict[str, Any]:
    """Write match + scored signal with explicit reasons."""
    tok = token or {}
    if amount_human is None and value_raw is not None:
        amount_human = human_amount(value_raw, decimals if decimals is not None else 18)
    scored = score_match(
        match_role=match_role,
        match_entity=match_entity,
        direction=direction,
        is_token_itself=is_token_itself,
        age_days=tok.get("age_days"),
        ath_chg=tok.get("ath_chg"),
        ath=tok.get("ath"),
        price=tok.get("price"),
        timestamp=timestamp,
        via=via,
        hop=hop,
        same_amount=same_amount,
        same_amount_hint=same_amount_hint,
        fresh_wallet=fresh_wallet,
        fresh_wallet_days=fresh_wallet_days,
        amount_human=amount_human,
    )
    match_row = {
        "symbol": symbol,
        "token_id": token_id,
        "contract": contract,
        "chain_id": chain_id,
        "deployer": deployer,
        "direction": direction,
        "counterparty": counterparty,
        "flow_symbol": flow_symbol,
        "is_token_itself": is_token_itself,
        "hash": tx_hash,
        "timestamp": timestamp,
        "match_entity": match_entity,
        "match_label": match_label,
        "match_role": match_role,
        "via": via,
        "score": scored.score,
        "tier": scored.tier,
        "reasons": scored.reasons,
        "reasons_uk": scored.reasons_uk,
        "signal_kind": scored.kind,
        "summary": scored.summary,
        "summary_uk": scored.summary_uk,
        "age_days": tok.get("age_days"),
        "ath": tok.get("ath"),
        "ath_date": tok.get("ath_date"),
        "ath_chg": tok.get("ath_chg"),
        "price": tok.get("price"),
        "had_pump": _had_pump(tok) if tok else False,
        "amount_human": amount_human,
        "same_amount": same_amount,
        "fresh_wallet": fresh_wallet,
        "hop": hop,
    }
    gs.add_match(**match_row)
    gs.add_signal(
        source="graph",
        **match_row,
        telegram_worthy=scored.score >= MIN_SCORE,
        min_score_rule=MIN_SCORE,
    )
    if scored.score >= MIN_SCORE:
        try:
            from alerts.push import push_graph_signal

            push_graph_signal({**match_row, "source": "graph"})
        except Exception:
            pass
    return match_row


def _counterparty_meta(other: str, known: dict[str, dict]) -> tuple[str | None, str | None, str | None]:
    """entity, label, role for a counterparty (known / cex / bridge)."""
    kh = known.get(other)
    if kh:
        return kh.get("entity"), kh.get("label"), kh.get("role")
    cex = cex_name(other)
    if cex:
        return cex, f"{cex} hot", "cex"
    br = bridge_name(other)
    if br:
        return br, f"{br} bridge", "bridge"
    return None, None, None


def _handle_sig(*_args: Any) -> None:
    global _STOP
    _STOP = True
    logger.info("Stop requested — finishing current item then exit")


def _all_tokens() -> list[dict[str, Any]]:
    if not MCAP_CACHE.exists():
        logger.error("Missing token cache %s — run token table scrape first", MCAP_CACHE)
        return []
    data = __import__("json").loads(MCAP_CACHE.read_text())
    tokens = list(data.get("tokens") or [])
    tokens.sort(key=lambda t: (-(t.get("vol24h") or 0), t.get("id") or ""))
    return tokens


def _next_token(state: dict[str, Any], tokens: list[dict[str, Any]]) -> dict[str, Any] | None:
    done = set(state.get("done_tokens") or [])
    fails = state.get("failed_tokens") or {}
    for t in tokens:
        tid = t.get("id")
        if not tid or tid in done:
            continue
        # skip repeatedly failing (>3)
        if int(fails.get(tid) or 0) >= 3:
            continue
        return t
    return None


def _process_token(
    sess: requests.Session,
    pace_es: Pace,
    platforms: dict,
    known: dict[str, dict],
    token: dict[str, Any],
    state: dict[str, Any],
) -> bool:
    tid = token["id"]
    hit = _contract_from_map(platforms, tid)
    if not hit:
        gs.add_token_result(
            id=tid,
            symbol=token.get("symbol"),
            name=token.get("name"),
            mcap=token.get("mcap"),
            age_days=token.get("age_days"),
            listed_at=token.get("listed_at"),
            price=token.get("price"),
            ath=token.get("ath"),
            ath_date=token.get("ath_date"),
            ath_chg=token.get("ath_chg"),
            status="no_evm_contract",
            deployer="",
            flow_count=0,
            match_count=0,
            had_pump=_had_pump(token),
        )
        gs.mark_token_done(state, tid, ok=True)
        return True

    contract, chain_id, plat = hit
    creators = _get_creators(sess, pace_es, chain_id, [contract])
    info = creators.get(contract) or {}
    deployer = (info.get("creator") or "").lower()

    if not deployer:
        gs.add_token_result(
            id=tid,
            symbol=token.get("symbol"),
            name=token.get("name"),
            mcap=token.get("mcap"),
            age_days=token.get("age_days"),
            listed_at=token.get("listed_at"),
            price=token.get("price"),
            ath=token.get("ath"),
            ath_date=token.get("ath_date"),
            ath_chg=token.get("ath_chg"),
            contract=contract,
            chain_id=chain_id,
            platform=plat,
            status="no_deployer",
            deployer="",
            flow_count=0,
            match_count=0,
            had_pump=_had_pump(token),
        )
        gs.mark_token_done(state, tid, ok=True)
        return True

    dep_known = known.get(deployer)
    gs.upsert_address(
        deployer,
        role="deployer",
        symbol=token.get("symbol"),
        token_id=tid,
        entity=(dep_known or {}).get("entity") or "",
        label=(dep_known or {}).get("label") or f"deployer:{token.get('symbol')}",
    )

    txs = fetch_token_transfers(sess, deployer, chain_id, pace=pace_es, offset=80)
    match_count = 0
    flow_count = 0
    recent_edges: list[dict[str, Any]] = []

    for tx in txs:
        is_this = (tx.get("contract") or "") == contract
        is_out = tx.get("direction") == "out"
        if not (is_this or is_out):
            continue
        flow_count += 1
        counterparty = tx["to"] if tx["direction"] == "out" else tx["from"]
        amt = human_amount(tx.get("value_raw"), tx.get("decimals"))
        ts = tx.get("timestamp")

        edge = {
            "from_addr": tx["from"],
            "to_addr": tx["to"],
            "direction": tx["direction"],
            "symbol": tx.get("symbol"),
            "token_symbol": token.get("symbol"),
            "token_id": tid,
            "contract": tx.get("contract") or "",
            "is_token_itself": is_this,
            "chain_id": chain_id,
            "hash": tx.get("hash"),
            "timestamp": ts,
            "deployer": deployer,
            "value_raw": tx.get("value_raw"),
            "decimals": tx.get("decimals"),
            "amount_human": amt,
        }
        gs.add_edge(**edge)
        recent_edges.append(edge)
        gs.upsert_address(
            counterparty,
            role="counterparty",
            via_token=token.get("symbol"),
            token_id=tid,
        )

        ent, lab, role = _counterparty_meta(counterparty, known)
        if role:
            match_count += 1
            same = False
            hint = None
            found = detect_same_amount_vs_edges(
                amount=amt,
                counterparty=deployer,
                edges=recent_edges[:-1],
                now_ts=int(ts) if ts else None,
            )
            if found:
                same = True
                hint = f"≈{found.get('matched_amount')}"
            _emit_scored_match(
                token=token,
                symbol=token.get("symbol"),
                token_id=tid,
                contract=contract,
                chain_id=chain_id,
                deployer=deployer,
                direction=tx["direction"],
                counterparty=counterparty,
                flow_symbol=tx.get("symbol"),
                is_token_itself=is_this,
                tx_hash=tx.get("hash"),
                timestamp=ts,
                match_entity=ent,
                match_label=lab,
                match_role=role,
                via="deployer",
                amount_human=amt,
                value_raw=tx.get("value_raw"),
                decimals=tx.get("decimals"),
                same_amount=same,
                same_amount_hint=hint,
                hop=0,
            )
        else:
            # queue unknown counterparties that received the token itself
            if is_this and is_out and counterparty not in known:
                gs.enqueue_expand(state, counterparty, reason=f"early_holder:{tid}", hop=1)
    stats = state.setdefault("stats", {})
    stats["edges"] = int(stats.get("edges") or 0) + flow_count
    stats["matches"] = int(stats.get("matches") or 0) + match_count
    stats["addresses"] = int(stats.get("addresses") or 0) + 1 + flow_count

    gs.add_token_result(
        id=tid,
        symbol=token.get("symbol"),
        name=token.get("name"),
        mcap=token.get("mcap"),
        vol24h=token.get("vol24h"),
        age_days=token.get("age_days"),
        listed_at=token.get("listed_at"),
        price=token.get("price"),
        ath=token.get("ath"),
        ath_date=token.get("ath_date"),
        ath_chg=token.get("ath_chg"),
        contract=contract,
        chain_id=chain_id,
        platform=plat,
        deployer=deployer,
        deploy_tx=info.get("tx_hash") or "",
        deployer_entity=(dep_known or {}).get("entity") or "",
        flow_count=flow_count,
        match_count=match_count,
        status="ok",
        had_pump=_had_pump(token),
    )
    state["last_token"] = tid
    gs.mark_token_done(state, tid, ok=True)
    return True


def _process_expand(
    sess: requests.Session,
    pace_es: Pace,
    known: dict[str, dict],
    addr: str,
    state: dict[str, Any],
    *,
    via: str = "expand",
    hop: int = 1,
    seed_amount: float | None = None,
) -> None:
    """1/2-hop: pull recent token txs for discovered address, record edges/matches.

    From a *hit* (match to MM/CEX/bridge), enqueue unknown counterparties as expand2
    — that catches intermediate EOAs used to obfuscate prep flows.
    """
    recent_edges: list[dict[str, Any]] = []
    hit = False
    oldest_ts: int | None = None

    for chain_id in (1, 56, 42161, 8453):
        if _STOP:
            return
        txs = fetch_token_transfers(sess, addr, chain_id, pace=pace_es, offset=40)
        for tx in txs:
            other = tx["to"] if tx["direction"] == "out" else tx["from"]
            amt = human_amount(tx.get("value_raw"), tx.get("decimals"))
            ts = int(tx.get("timestamp") or 0)
            if ts and (oldest_ts is None or ts < oldest_ts):
                oldest_ts = ts
            edge = {
                "from_addr": tx["from"],
                "to_addr": tx["to"],
                "direction": tx["direction"],
                "symbol": tx.get("symbol"),
                "token_symbol": tx.get("symbol"),
                "token_id": "",
                "contract": tx.get("contract") or "",
                "is_token_itself": False,
                "chain_id": chain_id,
                "hash": tx.get("hash"),
                "timestamp": ts,
                "deployer": "",
                "expanded_from": addr,
                "value_raw": tx.get("value_raw"),
                "decimals": tx.get("decimals"),
                "amount_human": amt,
            }
            gs.add_edge(**edge)
            recent_edges.append(edge)

            ent, lab, role = _counterparty_meta(other, known)
            if not role:
                # 2-hop only from hits: queue unknown neighbor once we know this
                # expand address is interesting (handled after loop if hit)
                continue

            same = False
            hint = None
            if seed_amount is not None and amounts_match(seed_amount, amt):
                same = True
                hint = f"seed≈{seed_amount:g} / hop≈{amt:g}"
            else:
                found = detect_same_amount_vs_edges(
                    amount=amt,
                    counterparty=addr,
                    edges=recent_edges[:-1],
                    now_ts=ts or None,
                )
                if found:
                    same = True
                    hint = f"≈{found.get('matched_amount')}"

            fw = is_fresh_wallet(oldest_ts) if hop >= 1 else False
            fwd = wallet_age_days(oldest_ts) if fw else None

            _emit_scored_match(
                token=None,
                symbol=tx.get("symbol"),
                token_id="",
                contract=tx.get("contract") or "",
                chain_id=chain_id,
                deployer=addr,
                direction=tx["direction"],
                counterparty=other,
                flow_symbol=tx.get("symbol"),
                is_token_itself=False,
                tx_hash=tx.get("hash"),
                timestamp=ts,
                match_entity=ent,
                match_label=lab,
                match_role=role,
                via=via,
                amount_human=amt,
                value_raw=tx.get("value_raw"),
                decimals=tx.get("decimals"),
                same_amount=same,
                same_amount_hint=hint,
                fresh_wallet=fw,
                fresh_wallet_days=fwd,
                hop=hop,
            )
            hit = True
            # From a hit: enqueue unknown counterparties → 2-hop (obfuscation path)
            if hop < 2:
                queued: set[str] = set()
                for e2 in recent_edges[-15:]:
                    for side in (e2.get("from_addr"), e2.get("to_addr")):
                        if not side:
                            continue
                        s = side.lower()
                        if s == addr.lower() or s in known or s in queued:
                            continue
                        if cex_name(s) or bridge_name(s):
                            continue
                        queued.add(s)
                        gs.enqueue_expand(
                            state,
                            s,
                            reason=f"hop2_from_hit:{addr[:10]}",
                            hop=2,
                        )

    # Also mark expand address itself if it looks fresh and we got a hit
    if hit and hop < 2 and oldest_ts and is_fresh_wallet(oldest_ts):
        state.setdefault("fresh_expand", [])
        fl = list(state.get("fresh_expand") or [])
        if addr.lower() not in fl:
            fl.append(addr.lower())
            state["fresh_expand"] = fl[-200:]


def write_graph_html() -> str:
    """Render accumulated graph to HTML report."""
    import html as html_mod
    import json
    from datetime import datetime, timezone

    summary = gs.aggregate_summary()
    state = summary["state"]
    matches = summary["recent_matches"]
    tokens = summary["recent_tokens"]
    edges = summary["recent_edges"]
    entity_hits = summary["entity_hits"]

    # Enrich older token rows from mcap cache (price / ATH / age)
    by_id: dict[str, dict[str, Any]] = {}
    if MCAP_CACHE.exists():
        try:
            for row in json.loads(MCAP_CACHE.read_text()).get("tokens") or []:
                if row.get("id"):
                    by_id[row["id"]] = row
        except Exception:
            pass

    lang = normalize_lang(DEFAULT_LANG)

    def esc(x: Any) -> str:
        return html_mod.escape("" if x is None else str(x))

    def T(key: str, **fmt: Any) -> str:
        return esc(t(lang, key, **fmt))

    def TIP(key: str, **fmt: Any) -> str:
        return esc(t(lang, key, **fmt)).replace("\n", "&#10;")

    def short(a: str) -> str:
        if not a or len(a) < 12:
            return a or "—"
        return f"{a[:6]}…{a[-4:]}"

    def ts_chain(t: Any) -> str:
        """On-chain event time (UTC)."""
        if not t:
            return "—"
        try:
            return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            return str(t)

    def ts_iso(s: Any) -> str:
        if not s:
            return "—"
        try:
            raw = str(s).replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            return str(s)[:19]

    def age_label(days: Any) -> str:
        if days is None or days == "":
            return "—"
        try:
            d = int(float(days))
        except (TypeError, ValueError):
            return str(days)
        if d < 30:
            return f"{d}d"
        if d < 365:
            return f"{d // 30}m ({d}d)"
        return f"{d / 365:.1f}y ({d}d)"

    def money(v: Any) -> str:
        if v is None or v == "":
            return "—"
        try:
            x = float(v)
        except (TypeError, ValueError):
            return str(v)
        if x == 0:
            return "0"
        if x >= 1:
            return f"${x:,.4g}"
        if x >= 1e-4:
            return f"${x:.6f}"
        return f"${x:.4e}"

    def merge_token(t: dict[str, Any]) -> dict[str, Any]:
        src = by_id.get(t.get("id") or "") or {}
        out = {**src, **{k: v for k, v in t.items() if v not in (None, "")}}
        if "had_pump" not in out or out.get("had_pump") is None:
            out["had_pump"] = _had_pump(out)
        return out

    # Score unmatched legacy rows for display + optional signal journal backfill
    progress = summary.get("progress") or gs.progress_snapshot()
    signals = list(summary.get("recent_signals") or [])

    def enrich_match(m: dict[str, Any]) -> dict[str, Any]:
        if m.get("score") is not None and m.get("reasons"):
            return m
        tok = by_id.get(m.get("token_id") or "") or {}
        scored = score_match(
            match_role=m.get("match_role"),
            match_entity=m.get("match_entity"),
            direction=m.get("direction"),
            is_token_itself=bool(m.get("is_token_itself")),
            age_days=m.get("age_days") if m.get("age_days") is not None else tok.get("age_days"),
            ath_chg=m.get("ath_chg") if m.get("ath_chg") is not None else tok.get("ath_chg"),
            ath=m.get("ath") if m.get("ath") is not None else tok.get("ath"),
            price=m.get("price") if m.get("price") is not None else tok.get("price"),
            timestamp=m.get("timestamp"),
            via=m.get("via"),
            hop=m.get("hop"),
            same_amount=bool(m.get("same_amount")),
            fresh_wallet=bool(m.get("fresh_wallet")),
            amount_human=m.get("amount_human"),
        )
        return {
            **m,
            "score": scored.score,
            "tier": scored.tier,
            "reasons": scored.reasons,
            "reasons_uk": scored.reasons_uk,
            "signal_kind": scored.kind,
            "summary": scored.summary,
            "summary_uk": scored.summary_uk,
            "age_days": m.get("age_days") if m.get("age_days") is not None else tok.get("age_days"),
            "ath": m.get("ath") if m.get("ath") is not None else tok.get("ath"),
            "ath_date": m.get("ath_date") or tok.get("ath_date"),
            "ath_chg": m.get("ath_chg") if m.get("ath_chg") is not None else tok.get("ath_chg"),
            "price": m.get("price") if m.get("price") is not None else tok.get("price"),
        }

    scored_matches = [enrich_match(m) for m in matches]
    if not signals:
        # Build display signals from scored matches (legacy graph without signals.jsonl)
        signals = sorted(
            scored_matches,
            key=lambda x: (-(x.get("score") or 0), x.get("saved_at") or ""),
        )[:80]

    def tier_badge(tier: str, score: Any) -> str:
        tier_ = tier or "noise"
        cls = {"actionable": "tier-go", "watch": "tier-watch", "noise": "tier-noise"}.get(tier_, "tier-noise")
        key = _TIER_KEY.get(tier_, "tier_noise")
        return f"<span class='tier {cls}'><span data-i18n='{key}'>{T(key)}</span> · {esc(score)}/100</span>"

    def reasons_cell(reasons_en: Any, reasons_uk: Any) -> str:
        items_en = list(reasons_en or [])[:8]
        items_uk = list(reasons_uk or [])[:8]
        show = items_uk if (lang == "uk" and items_uk) else items_en
        html_items = "".join(f"<li>{esc(r)}</li>" for r in show) or "<li>—</li>"
        data_en = esc(json.dumps(items_en, ensure_ascii=False))
        data_uk = esc(json.dumps(items_uk, ensure_ascii=False))
        return (
            f"<td data-reasons=\"{data_en}\" data-reasons-uk=\"{data_uk}\">"
            f"<ul class='reasons'>{html_items}</ul></td>"
        )

    sig_rows = []
    for s in sorted(signals, key=lambda x: (-(x.get("score") or 0), x.get("saved_at") or ""))[:40]:
        if s.get("score") is None:
            s = enrich_match(s)
        when_onchain = ts_chain(s.get("timestamp"))
        had = False
        try:
            chg = s.get("ath_chg")
            if chg is not None and float(chg) <= -50:
                had = True
            elif s.get("ath") and s.get("price") and float(s["price"]) > 0:
                had = float(s["ath"]) / float(s["price"]) >= 2.0
        except (TypeError, ValueError, KeyError):
            had = False
        pump_bit = ""
        if had:
            pump_bit = (
                f"<div class='sub pump-inline'>"
                f"{esc(t(lang, 'graph_pump_inline', ath=money(s.get('ath')), date=ts_iso(s.get('ath_date')), chg=s.get('ath_chg')))}"
                f"</div>"
            )
        sig_rows.append(
            f"<tr class='tier-{esc(s.get('tier') or 'noise')}'>"
            f"<td>{tier_badge(s.get('tier') or '', s.get('score'))}</td>"
            f"<td><b>{esc(s.get('symbol'))}</b>{pump_bit}"
            f"<div class='sub'>{esc(s.get('signal_kind') or s.get('kind') or '')}</div></td>"
            f"<td><span class='dir'>{esc(s.get('direction'))}</span> → "
            f"<span class='pill'>{esc(s.get('match_entity'))}</span></td>"
            f"<td class='num'>{esc(age_label(s.get('age_days')))}</td>"
            f"<td class='when'><b data-i18n='graph_onchain'>{T('graph_onchain')}</b> {esc(when_onchain)}"
            f"<div class='sub'><b data-i18n='graph_saved'>{T('graph_saved')}</b> {esc(ts_iso(s.get('saved_at')))}</div></td>"
            f"{reasons_cell(s.get('reasons'), s.get('reasons_uk'))}"
            f"</tr>"
        )

    tok_rows = []
    for raw_tok in reversed(tokens):
        tok = merge_token(raw_tok)
        pump = bool(tok.get("had_pump"))
        pump_cell = (
            f"<span class='pump' data-i18n='graph_pump_ath'>{T('graph_pump_ath')}</span>"
            if pump
            else "<span class='muted'>—</span>"
        )
        cls = []
        if tok.get("match_count"):
            cls.append("hit")
        if pump:
            cls.append("pump-row")
        tok_rows.append(
            f"<tr class='{' '.join(cls)}'>"
            f"<td><b>{esc(tok.get('symbol'))}</b><div class='sub'>{esc(tok.get('name') or '')}</div></td>"
            f"<td>{pump_cell}</td>"
            f"<td class='num'>{esc(age_label(tok.get('age_days')))}"
            f"<div class='sub'>listed {esc(tok.get('listed_at') or '—')}</div></td>"
            f"<td class='num'>{esc(money(tok.get('price')))}</td>"
            f"<td class='num ath'>{esc(money(tok.get('ath')))}"
            f"<div class='sub' data-i18n='graph_max_price'>{T('graph_max_price')}</div></td>"
            f"<td class='when'>{esc(ts_iso(tok.get('ath_date')))}"
            f"<div class='sub' data-i18n='graph_when_max_price'>{T('graph_when_max_price')}</div></td>"
            f"<td class='num'>{esc(tok.get('ath_chg') if tok.get('ath_chg') is not None else '—')}"
            f"{'%' if tok.get('ath_chg') is not None else ''}</td>"
            f"<td>{esc(tok.get('status'))}</td>"
            f"<td title='{esc(tok.get('deployer'))}'>{esc(short(tok.get('deployer') or ''))}</td>"
            f"<td class='num'>{tok.get('flow_count') or 0}</td>"
            f"<td class='num'>{tok.get('match_count') or 0}</td>"
            f"<td class='when'>{esc(ts_iso(tok.get('saved_at')))}"
            f"<div class='sub' data-i18n='graph_when_scanned'>{T('graph_when_scanned')}</div></td>"
            f"</tr>"
        )

    match_rows = []
    for m in reversed(scored_matches):
        when_onchain = ts_chain(m.get("timestamp"))
        when_saved = ts_iso(m.get("saved_at"))
        match_rows.append(
            f"<tr class='role-{esc(m.get('match_role') or '')} tier-{esc(m.get('tier') or '')}'>"
            f"<td>{tier_badge(m.get('tier') or '', m.get('score'))}</td>"
            f"<td><b>{esc(m.get('symbol'))}</b></td>"
            f"<td>{esc(short(m.get('deployer') or ''))}</td>"
            f"<td><span class='dir'>{esc(m.get('direction'))}</span></td>"
            f"<td title='{esc(m.get('counterparty'))}'>{esc(short(m.get('counterparty') or ''))}</td>"
            f"<td><span class='pill'>{esc(m.get('match_entity'))}</span>"
            f"<div class='sub'>{esc(m.get('match_label') or '')}</div></td>"
            f"<td class='when'><b data-i18n='graph_onchain'>{T('graph_onchain')}</b> {esc(when_onchain)}"
            f"<div class='sub'><b data-i18n='graph_saved'>{T('graph_saved')}</b> {esc(when_saved)}</div></td>"
            f"{reasons_cell(m.get('reasons'), m.get('reasons_uk'))}"
            f"</tr>"
        )

    edge_rows = []
    for e in reversed(edges[-120:]):
        when_onchain = ts_chain(e.get("timestamp"))
        when_saved = ts_iso(e.get("saved_at"))
        edge_rows.append(
            f"<tr>"
            f"<td>{esc(e.get('token_symbol') or e.get('symbol'))}</td>"
            f"<td title='{esc(e.get('from_addr'))}'>{esc(short(e.get('from_addr') or ''))}</td>"
            f"<td title='{esc(e.get('to_addr'))}'>{esc(short(e.get('to_addr') or ''))}</td>"
            f"<td><span class='dir'>{esc(e.get('direction'))}</span></td>"
            f"<td class='when'><b data-i18n='graph_link_happened'>{T('graph_link_happened')}</b> {esc(when_onchain)}"
            f"<div class='sub'><b data-i18n='graph_detected'>{T('graph_detected')}</b> {esc(when_saved)}</div></td>"
            f"</tr>"
        )

    ents = "".join(f"<span class='ent'>{esc(k)} · {v}</span>" for k, v in list(entity_hits.items())[:20])
    pump_n = sum(1 for raw_tok in tokens if merge_token(raw_tok).get("had_pump"))
    pct = progress.get("pct") or 0
    done_n = progress.get("done") or 0
    total_n = progress.get("total") or 0
    rem_n = progress.get("remaining") or 0
    tier_counts = progress.get("signals_by_tier") or {}
    bar_w = max(0, min(100, float(pct)))
    en_active = " active" if lang == "en" else ""
    uk_active = " active" if lang == "uk" else ""
    i18n_json = packs_json().replace("</", "<\\/")

    doc = f"""<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta http-equiv="refresh" content="120"/>
<title data-i18n="graph_title">{T('graph_title')}</title>
<style>
:root {{ --bg:#0f1115; --panel:#171a21; --text:#e8eaed; --muted:#9aa0a6; --line:#2a2f3a; --accent:#7cb3ff; --ok:#3dd68c; --danger:#f07178; --warn:#e6c07b; }}
body {{ margin:0; font:14px/1.45 ui-sans-serif,system-ui,sans-serif; background:var(--bg); color:var(--text); }}
header {{ padding:18px 24px; border-bottom:1px solid var(--line); position:sticky; top:0; background:rgba(15,17,21,.96); z-index:2; }}
.header-top {{ display:flex; flex-wrap:wrap; gap:10px 16px; align-items:flex-start; justify-content:space-between; }}
.header-copy {{ min-width:0; flex:1; }}
h1 {{ margin:0 0 6px; font-size:20px; }} h2 {{ margin:22px 0 8px; font-size:15px; }}
.meta,.stats {{ color:var(--muted); font-size:12px; }}
.stats {{ display:flex; gap:14px; flex-wrap:wrap; margin-top:8px; }}
.ents {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
.ent {{ border:1px solid var(--line); border-radius:999px; padding:3px 10px; background:var(--panel); font-size:11px; }}
.wrap {{ padding:12px 16px 40px; overflow:auto; }}
table {{ width:100%; border-collapse:collapse; min-width:1100px; }}
th,td {{ padding:7px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
th {{ background:#1b2030; color:var(--muted); font-size:11px; text-transform:uppercase; position:sticky; top:0; }}
td.num {{ text-align:right; font-family:ui-monospace,Menlo,monospace; white-space:nowrap; }}
td.when {{ font-size:12px; white-space:nowrap; }}
td.ath {{ color:var(--warn); font-weight:650; }}
tr.hit td {{ background:rgba(61,214,140,.08); }}
tr.pump-row td {{ background:rgba(230,192,123,.07); }}
tr.tier-actionable td {{ background:rgba(61,214,140,.10); }}
tr.tier-watch td {{ background:rgba(230,192,123,.06); }}
.pill {{ background:#374151; color:#fff; border-radius:999px; padding:2px 8px; font-size:11px; font-weight:650; }}
.pump {{ background:#7c4a1a; color:#ffe8c2; border-radius:6px; padding:2px 8px; font-size:11px; font-weight:700; }}
.pump-inline {{ color:var(--warn); }}
.dir {{ font-family:ui-monospace,Menlo,monospace; color:var(--accent); }}
.sub {{ color:var(--muted); font-size:11px; font-weight:400; margin-top:2px; }}
.muted {{ color:var(--muted); }}
.tip {{ color:var(--muted); font-size:12px; max-width:980px; }}
.bar {{ height:12px; background:#222833; border-radius:6px; overflow:hidden; margin:10px 0 4px; max-width:640px; }}
.bar > i {{ display:block; height:100%; background:var(--ok); width:{bar_w}%; }}
.tier {{ display:inline-block; border-radius:6px; padding:2px 8px; font-size:11px; font-weight:700; white-space:nowrap; }}
.tier-go {{ background:rgba(61,214,140,.2); color:var(--ok); }}
.tier-watch {{ background:rgba(230,192,123,.18); color:var(--warn); }}
.tier-noise {{ background:#2a2f3a; color:var(--muted); }}
ul.reasons {{ margin:0; padding-left:16px; font-size:12px; color:var(--muted); }}
ul.reasons li {{ margin:1px 0; }}
.legend {{ font-size:12px; color:var(--muted); margin:8px 0 0; max-width:900px; }}
.legend b {{ color:var(--text); }}
.row {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
.lang-toggle {{ flex:0 0 auto; }}
.lang-btn {{ appearance:none; border:1px solid var(--line); background:#1b2030; color:var(--text); border-radius:6px; padding:6px 10px; font:inherit; font-size:12px; font-weight:700; cursor:pointer; }}
.lang-btn:hover {{ border-color:var(--accent); }}
.lang-btn.active {{ background:#243044; border-color:#3a5080; color:#cfe0ff; }}
</style></head><body>
<header>
  <div class="header-top">
    <div class="header-copy">
      <h1 data-i18n="graph_h1">{T('graph_h1')}</h1>
      <p class="tip" data-i18n="graph_tip">{T('graph_tip', min=MIN_SCORE)}</p>
    </div>
    <div class="row lang-toggle" role="group" aria-label="Language">
      <button type="button" class="lang-btn{en_active}" data-lang="en" data-i18n="lang_en">{T('lang_en')}</button>
      <button type="button" class="lang-btn{uk_active}" data-lang="uk" data-i18n="lang_uk">{T('lang_uk')}</button>
    </div>
  </div>
  <div class="bar" title="{esc(pct)}%"><i></i></div>
  <div class="stats">
    <span><b>{esc(pct)}%</b> · {esc(done_n)} / {esc(total_n)} <span data-i18n="graph_word_tokens">{T('graph_word_tokens')}</span></span>
    <span><span data-i18n="graph_word_remaining">{T('graph_word_remaining')}</span>: {esc(rem_n)}</span>
    <span>last: {esc(progress.get('last_token') or state.get('last_token'))}</span>
    <span>edges≈ {esc((state.get('stats') or {{}}).get('edges'))}</span>
    <span>matches≈ {esc((state.get('stats') or {{}}).get('matches'))}</span>
    <span><span data-i18n="graph_word_signals">{T('graph_word_signals')}</span>:
      <span data-i18n="tier_act">{T('tier_act')}</span> {esc(tier_counts.get('actionable', 0))} ·
      <span data-i18n="tier_watch">{T('tier_watch')}</span> {esc(tier_counts.get('watch', 0))} ·
      <span data-i18n="tier_noise">{T('tier_noise')}</span> {esc(tier_counts.get('noise', 0))}</span>
    <span><span data-i18n="graph_stat_pump_label">{T('graph_stat_pump_label')}</span>: {pump_n}</span>
    <span>expand q: {esc(state.get('expand_queue'))}</span>
    <span>updated: {esc(state.get('updated_at'))}</span>
  </div>
  <p class="legend">
    <b data-i18n="tier_act">{T('tier_act')}</b> ≥{MIN_SCORE} ·
    <b data-i18n="tier_watch">{T('tier_watch')}</b> ≥35 ·
    <span data-i18n="graph_legend_rest">{T('graph_legend_rest')}</span>
  </p>
  <div class="ents">{ents or f'<span class="ent" data-i18n="graph_no_matches">{T("graph_no_matches")}</span>'}</div>
</header>
<div class="wrap">
  <h2 data-i18n="graph_h2_signals">{T('graph_h2_signals')}</h2>
  <table><thead><tr>
    <th data-i18n="graph_col_tier">{T('graph_col_tier')}</th>
    <th data-i18n="graph_col_token">{T('graph_col_token')}</th>
    <th data-i18n="graph_col_link">{T('graph_col_link')}</th>
    <th data-i18n="graph_col_age">{T('graph_col_age')}</th>
    <th data-i18n="graph_col_when">{T('graph_col_when')}</th>
    <th data-i18n="graph_col_why">{T('graph_col_why')}</th>
  </tr></thead>
  <tbody>{''.join(sig_rows) or f'<tr><td colspan="6" data-i18n="graph_empty_signals">{T("graph_empty_signals")}</td></tr>'}</tbody></table>

  <h2 data-i18n="graph_h2_tokens">{T('graph_h2_tokens')}</h2>
  <table><thead><tr>
    <th data-i18n="graph_col_token">{T('graph_col_token')}</th>
    <th data-i18n="graph_col_pump">{T('graph_col_pump')}</th>
    <th data-i18n="graph_col_age">{T('graph_col_age')}</th>
    <th data-i18n="graph_col_price_now">{T('graph_col_price_now')}</th>
    <th data-i18n="graph_col_ath_max">{T('graph_col_ath_max')}</th>
    <th data-i18n="graph_col_when_ath">{T('graph_col_when_ath')}</th>
    <th data-i18n="graph_col_vs_ath">{T('graph_col_vs_ath')}</th>
    <th data-i18n="graph_col_status">{T('graph_col_status')}</th>
    <th data-i18n="graph_col_deployer">{T('graph_col_deployer')}</th>
    <th data-i18n="graph_col_flows">{T('graph_col_flows')}</th>
    <th data-i18n="graph_col_matches">{T('graph_col_matches')}</th>
    <th data-i18n="graph_col_scanned">{T('graph_col_scanned')}</th>
  </tr></thead>
  <tbody>{''.join(tok_rows) or f'<tr><td colspan="12" data-i18n="graph_empty_tokens">{T("graph_empty_tokens")}</td></tr>'}</tbody></table>

  <h2 data-i18n="graph_h2_matches">{T('graph_h2_matches')}</h2>
  <table><thead><tr>
    <th data-i18n="graph_col_score">{T('graph_col_score')}</th>
    <th data-i18n="graph_col_token">{T('graph_col_token')}</th>
    <th data-i18n="graph_col_from">{T('graph_col_from')}</th>
    <th data-i18n="graph_col_dir">{T('graph_col_dir')}</th>
    <th data-i18n="graph_col_counterparty">{T('graph_col_counterparty')}</th>
    <th data-i18n="graph_col_match">{T('graph_col_match')}</th>
    <th data-i18n="graph_col_when">{T('graph_col_when')}</th>
    <th data-i18n="graph_col_why_short">{T('graph_col_why_short')}</th>
  </tr></thead>
  <tbody>{''.join(match_rows) or '<tr><td colspan="8">—</td></tr>'}</tbody></table>

  <h2 data-i18n="graph_h2_edges">{T('graph_h2_edges')}</h2>
  <table><thead><tr>
    <th data-i18n="graph_col_token">{T('graph_col_token')}</th>
    <th data-i18n="graph_col_from">{T('graph_col_from')}</th>
    <th data-i18n="graph_col_to">{T('graph_col_to')}</th>
    <th data-i18n="graph_col_dir">{T('graph_col_dir')}</th>
    <th data-i18n="graph_col_when">{T('graph_col_when')}</th>
  </tr></thead>
  <tbody>{''.join(edge_rows) or '<tr><td colspan="5">—</td></tr>'}</tbody></table>
</div>
<script>
const I18N = {i18n_json};
const LANG_KEY = '{STORAGE_KEY}';
const DEFAULT_LANG = '{lang}';
const MIN_SCORE = {MIN_SCORE};
let currentLang = DEFAULT_LANG;

function normalizeLang(v) {{
  v = (v || '').toLowerCase().trim();
  if (['ua', 'ukr', 'украинский', 'українська'].includes(v)) return 'uk';
  if (I18N[v]) return v;
  return DEFAULT_LANG;
}}
function tr(key, fmt) {{
  const pack = I18N[currentLang] || I18N[DEFAULT_LANG] || {{}};
  let s = pack[key] || (I18N[DEFAULT_LANG] && I18N[DEFAULT_LANG][key]) || key;
  if (fmt) {{
    s = s.replace(/\\{{(\\w+)\\}}/g, (m, k) => (fmt[k] !== undefined ? fmt[k] : m));
  }}
  return s;
}}
function escapeHtml(s) {{
  return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}
function applyRowReasons() {{
  document.querySelectorAll('td[data-reasons]').forEach(td => {{
    let en = [], uk = [];
    try {{ en = JSON.parse(td.dataset.reasons || '[]'); }} catch (e) {{}}
    try {{ uk = JSON.parse(td.dataset.reasonsUk || '[]'); }} catch (e) {{}}
    const list = (currentLang === 'uk' && uk.length) ? uk : en;
    const ul = td.querySelector('ul');
    if (!ul) return;
    ul.innerHTML = list.length ? list.map(r => '<li>' + escapeHtml(r) + '</li>').join('') : '<li>\\u2014</li>';
  }});
}}
function applyLang(lang) {{
  lang = normalizeLang(lang);
  currentLang = lang;
  try {{ localStorage.setItem(LANG_KEY, lang); }} catch (e) {{}}
  document.documentElement.lang = lang;
  const FMT = {{ min: MIN_SCORE }};
  document.querySelectorAll('[data-i18n]').forEach(el => {{ el.textContent = tr(el.dataset.i18n, FMT); }});
  document.querySelectorAll('.lang-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.lang === lang));
  document.title = tr('graph_title', FMT);
  applyRowReasons();
}}
let savedLang = null;
try {{ savedLang = localStorage.getItem(LANG_KEY); }} catch (e) {{}}
applyLang(savedLang || DEFAULT_LANG);
document.querySelectorAll('.lang-btn').forEach(btn => {{
  btn.addEventListener('click', () => applyLang(btn.dataset.lang));
}});
</script>
</body></html>
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "graph_live.html"
    path.write_text(doc, encoding="utf-8")
    return str(path)


def backfill_signals(*, limit: int = 2000) -> int:
    """Re-score recent matches into signals.jsonl (idempotent-ish append)."""
    import json

    by_id: dict[str, dict[str, Any]] = {}
    if MCAP_CACHE.exists():
        try:
            for row in json.loads(MCAP_CACHE.read_text()).get("tokens") or []:
                if row.get("id"):
                    by_id[row["id"]] = row
        except Exception:
            pass
    matches = gs.read_jsonl_tail(gs.MATCH_FILE, limit)
    n = 0
    for m in matches:
        if m.get("score") is not None and m.get("tier"):
            # already scored on write — still ensure signal journal has a row
            pass
        tok = by_id.get(m.get("token_id") or "") or {}
        scored = score_match(
            match_role=m.get("match_role"),
            match_entity=m.get("match_entity"),
            direction=m.get("direction"),
            is_token_itself=bool(m.get("is_token_itself")),
            age_days=m.get("age_days") if m.get("age_days") is not None else tok.get("age_days"),
            ath_chg=m.get("ath_chg") if m.get("ath_chg") is not None else tok.get("ath_chg"),
            ath=m.get("ath") if m.get("ath") is not None else tok.get("ath"),
            price=m.get("price") if m.get("price") is not None else tok.get("price"),
            timestamp=m.get("timestamp"),
            via=m.get("via"),
            hop=m.get("hop"),
            same_amount=bool(m.get("same_amount")),
            fresh_wallet=bool(m.get("fresh_wallet")),
            amount_human=m.get("amount_human"),
        )
        gs.add_signal(
            source="backfill",
            symbol=m.get("symbol"),
            token_id=m.get("token_id"),
            contract=m.get("contract"),
            chain_id=m.get("chain_id"),
            deployer=m.get("deployer"),
            direction=m.get("direction"),
            counterparty=m.get("counterparty"),
            hash=m.get("hash"),
            timestamp=m.get("timestamp"),
            match_entity=m.get("match_entity"),
            match_label=m.get("match_label"),
            match_role=m.get("match_role"),
            via=m.get("via"),
            score=scored.score,
            tier=scored.tier,
            reasons=scored.reasons,
            reasons_uk=scored.reasons_uk,
            signal_kind=scored.kind,
            summary=scored.summary,
            summary_uk=scored.summary_uk,
            age_days=tok.get("age_days"),
            ath=tok.get("ath"),
            ath_date=tok.get("ath_date"),
            ath_chg=tok.get("ath_chg"),
            price=tok.get("price"),
            telegram_worthy=scored.score >= MIN_SCORE,
            min_score_rule=MIN_SCORE,
        )
        n += 1
    return n


def rewrite_signals_i18n(*, limit: int = 5000) -> int:
    """Rewrite signals.jsonl with bilingual EN/UK reasons (atomic replace)."""
    import json
    from pathlib import Path

    from pump_prep.signals import score_prep_event

    path: Path = gs.SIGNAL_FILE
    if not path.exists():
        return 0
    rows = gs.read_jsonl_tail(path, limit)
    # keep chronological order (tail returns newest last typically — check)
    # read_jsonl_tail usually returns last N lines in file order
    out: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        source = (row.get("source") or "").lower()
        prep = row.get("prep_type")
        if prep or source in ("prep", "live", "mute") or row.get("signal_kind") in (
            "cex_deposit",
            "new_token_in",
            "prep_live",
        ):
            # live prep-style
            ev = {
                "prep_type": prep or ("cex_deposit" if row.get("signal_kind") == "cex_deposit" else "new_token_in"),
                "symbol": row.get("symbol") or "?",
                "cex": row.get("cex") or row.get("match_entity"),
                "wallet_label": row.get("wallet_label") or row.get("match_label") or row.get("match_entity") or "",
                "timestamp": row.get("timestamp"),
            }
            scored = score_prep_event(ev)
        else:
            scored = score_match(
                match_role=row.get("match_role"),
                match_entity=row.get("match_entity"),
                direction=row.get("direction"),
                is_token_itself=bool(row.get("is_token_itself")),
                age_days=row.get("age_days"),
                ath_chg=row.get("ath_chg"),
                ath=row.get("ath"),
                price=row.get("price"),
                timestamp=row.get("timestamp"),
                via=row.get("via"),
                hop=row.get("hop"),
                same_amount=bool(row.get("same_amount")),
                fresh_wallet=bool(row.get("fresh_wallet")),
                amount_human=row.get("amount_human"),
            )
        row["score"] = scored.score
        row["tier"] = scored.tier
        row["reasons"] = scored.reasons
        row["reasons_uk"] = scored.reasons_uk
        row["signal_kind"] = scored.kind or row.get("signal_kind")
        row["summary"] = scored.summary
        row["summary_uk"] = scored.summary_uk
        out.append(row)

    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return len(out)


def _enqueue_cluster_expands(state: dict[str, Any], *, limit: int = 40) -> int:
    """After first pass: expand top repeat/pump deployers from clusters."""
    try:
        from pump_prep.clusters import build_deployer_clusters

        data = build_deployer_clusters()
    except Exception:
        logger.exception("cluster build failed")
        return 0
    n = 0
    for c in data.get("clusters") or []:
        if n >= limit:
            break
        if int(c.get("token_count") or 0) < 2 and int(c.get("pump_count") or 0) < 1:
            continue
        dep = c.get("deployer") or ""
        if not dep.startswith("0x"):
            continue
        before = len(state.get("expand_queue") or [])
        gs.enqueue_expand(state, dep, reason="cluster_pass2")
        if len(state.get("expand_queue") or []) > before:
            n += 1
    return n


def _requeue_priority_tokens(state: dict[str, Any], tokens: list[dict[str, Any]], *, limit: int = 25) -> int:
    """Re-scan young / high-vol tokens for fresh flows (pass 2)."""
    done = set(state.get("done_tokens") or [])
    # pick young tokens already done
    cands = []
    for t in tokens:
        tid = t.get("id")
        if not tid or tid not in done:
            continue
        age = t.get("age_days")
        try:
            age_i = int(float(age)) if age is not None else 9999
        except (TypeError, ValueError):
            age_i = 9999
        vol = t.get("vol24h") or 0
        if age_i <= 90 or vol >= 5_000_000:
            cands.append((age_i, -(vol or 0), tid))
    cands.sort()
    # track pass2 in state to avoid infinite loop
    pass2 = set(state.get("pass2_tokens") or [])
    n = 0
    for _, __, tid in cands:
        if tid in pass2:
            continue
        done.discard(tid)
        pass2.add(tid)
        n += 1
        if n >= limit:
            break
    state["done_tokens"] = sorted(done)
    state["pass2_tokens"] = sorted(pass2)[-2000:]
    return n


def run_forever(
    *,
    sleep_sec: float = 2.0,
    html_every: int = 5,
    expand_every: int = 3,
) -> int:
    if not ETHERSCAN_API_KEY:
        logger.error("ETHERSCAN_API_KEY required")
        return 1

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    sess = requests.Session()
    sess.trust_env = False
    sess.headers.update({"User-Agent": "MUTE-continuous/0.1", "Accept": "application/json"})
    pace_es = Pace(max(REQUEST_DELAY_SEC, 0.45))
    platforms = _load_platform_map(sess, Pace(1.2))
    known = _load_known()
    tokens = _all_tokens()
    logger.info("Continuous scanner start · tokens in cache=%s · graph=%s", len(tokens), gs.GRAPH_DIR)

    processed_since_html = 0
    since_expand = 0

    while not _STOP:
        state = gs.load_state()
        state["cycles"] = int(state.get("cycles") or 0) + 1

        # Prefer expand hop sometimes
        do_expand = since_expand >= expand_every and (state.get("expand_queue") or [])
        if do_expand:
            addr, exp_meta = gs.pop_expand(state)
            gs.save_state(state)
            if addr:
                hop_n = int(exp_meta.get("hop") or 1)
                via = "expand2" if hop_n >= 2 else "expand"
                logger.info("Expand %s-hop %s (%s)", hop_n, addr, exp_meta.get("reason") or via)
                try:
                    _process_expand(
                        sess,
                        pace_es,
                        known,
                        addr,
                        state,
                        via=via,
                        hop=hop_n,
                    )
                except Exception:
                    logger.exception("expand failed %s", addr)
                since_expand = 0
                gs.save_state(state)
                processed_since_html += 1
                continue

        token = _next_token(state, tokens)
        if not token:
            # Pass-2: expand clusters, requeue young tokens, refresh hub
            added_exp = 0
            if not (state.get("expand_queue") or []):
                added_exp = _enqueue_cluster_expands(state, limit=40)
            added_tok = 0
            if not (state.get("expand_queue") or []) and not _next_token(state, tokens):
                # only requeue if we haven't recently
                cycles = int(state.get("cycles") or 0)
                last_pass2 = int(state.get("last_pass2_cycle") or 0)
                if cycles - last_pass2 >= 50:
                    added_tok = _requeue_priority_tokens(state, tokens, limit=30)
                    state["last_pass2_cycle"] = cycles
            logger.info(
                "Queue empty · expand_added=%s requeue=%s expand_q=%s — refresh hub, sleep 60s",
                added_exp,
                added_tok,
                len(state.get("expand_queue") or []),
            )
            gs.save_state(state)
            write_graph_html()
            try:
                from pump_prep.hub import write_hub_html

                write_hub_html()
            except Exception:
                logger.debug("hub refresh skip", exc_info=True)
            for _ in range(60):
                if _STOP:
                    break
                time.sleep(1)
            tokens = _all_tokens()
            platforms = _load_platform_map(sess, Pace(1.2))
            known = _load_known()
            continue

        logger.info(
            "Scan %s (%s) · done=%s queue_left≈%s",
            token.get("symbol"),
            token.get("id"),
            len(state.get("done_tokens") or []),
            max(0, len(tokens) - len(state.get("done_tokens") or [])),
        )
        try:
            _process_token(sess, pace_es, platforms, known, token, state)
        except Exception:
            logger.exception("token failed %s", token.get("id"))
            gs.mark_token_done(state, token["id"], ok=False)
        gs.save_state(state)
        since_expand += 1
        processed_since_html += 1

        if processed_since_html >= html_every:
            path = write_graph_html()
            try:
                from pump_prep.hub import write_hub_html

                write_hub_html()
            except Exception:
                logger.debug("hub html skip", exc_info=True)
            logger.info("HTML updated %s", path)
            processed_since_html = 0

        time.sleep(sleep_sec)

    write_graph_html()
    logger.info("Continuous scanner stopped cleanly")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Resumable continuous deployer/graph scanner")
    p.add_argument("command", nargs="?", default="run", choices=["run", "html", "status"])
    p.add_argument("--sleep", type=float, default=2.0)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "status":
        print(__import__("json").dumps(gs.aggregate_summary()["state"], indent=2, ensure_ascii=False))
        return 0
    if args.command == "html":
        print(write_graph_html())
        return 0
    return run_forever(sleep_sec=args.sleep)


if __name__ == "__main__":
    raise SystemExit(main())
