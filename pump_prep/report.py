from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pump_prep.config import EXPLORERS, OUT_DIR


def _esc(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def _fmt_ts(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _fmt_mcap(m: float | None) -> str:
    if m is None:
        return "н/д"
    if m >= 1e6:
        return f"${m/1e6:.2f}M"
    if m >= 1e3:
        return f"${m/1e3:.1f}K"
    return f"${m:.0f}"


def _short(a: str) -> str:
    if not a or len(a) < 12:
        return a or "—"
    return f"{a[:6]}…{a[-4:]}"


def _explorer_addr(chain_id: int, addr: str) -> str:
    base = EXPLORERS.get(chain_id) or EXPLORERS.get(1) or "https://etherscan.io"
    return f"{base}/address/{addr}"


def _explorer_tx(chain_id: int, txh: str) -> str:
    base = EXPLORERS.get(chain_id) or EXPLORERS.get(1) or "https://etherscan.io"
    return f"{base}/tx/{txh}"


def write_html(data: dict[str, Any], path: Path | None = None) -> Path:
    path = path or (OUT_DIR / "pump_prep_report.html")
    signals = data.get("signals") or []
    addresses = data.get("addresses") or []
    edges = data.get("edges") or []
    stats = data.get("stats") or {}

    sig_rows = []
    for s in signals:
        st = s.get("type") or ""
        cid = int(s.get("chain_id") or 1)
        txh = s.get("hash") or ""
        link = (
            f"<a href='{_esc(_explorer_tx(cid, txh))}' target='_blank' rel='noopener'>tx</a>"
            if txh
            else "—"
        )
        seed = s.get("seed") or ""
        cp = s.get("counterparty") or ""
        sig_rows.append(
            "<tr class='sig-{st}' data-type='{st}' data-entity='{ent}' data-sym='{sym}' "
            "data-q='{q}'>"
            "<td><span class='pill pill-{st}'>{st}</span></td>"
            "<td>{ent}</td>"
            "<td title='{seed}'><a href='{sa}' target='_blank' rel='noopener'>{ss}</a><div class='sub'>{sl}</div></td>"
            "<td title='{cp}'>{cps}</td>"
            "<td><b>{sym}</b></td>"
            "<td class='num'>{mcap}</td>"
            "<td>{chain}</td>"
            "<td>{ts}</td>"
            "<td>{note}</td>"
            "<td>{link}</td>"
            "</tr>".format(
                st=_esc(st),
                ent=_esc(s.get("entity") or ""),
                seed=_esc(seed),
                sa=_esc(_explorer_addr(cid if cid else 1, seed)) if seed.startswith("0x") else "#",
                ss=_esc(_short(seed)),
                sl=_esc(s.get("seed_label") or ""),
                cp=_esc(cp),
                cps=_esc(_short(cp) if isinstance(cp, str) and cp.startswith("0x") else cp),
                sym=_esc(s.get("symbol") or ""),
                mcap=_esc(_fmt_mcap(s.get("mcap"))),
                chain=_esc(s.get("chain") or ""),
                ts=_esc(_fmt_ts(s.get("timestamp"))),
                note=_esc(s.get("note") or ""),
                link=link,
                q=_esc(
                    f"{st} {s.get('entity')} {s.get('symbol')} {s.get('note')} {seed} {cp}".lower()
                ),
            )
        )

    addr_rows = []
    for a in addresses:
        roles = a.get("roles") or []
        role_pills = "".join(f"<span class='role role-{_esc(r)}'>{_esc(r)}</span>" for r in roles)
        primary = roles[0] if roles else "other"
        addr_rows.append(
            "<tr class='role-{prim}' data-role='{roles}' data-entity='{ent}' data-q='{q}'>"
            "<td title='{addr}'><a href='{ex}' target='_blank' rel='noopener'>{short}</a></td>"
            "<td>{label}</td>"
            "<td>{pills}</td>"
            "<td>{ent}</td>"
            "<td class='num'>{touch}</td>"
            "<td>{syms}</td>"
            "</tr>".format(
                prim=_esc(primary),
                roles=_esc(",".join(roles)),
                ent=_esc(", ".join(a.get("entities") or [])),
                q=_esc(f"{a.get('address')} {a.get('label')} {' '.join(roles)}".lower()),
                addr=_esc(a.get("address")),
                ex=_esc(a.get("explorer") or "#"),
                short=_esc(a.get("short") or _short(a.get("address") or "")),
                label=_esc(a.get("label") or a.get("cex") or ""),
                pills=role_pills,
                touch=a.get("tx_touch") or 0,
                syms=_esc(", ".join(a.get("symbols") or [])[:80]),
            )
        )

    edge_rows = []
    for e in edges[:300]:
        cid = int(e.get("chain_id") or 1)
        frm, to = e.get("from") or "", e.get("to") or ""
        to_cex = e.get("to_cex") or ""
        edge_rows.append(
            "<tr data-sym='{sym}' data-q='{q}' class='{cls}'>"
            "<td title='{frm}'><a href='{fa}' target='_blank' rel='noopener'>{fs}</a></td>"
            "<td title='{to}'><a href='{ta}' target='_blank' rel='noopener'>{ts}</a>"
            "{cex}</td>"
            "<td><b>{sym}</b></td>"
            "<td class='num'>{cnt}</td>"
            "<td>{chain}</td>"
            "<td>{last}</td>"
            "<td>{ent}</td>"
            "</tr>".format(
                sym=_esc(e.get("symbol") or ""),
                q=_esc(f"{frm} {to} {e.get('symbol')} {to_cex}".lower()),
                cls="edge-cex" if to_cex else "",
                frm=_esc(frm),
                fa=_esc(_explorer_addr(cid, frm)),
                fs=_esc(_short(frm)),
                to=_esc(to),
                ta=_esc(_explorer_addr(cid, to)),
                ts=_esc(_short(to)),
                cex=f" <span class='cex'>{_esc(to_cex)}</span>" if to_cex else "",
                cnt=e.get("count") or 0,
                chain=_esc(e.get("chain") or ""),
                last=_esc(_fmt_ts(e.get("last_seen"))),
                ent=_esc(", ".join(e.get("entities") or [])),
            )
        )

    by_type = stats.get("signals_by_type") or {}
    type_opts = "".join(
        f"<option value='{_esc(k)}'>{_esc(k)} ({v})</option>" for k, v in sorted(by_type.items())
    )

    doc = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Pump prep — адреса и связи</title>
<style>
:root {{
  --bg:#0f1115; --panel:#171a21; --text:#e8eaed; --muted:#9aa0a6; --line:#2a2f3a;
  --accent:#7cb3ff; --danger:#f07178; --warn:#e6b84d; --ok:#3dd68c; --info:#7cb3ff;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:14px/1.45 ui-sans-serif,system-ui,sans-serif; background:var(--bg); color:var(--text); }}
header {{ padding:18px 24px 12px; position:sticky; top:0; background:rgba(15,17,21,.96); backdrop-filter:blur(8px); border-bottom:1px solid var(--line); z-index:5; }}
h1 {{ margin:0 0 6px; font-size:20px; font-weight:650; }}
h2 {{ margin:22px 0 10px; font-size:16px; }}
.meta {{ color:var(--muted); font-size:13px; margin-bottom:10px; }}
.controls {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom:8px; }}
input, select {{ background:var(--panel); color:var(--text); border:1px solid var(--line); border-radius:8px; padding:8px 10px; }}
input {{ min-width:200px; flex:1; }}
.stats {{ display:flex; gap:14px; flex-wrap:wrap; color:var(--muted); font-size:12px; }}
.wrap {{ padding:0 16px 40px; overflow:auto; }}
table {{ width:100%; border-collapse:collapse; min-width:960px; margin-bottom:8px; }}
th, td {{ padding:7px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
th {{ background:#1b2030; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.03em; position:sticky; top:0; }}
td.num {{ font-variant-numeric:tabular-nums; text-align:right; font-family:ui-monospace,Menlo,monospace; font-size:12px; }}
.sub {{ color:var(--muted); font-size:10px; }}
a {{ color:var(--accent); text-decoration:none; }}
.pill {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:650; color:#0b0d10; }}
.pill-new_token_in {{ background:#3dd68c; }}
.pill-cex_deposit {{ background:#f07178; color:#fff; }}
.pill-shared_funder {{ background:#e6b84d; }}
.pill-repeat_counterparty {{ background:#7cb3ff; }}
tr.sig-new_token_in td {{ background:rgba(61,214,140,.10); }}
tr.sig-cex_deposit td {{ background:rgba(240,113,120,.12); }}
tr.sig-shared_funder td {{ background:rgba(230,184,77,.10); }}
tr.sig-repeat_counterparty td {{ background:rgba(124,179,255,.10); }}
.role {{ display:inline-block; margin:1px 3px 1px 0; padding:1px 6px; border-radius:4px; font-size:10px; font-weight:650; background:#374151; color:#fff; }}
.role-seed {{ background:#3dd68c; color:#0b0d10; }}
.role-cex {{ background:#f07178; color:#fff; }}
.role-counterparty {{ background:#7cb3ff; color:#0b0d10; }}
.role-expanded {{ background:#a78bfa; color:#0b0d10; }}
.role-shared_funder {{ background:#e6b84d; color:#0b0d10; }}
.role-fresh {{ background:#5eead4; color:#0b0d10; }}
.role-repeat_counterparty {{ background:#f9a8d4; color:#0b0d10; }}
tr.role-seed td {{ background:rgba(61,214,140,.08); }}
tr.role-cex td {{ background:rgba(240,113,120,.08); }}
.cex {{ font-size:10px; background:#f07178; color:#fff; padding:1px 5px; border-radius:4px; margin-left:4px; }}
tr.edge-cex td {{ background:rgba(240,113,120,.08); }}
.legend {{ display:flex; flex-wrap:wrap; gap:8px; margin:8px 0; }}
.legend span {{ font-size:11px; padding:3px 8px; border-radius:999px; border:1px solid var(--line); }}
</style>
</head>
<body>
<header>
  <h1>Pump prep — адреса и связи</h1>
  <div class="meta">
    Lookback { _esc(data.get('lookback_days')) }д · seeds { _esc(data.get('seed_count')) } ·
    transfers { _esc(data.get('transfer_count')) } · generated { _esc(data.get('generated_at')) }
  </div>
  <div class="controls">
    <input id="q" type="text" placeholder="Поиск по сигналам / адресам / связям…" />
    <select id="stype">
      <option value="all">Сигнал: все</option>
      {type_opts}
    </select>
    <select id="arole">
      <option value="all">Роль адреса: все</option>
      <option value="seed">seed</option>
      <option value="counterparty">counterparty</option>
      <option value="cex">cex</option>
      <option value="expanded">expanded</option>
      <option value="shared_funder">shared_funder</option>
      <option value="fresh">fresh</option>
      <option value="repeat_counterparty">repeat_counterparty</option>
    </select>
  </div>
  <div class="legend">
    <span style="color:var(--muted);border:none;padding:0">Сигналы:</span>
    <span style="background:rgba(61,214,140,.2);color:#3dd68c">new_token_in</span>
    <span style="background:rgba(240,113,120,.2);color:#f07178">cex_deposit</span>
    <span style="background:rgba(230,184,77,.2);color:#e6b84d">shared_funder</span>
    <span style="background:rgba(124,179,255,.2);color:#7cb3ff">repeat_counterparty</span>
  </div>
  <div class="stats">
    <span id="shown-sig">signals: {len(signals)}</span>
    <span id="shown-addr">addresses: {len(addresses)}</span>
    <span id="shown-edge">edges: {len(edges)}</span>
    <span>типы: {_esc(by_type)}</span>
  </div>
</header>

<div class="wrap">
  <h2>Сигналы prep</h2>
  <table id="sig">
    <thead><tr>
      <th>Тип</th><th>Entity</th><th>Seed</th><th>Counterparty</th>
      <th>Token</th><th>Mcap</th><th>Chain</th><th>Time UTC</th><th>Note</th><th>Tx</th>
    </tr></thead>
    <tbody>
      {''.join(sig_rows) if sig_rows else '<tr><td colspan="10">Нет сигналов за окно (проверь API key / seeds)</td></tr>'}
    </tbody>
  </table>

  <h2>Адреса</h2>
  <table id="addr">
    <thead><tr>
      <th>Address</th><th>Label</th><th>Roles</th><th>Entities</th><th>Touches</th><th>Symbols</th>
    </tr></thead>
    <tbody>
      {''.join(addr_rows)}
    </tbody>
  </table>

  <h2>Связи (from → to)</h2>
  <table id="edge">
    <thead><tr>
      <th>From</th><th>To</th><th>Token</th><th>Count</th><th>Chain</th><th>Last</th><th>Entities</th>
    </tr></thead>
    <tbody>
      {''.join(edge_rows)}
    </tbody>
  </table>
</div>

<script>
const q=document.getElementById('q');
const stype=document.getElementById('stype');
const arole=document.getElementById('arole');
function apply(){{
  const s=q.value.trim().toLowerCase();
  const t=stype.value;
  const r=arole.value;
  let ns=0,na=0,ne=0;
  for(const row of document.querySelectorAll('#sig tbody tr')){{
    if(!row.dataset.type) continue;
    const okT=t==='all'||row.dataset.type===t;
    const okQ=!s||(row.dataset.q||'').includes(s);
    const show=okT&&okQ;
    row.style.display=show?'':'none';
    if(show) ns++;
  }}
  for(const row of document.querySelectorAll('#addr tbody tr')){{
    const roles=(row.dataset.role||'').split(',');
    const okR=r==='all'||roles.includes(r);
    const okQ=!s||(row.dataset.q||'').includes(s);
    const show=okR&&okQ;
    row.style.display=show?'':'none';
    if(show) na++;
  }}
  for(const row of document.querySelectorAll('#edge tbody tr')){{
    const okQ=!s||(row.dataset.q||'').includes(s);
    row.style.display=okQ?'':'none';
    if(okQ) ne++;
  }}
  document.getElementById('shown-sig').textContent='signals: '+ns;
  document.getElementById('shown-addr').textContent='addresses: '+na;
  document.getElementById('shown-edge').textContent='edges: '+ne;
}}
q.addEventListener('input', apply);
stype.addEventListener('change', apply);
arole.addEventListener('change', apply);
apply();
</script>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    return path
