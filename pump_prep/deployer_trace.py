"""Trace token deployers → outbound flows → match known funds/MM/CEX."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from pump_prep.cex_labels import cex_name, is_major_symbol
from pump_prep.config import (
    ETHERSCAN_API_KEY,
    ETHERSCAN_V2,
    EXPLORERS,
    MCAP_CACHE,
    OUT_DIR,
    REQUEST_DELAY_SEC,
    ROOT,
    SEEDS_FILE,
)
from pump_prep.etherscan import Pace, fetch_token_transfers
from pump_prep.seeds import load_seeds, seed_index

logger = logging.getLogger(__name__)

COINGECKO = "https://api.coingecko.com/api/v3"

# platform id on CoinGecko → chain_id
PLATFORM_CHAIN: dict[str, int] = {
    "ethereum": 1,
    "binance-smart-chain": 56,
    "arbitrum-one": 42161,
    "base": 8453,
    "polygon-pos": 137,
    "optimistic-ethereum": 10,
    "avalanche": 43114,
}

CHAIN_PRIORITY = [1, 56, 42161, 8453, 137, 10, 43114]


def _short(a: str) -> str:
    if not a or len(a) < 12:
        return a or "—"
    return f"{a[:6]}…{a[-4:]}"


def _load_known() -> dict[str, dict[str, Any]]:
    """address(lower) -> {entity, label, role} — unified registry."""
    from pump_prep.labels import load_known

    return load_known()


def _pick_tokens(limit: int, max_age_days: int | None) -> list[dict[str, Any]]:
    if not MCAP_CACHE.exists():
        raise FileNotFoundError(f"Need token cache: {MCAP_CACHE}")
    data = json.loads(MCAP_CACHE.read_text())
    tokens = list(data.get("tokens") or [])
    if max_age_days is not None:
        tokens = [
            t
            for t in tokens
            if t.get("age_days") is not None and t["age_days"] <= max_age_days
        ]
    tokens.sort(key=lambda t: -(t.get("vol24h") or 0))
    return tokens[:limit]


def _load_platform_map(sess: requests.Session, pace: Pace) -> dict[str, dict[str, str]]:
    """coin_id -> {platform: contract}."""
    cache = OUT_DIR / "cg_platforms_cache.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
        return json.loads(cache.read_text(encoding="utf-8"))
    pace.wait()
    for attempt in range(5):
        try:
            r = sess.get(
                f"{COINGECKO}/coins/list",
                params={"include_platform": "true"},
                timeout=120,
            )
            if r.status_code == 429:
                time.sleep(25 * (attempt + 1))
                continue
            r.raise_for_status()
            rows = r.json()
            break
        except Exception as e:
            logger.warning("CG list attempt %s: %s", attempt, e)
            time.sleep(10)
    else:
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        return {}

    out: dict[str, dict[str, str]] = {}
    for row in rows:
        cid = row.get("id")
        plats = row.get("platforms") or {}
        if cid and plats:
            out[cid] = {k: str(v).lower() for k, v in plats.items() if v}
    cache.write_text(json.dumps(out), encoding="utf-8")
    logger.info("Cached %d coin platforms", len(out))
    return out


def _contract_from_map(
    platforms_by_id: dict[str, dict[str, str]],
    coin_id: str,
) -> tuple[str, int, str] | None:
    platforms = platforms_by_id.get(coin_id) or {}
    ranked = []
    for plat, addr in platforms.items():
        if not addr or not str(addr).startswith("0x"):
            continue
        cid = PLATFORM_CHAIN.get(plat)
        if cid is None:
            continue
        ranked.append(
            (CHAIN_PRIORITY.index(cid) if cid in CHAIN_PRIORITY else 99, cid, plat, addr.lower())
        )
    if not ranked:
        return None
    ranked.sort()
    _, cid, plat, addr = ranked[0]
    return addr, cid, plat


def _cg_contract(
    sess: requests.Session,
    pace: Pace,
    coin_id: str,
) -> tuple[str, int, str] | None:
    """Fallback single-coin lookup (prefer platform map)."""
    pace.wait()
    try:
        r = sess.get(
            f"{COINGECKO}/coins/{coin_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "market_data": "false",
                "community_data": "false",
                "developer_data": "false",
            },
            timeout=45,
        )
        if r.status_code == 429:
            time.sleep(20)
            return None
        r.raise_for_status()
        platforms = (r.json().get("platforms") or {})
    except Exception as e:
        logger.warning("CG %s: %s", coin_id, e)
        return None

    ranked = []
    for plat, addr in platforms.items():
        if not addr or not str(addr).startswith("0x"):
            continue
        cid = PLATFORM_CHAIN.get(plat)
        if cid is None:
            continue
        ranked.append(
            (CHAIN_PRIORITY.index(cid) if cid in CHAIN_PRIORITY else 99, cid, plat, addr.lower())
        )
    if not ranked:
        return None
    ranked.sort()
    _, cid, plat, addr = ranked[0]
    return addr, cid, plat


def _get_creators(
    sess: requests.Session,
    pace: Pace,
    chain_id: int,
    contracts: list[str],
) -> dict[str, dict[str, Any]]:
    """Batch up to 5 contracts → contractAddress -> creation info."""
    out: dict[str, dict[str, Any]] = {}
    api_key = ETHERSCAN_API_KEY
    if not api_key:
        return out
    for i in range(0, len(contracts), 5):
        batch = contracts[i : i + 5]
        pace.wait()
        try:
            resp = sess.get(
                ETHERSCAN_V2,
                params={
                    "chainid": chain_id,
                    "module": "contract",
                    "action": "getcontractcreation",
                    "contractaddresses": ",".join(batch),
                    "apikey": api_key,
                },
                timeout=45,
            )
            data = resp.json()
        except Exception:
            logger.exception("getcontractcreation fail")
            continue
        if str(data.get("status")) != "1":
            logger.debug("creation miss: %s", data.get("result"))
            continue
        for row in data.get("result") or []:
            c = (row.get("contractAddress") or "").lower()
            out[c] = {
                "creator": (row.get("contractCreator") or "").lower(),
                "tx_hash": row.get("txHash") or "",
                "timestamp": int(row.get("timestamp") or 0),
                "factory": (row.get("contractFactory") or "").lower(),
            }
    return out


def analyze_deployers(
    *,
    limit: int = 40,
    max_age_days: int | None = 365,
    out_per_deployer: int = 80,
) -> dict[str, Any]:
    if not ETHERSCAN_API_KEY:
        raise RuntimeError("ETHERSCAN_API_KEY required")

    known = _load_known()
    seeds = seed_index(load_seeds(SEEDS_FILE))
    tokens = _pick_tokens(limit, max_age_days)

    sess = requests.Session()
    sess.trust_env = False
    sess.headers.update({"User-Agent": "MUTE-deployer-trace/0.1", "Accept": "application/json"})
    pace = Pace(max(REQUEST_DELAY_SEC, 1.1))  # CG free tier friendly

    # Resolve contracts
    platforms_by_id = _load_platform_map(sess, Pace(1.2))
    resolved: list[dict[str, Any]] = []
    logger.info("Resolving contracts for %d tokens…", len(tokens))
    for t in tokens:
        cid = t.get("id")
        if not cid:
            continue
        hit = _contract_from_map(platforms_by_id, cid)
        if not hit:
            continue
        contract, chain_id, plat = hit
        resolved.append({
            "id": cid,
            "symbol": t.get("symbol"),
            "name": t.get("name"),
            "mcap": t.get("mcap"),
            "vol24h": t.get("vol24h"),
            "age_days": t.get("age_days"),
            "contract": contract,
            "chain_id": chain_id,
            "platform": plat,
        })
    logger.info("Resolved %d / %d with EVM contracts", len(resolved), len(tokens))

    # Creators by chain
    by_chain: dict[int, list[dict]] = defaultdict(list)
    for r in resolved:
        by_chain[r["chain_id"]].append(r)

    for chain_id, rows in by_chain.items():
        contracts = [r["contract"] for r in rows]
        creators = _get_creators(sess, Pace(REQUEST_DELAY_SEC), chain_id, contracts)
        for r in rows:
            info = creators.get(r["contract"]) or {}
            r["deployer"] = info.get("creator") or ""
            r["deploy_tx"] = info.get("tx_hash") or ""
            r["deploy_ts"] = info.get("timestamp") or 0
            r["factory"] = info.get("factory") or ""

    # Trace deployer outflows + early token recipients
    pace_es = Pace(REQUEST_DELAY_SEC)
    flows: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    token_rows: list[dict[str, Any]] = []

    for r in resolved:
        deployer = r.get("deployer") or ""
        if not deployer:
            token_rows.append({**r, "flow_count": 0, "match_count": 0, "status": "no_deployer"})
            continue

        # All token txs involving deployer (in+out) on that chain
        txs = fetch_token_transfers(
            sess, deployer, r["chain_id"], pace=pace_es, offset=out_per_deployer
        )
        # Focus: outs from deployer, and transfers of THIS token
        contract = r["contract"]
        related = []
        for tx in txs:
            is_this = (tx.get("contract") or "") == contract
            is_out = tx.get("direction") == "out"
            if not (is_this or is_out):
                continue
            related.append(tx)

        # Also fetch transfers of the token contract via tokentx? Etherscan needs address=
        # Use deployer outs of this token as primary; also first hops to known

        local_matches = []
        for tx in related:
            counterparty = tx["to"] if tx["direction"] == "out" else tx["from"]
            hit = known.get(counterparty)
            cex = cex_name(counterparty)
            row = {
                "symbol": r["symbol"],
                "token_id": r["id"],
                "contract": contract,
                "chain_id": r["chain_id"],
                "chain": EXPLORERS.get(r["chain_id"], "").replace("https://", "").split(".")[0],
                "deployer": deployer,
                "direction": tx["direction"],
                "from": tx["from"],
                "to": tx["to"],
                "counterparty": counterparty,
                "flow_symbol": tx.get("symbol"),
                "is_token_itself": (tx.get("contract") or "") == contract,
                "hash": tx.get("hash"),
                "timestamp": tx.get("timestamp"),
                "match_entity": (hit or {}).get("entity") if hit else (cex if cex else ""),
                "match_label": (hit or {}).get("label") if hit else (f"{cex} hot" if cex else ""),
                "match_role": (hit or {}).get("role") if hit else ("cex" if cex else ""),
            }
            flows.append(row)
            if hit or cex:
                local_matches.append(row)
                matches.append(row)

        # Label deployer itself if known
        dep_hit = known.get(deployer)
        token_rows.append({
            **r,
            "flow_count": len(related),
            "match_count": len(local_matches),
            "deployer_known": bool(dep_hit),
            "deployer_entity": (dep_hit or {}).get("entity") or "",
            "status": "ok",
        })

    # Aggregate: which known entities appear most
    entity_hits: dict[str, int] = defaultdict(int)
    for m in matches:
        if m.get("match_entity"):
            entity_hits[m["match_entity"]] += 1

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "token → CoinGecko contract → Etherscan deployer → tokentx outs → match funds/CEX",
        "limit": limit,
        "max_age_days": max_age_days,
        "tokens_input": len(tokens),
        "tokens_resolved": len(resolved),
        "tokens": token_rows,
        "flows": flows,
        "matches": matches,
        "entity_hits": dict(sorted(entity_hits.items(), key=lambda x: -x[1])),
        "stats": {
            "with_deployer": sum(1 for t in token_rows if t.get("deployer")),
            "with_matches": sum(1 for t in token_rows if t.get("match_count", 0) > 0),
            "match_flows": len(matches),
            "total_flows": len(flows),
        },
    }
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "deployer_trace_data.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def write_deployer_html(data: dict[str, Any], path: Path | None = None) -> Path:
    import html as html_mod

    path = path or (OUT_DIR / "deployer_trace.html")

    def esc(x: Any) -> str:
        return html_mod.escape("" if x is None else str(x))

    def money(x: Any) -> str:
        if x is None:
            return "—"
        x = float(x)
        if x >= 1e6:
            return f"${x/1e6:.2f}M"
        if x >= 1e3:
            return f"${x/1e3:.1f}K"
        return f"${x:.0f}"

    def ts(t: Any) -> str:
        if not t:
            return "—"
        return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

    def short(a: str) -> str:
        return _short(a)

    tokens = data.get("tokens") or []
    matches = data.get("matches") or []
    flows = data.get("flows") or []
    stats = data.get("stats") or {}
    entity_hits = data.get("entity_hits") or {}

    tok_rows = []
    for t in tokens:
        dep = t.get("deployer") or ""
        cid = int(t.get("chain_id") or 1)
        base = EXPLORERS.get(cid, "https://etherscan.io")
        cls = "hit" if t.get("match_count") else ("known" if t.get("deployer_known") else "")
        tok_rows.append(
            f"<tr class='{cls}' data-q='{esc((t.get('symbol') or '')+' '+(t.get('name') or '')+' '+dep).lower()}' "
            f"data-match='{1 if t.get('match_count') else 0}'>"
            f"<td><b>{esc(t.get('symbol'))}</b><div class='sub'>{esc(t.get('name'))}</div></td>"
            f"<td class='num'>{esc(money(t.get('mcap')))}</td>"
            f"<td class='num'>{esc(t.get('age_days') if t.get('age_days') is not None else '—')}</td>"
            f"<td>{esc(t.get('platform'))}</td>"
            f"<td title='{esc(t.get('contract'))}'><a href='{base}/token/{esc(t.get('contract'))}' target='_blank' rel='noopener'>{esc(short(t.get('contract') or ''))}</a></td>"
            f"<td title='{esc(dep)}'>"
            + (
                f"<a href='{base}/address/{esc(dep)}' target='_blank' rel='noopener'>{esc(short(dep))}</a>"
                if dep
                else "—"
            )
            + (
                f"<div class='sub ok'>{esc(t.get('deployer_entity'))}</div>"
                if t.get("deployer_entity")
                else ""
            )
            + f"</td>"
            f"<td class='num'>{t.get('flow_count') or 0}</td>"
            f"<td class='num'>{t.get('match_count') or 0}</td>"
            f"</tr>"
        )

    match_rows = []
    for m in matches:
        cid = int(m.get("chain_id") or 1)
        base = EXPLORERS.get(cid, "https://etherscan.io")
        role = m.get("match_role") or ""
        qmatch = f"{m.get('symbol')} {m.get('match_entity')} {m.get('deployer')} {m.get('counterparty')}".lower()
        match_rows.append(
            f"<tr class='role-{esc(role)}' data-entity='{esc(m.get('match_entity') or '')}' "
            f"data-q='{esc(qmatch)}'>"
            f"<td><b>{esc(m.get('symbol'))}</b></td>"
            f"<td title='{esc(m.get('deployer'))}'><a href='{base}/address/{esc(m.get('deployer'))}' target='_blank' rel='noopener'>{esc(short(m.get('deployer') or ''))}</a></td>"
            f"<td>{esc(m.get('direction'))}</td>"
            f"<td title='{esc(m.get('counterparty'))}'><a href='{base}/address/{esc(m.get('counterparty'))}' target='_blank' rel='noopener'>{esc(short(m.get('counterparty') or ''))}</a></td>"
            f"<td><span class='pill pill-{esc(role)}'>{esc(m.get('match_entity'))}</span>"
            f"<div class='sub'>{esc(m.get('match_label'))}</div></td>"
            f"<td>{esc(m.get('flow_symbol'))}</td>"
            f"<td>{'token' if m.get('is_token_itself') else 'other'}</td>"
            f"<td>{esc(ts(m.get('timestamp')))}</td>"
            f"<td><a href='{base}/tx/{esc(m.get('hash'))}' target='_blank' rel='noopener'>tx</a></td>"
            f"</tr>"
        )

    # sample of non-match flows (first 150)
    flow_sample = [f for f in flows if not f.get("match_entity")][:150]
    flow_rows = []
    for f in flow_sample:
        cid = int(f.get("chain_id") or 1)
        base = EXPLORERS.get(cid, "https://etherscan.io")
        qflow = f"{f.get('symbol')} {f.get('deployer')} {f.get('counterparty')}".lower()
        flow_rows.append(
            f"<tr data-q='{esc(qflow)}'>"
            f"<td><b>{esc(f.get('symbol'))}</b></td>"
            f"<td>{esc(short(f.get('deployer') or ''))}</td>"
            f"<td>{esc(f.get('direction'))}</td>"
            f"<td title='{esc(f.get('counterparty'))}'>{esc(short(f.get('counterparty') or ''))}</td>"
            f"<td>{esc(f.get('flow_symbol'))}</td>"
            f"<td>{esc(ts(f.get('timestamp')))}</td>"
            f"<td><a href='{base}/tx/{esc(f.get('hash'))}' target='_blank' rel='noopener'>tx</a></td>"
            f"</tr>"
        )

    ent_html = "".join(
        f"<span class='ent'>{esc(k)} · {v}</span>" for k, v in list(entity_hits.items())[:20]
    )

    doc = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Deployer trace — токен → первый адрес → куда ушло</title>
<style>
:root {{ --bg:#0f1115; --panel:#171a21; --text:#e8eaed; --muted:#9aa0a6; --line:#2a2f3a; --accent:#7cb3ff; --ok:#3dd68c; --danger:#f07178; --warn:#e6b84d; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:14px/1.45 ui-sans-serif,system-ui,sans-serif; background:var(--bg); color:var(--text); }}
header {{ padding:18px 24px 12px; position:sticky; top:0; background:rgba(15,17,21,.96); border-bottom:1px solid var(--line); z-index:5; }}
h1 {{ margin:0 0 6px; font-size:20px; }}
h2 {{ margin:20px 0 10px; font-size:16px; }}
.meta {{ color:var(--muted); font-size:13px; margin-bottom:10px; }}
.controls {{ display:flex; gap:10px; flex-wrap:wrap; }}
input, select {{ background:var(--panel); color:var(--text); border:1px solid var(--line); border-radius:8px; padding:8px 10px; }}
input {{ flex:1; min-width:200px; }}
.stats {{ display:flex; gap:14px; flex-wrap:wrap; margin-top:8px; color:var(--muted); font-size:12px; }}
.ents {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
.ent {{ background:var(--panel); border:1px solid var(--line); border-radius:999px; padding:3px 10px; font-size:11px; }}
.wrap {{ padding:0 16px 40px; overflow:auto; }}
table {{ width:100%; border-collapse:collapse; min-width:900px; }}
th, td {{ padding:7px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
th {{ background:#1b2030; color:var(--muted); font-size:11px; text-transform:uppercase; }}
td.num {{ text-align:right; font-variant-numeric:tabular-nums; font-family:ui-monospace,Menlo,monospace; font-size:12px; }}
.sub {{ color:var(--muted); font-size:10px; }} .ok {{ color:var(--ok); }}
a {{ color:var(--accent); text-decoration:none; }}
tr.hit td {{ background:rgba(61,214,140,.12); }}
tr.known td {{ background:rgba(124,179,255,.08); }}
tr.role-seed td {{ background:rgba(61,214,140,.10); }}
tr.role-cex td {{ background:rgba(240,113,120,.10); }}
.pill {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:650; background:#374151; color:#fff; }}
.pill-seed {{ background:var(--ok); color:#0b0d10; }}
.pill-cex {{ background:var(--danger); color:#fff; }}
</style>
</head>
<body>
<header>
  <h1>Токен → deployer (первый адрес) → куда ушло</h1>
  <div class="meta">{esc(data.get("method"))} · {esc(data.get("generated_at"))}</div>
  <div class="controls">
    <input id="q" type="text" placeholder="Поиск: symbol / deployer / fund…" />
    <select id="only">
      <option value="all">Все токены</option>
      <option value="match">Только с match фонд/CEX</option>
    </select>
  </div>
  <div class="stats">
    <span>input {esc(data.get('tokens_input'))}</span>
    <span>resolved {esc(data.get('tokens_resolved'))}</span>
    <span>deployers {esc(stats.get('with_deployer'))}</span>
    <span>с match {esc(stats.get('with_matches'))}</span>
    <span>match flows {esc(stats.get('match_flows'))}</span>
  </div>
  <div class="ents">{ent_html or '<span class="ent">пока нет совпадений с known seeds</span>'}</div>
</header>
<div class="wrap">
  <h2>Токены и deployers</h2>
  <table id="tok">
    <thead><tr><th>Token</th><th>Mcap</th><th>Age d</th><th>Chain</th><th>Contract</th><th>Deployer</th><th>Flows</th><th>Matches</th></tr></thead>
    <tbody>{''.join(tok_rows) if tok_rows else '<tr><td colspan="8">Нет данных</td></tr>'}</tbody>
  </table>

  <h2>Совпадения с фондами / MM / CEX</h2>
  <table id="match">
    <thead><tr><th>Token</th><th>Deployer</th><th>Dir</th><th>Counterparty</th><th>Match</th><th>Asset</th><th>Kind</th><th>Time</th><th>Tx</th></tr></thead>
    <tbody>{''.join(match_rows) if match_rows else '<tr><td colspan="9">Совпадений нет — расширь seeds или limit</td></tr>'}</tbody>
  </table>

  <h2>Прочие исходящие с deployer (сэмпл)</h2>
  <table id="flow">
    <thead><tr><th>Token</th><th>Deployer</th><th>Dir</th><th>To/From</th><th>Asset</th><th>Time</th><th>Tx</th></tr></thead>
    <tbody>{''.join(flow_rows) if flow_rows else '<tr><td colspan="7">—</td></tr>'}</tbody>
  </table>
</div>
<script>
const q=document.getElementById('q');
const only=document.getElementById('only');
function apply(){{
  const s=q.value.trim().toLowerCase();
  const o=only.value;
  for(const row of document.querySelectorAll('#tok tbody tr')){{
    if(!row.dataset.q) continue;
    const okM=o==='all'||row.dataset.match==='1';
    const okQ=!s||row.dataset.q.includes(s);
    row.style.display=(okM&&okQ)?'':'none';
  }}
  for(const sel of ['#match','#flow']){{
    for(const row of document.querySelectorAll(sel+' tbody tr')){{
      if(!row.dataset.q) continue;
      row.style.display=(!s||row.dataset.q.includes(s))?'':'none';
    }}
  }}
}}
q.addEventListener('input', apply);
only.addEventListener('change', apply);
</script>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")
    return path
