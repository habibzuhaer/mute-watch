from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOKEN_COLORS = {
    "BTC": "#F7931A",
    "ETH": "#627EEA",
    "SOL": "#14F195",
    "USDC": "#2775CA",
    "USDT": "#26A17B",
}


def _color_for(token: str) -> str:
    if token in TOKEN_COLORS:
        return TOKEN_COLORS[token]
    h = sum(ord(c) * (i + 1) for i, c in enumerate(token or "?"))
    return f"hsl({h % 360} 55% 42%)"


def build_html(rows: list[dict[str, Any]], title: str = "Crypto Funds Portfolio") -> str:
    tokens = sorted({r.get("token") or "" for r in rows if r.get("token")})
    color_map = {t: _color_for(t) for t in tokens}
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = json.dumps(rows, ensure_ascii=False, default=str)
    colors_json = json.dumps(color_map)

    # Keep JS template literals intact — inject data via placeholders only.
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>
  :root {{ --bg:#0f1115; --card:#171a21; --text:#e8eaed; --muted:#9aa0a6; --line:#2a2f3a; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: ui-sans-serif, system-ui, sans-serif; background:var(--bg); color:var(--text); }}
  header {{ padding:20px 24px; border-bottom:1px solid var(--line); }}
  h1 {{ margin:0 0 6px; font-size:22px; font-weight:650; }}
  .meta {{ color:var(--muted); font-size:13px; }}
  .toolbar {{ display:flex; flex-wrap:wrap; gap:10px; padding:14px 24px; align-items:center; border-bottom:1px solid var(--line); }}
  input, select {{ background:var(--card); color:var(--text); border:1px solid var(--line); border-radius:8px; padding:8px 10px; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:8px; padding:10px 24px; }}
  .chip {{ display:inline-flex; align-items:center; gap:6px; padding:4px 10px; border-radius:999px; background:var(--card); border:1px solid var(--line); font-size:12px; cursor:pointer; }}
  .chip .dot {{ width:10px; height:10px; border-radius:50%; }}
  .chip.active {{ outline:1px solid #fff; }}
  .wrap {{ overflow:auto; padding:0 12px 40px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; min-width:1400px; }}
  th, td {{ padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap; }}
  th {{ position:sticky; top:0; background:#12151c; cursor:pointer; user-select:none; }}
  th:hover {{ color:#fff; }}
  tr:hover td {{ background:#1c212b; }}
  a {{ color:#8ab4f8; text-decoration:none; }}
  .tok {{ display:inline-block; padding:2px 8px; border-radius:6px; color:#fff; font-weight:600; font-size:12px; }}
  .num {{ font-variant-numeric: tabular-nums; text-align:right; }}
  .neg {{ color:#f28b82; }}
  .pos {{ color:#81c995; }}
  .na {{ color:var(--muted); }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="meta">Generated {generated} · click headers to sort · chips filter by token</div>
</header>
<div class="toolbar">
  <input id="q" type="search" placeholder="Search fund / token…" style="min-width:220px"/>
  <select id="typeFilter">
    <option value="">All types</option>
    <option value="midcap_watch">Mid-cap watch</option>
    <option value="public_company_dat">Public / DAT</option>
    <option value="vc_hedge">VC / Hedge</option>
  </select>
  <span class="meta" id="count"></span>
</div>
<div class="legend" id="legend"></div>
<div class="wrap">
<table id="tbl">
  <thead>
    <tr>
      <th data-col="fund_name">Fund</th>
      <th data-col="website">Website</th>
      <th data-col="fund_type">Type</th>
      <th data-col="token">Token</th>
      <th data-col="market_cap" data-num="1">Mcap $</th>
      <th data-col="amount" data-num="1">Amount</th>
      <th data-col="portfolio_pct" data-num="1">Portfolio %</th>
      <th data-col="entry_price_usd" data-num="1">Entry $</th>
      <th data-col="price_binance" data-num="1">Binance</th>
      <th data-col="price_bybit" data-num="1">Bybit</th>
      <th data-col="price_okx" data-num="1">OKX</th>
      <th data-col="price_bingx" data-num="1">BingX</th>
      <th data-col="vol_3m" data-num="1">Vol 3m %</th>
      <th data-col="vol_6m" data-num="1">Vol 6m %</th>
      <th data-col="vol_9m" data-num="1">Vol 9m %</th>
      <th data-col="chg_3m" data-num="1">Chg 3m %</th>
      <th data-col="chg_6m" data-num="1">Chg 6m %</th>
      <th data-col="chg_9m" data-num="1">Chg 9m %</th>
      <th data-col="held_since">Held since</th>
      <th data-col="source">Source</th>
    </tr>
  </thead>
  <tbody></tbody>
</table>
</div>
<script>
const ROWS = {payload};
const COLORS = {colors_json};
let sortCol = 'market_cap';
let sortDir = -1;
let tokenFilter = '';

function esc(s) {{
  return String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);
}}
function fmt(v, digits=2) {{
  if (v === null || v === undefined || v === '') return '<span class="na">н/д</span>';
  if (typeof v === 'number') return v.toLocaleString(undefined, {{maximumFractionDigits: digits}});
  return esc(v);
}}
function fmtPct(v) {{
  if (v === null || v === undefined || v === '') return '<span class="na">н/д</span>';
  const n = Number(v);
  const cls = n > 0 ? 'pos' : (n < 0 ? 'neg' : '');
  return '<span class="num '+cls+'">' + n.toFixed(2) + '%</span>';
}}
function linkWebsite(r) {{
  if (!r.website) return '<span class="na">н/д</span>';
  return '<a href="'+esc(r.website)+'" target="_blank" rel="noopener">site</a>';
}}
function tokenCell(tok) {{
  const c = COLORS[tok] || '#666';
  return '<span class="tok" style="background:'+c+'">'+esc(tok)+'</span>';
}}
function filtered() {{
  const q = (document.getElementById('q').value || '').toLowerCase();
  const tf = document.getElementById('typeFilter').value;
  return ROWS.filter(r => {{
    if (tokenFilter && r.token !== tokenFilter) return false;
    if (tf && r.fund_type !== tf) return false;
    if (!q) return true;
    const hay = ((r.fund_name||'')+' '+(r.token||'')+' '+(r.ticker||'')).toLowerCase();
    return hay.includes(q);
  }});
}}
function sortRows(rows) {{
  return rows.slice().sort((a,b) => {{
    let av = a[sortCol], bv = b[sortCol];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sortDir;
    return String(av).localeCompare(String(bv), undefined, {{sensitivity:'base'}}) * sortDir;
  }});
}}
function render() {{
  const rows = sortRows(filtered());
  document.getElementById('count').textContent = rows.length + ' rows';
  const tb = document.querySelector('#tbl tbody');
  tb.innerHTML = rows.map(r => '<tr>'
    + '<td>'+esc(r.fund_name||'')+'</td>'
    + '<td>'+linkWebsite(r)+'</td>'
    + '<td>'+esc(r.fund_type||'')+'</td>'
    + '<td>'+tokenCell(r.token||'')+'</td>'
    + '<td class="num">'+fmt(r.market_cap, 0)+'</td>'
    + '<td class="num">'+fmt(r.amount, 4)+'</td>'
    + '<td>'+fmtPct(r.portfolio_pct)+'</td>'
    + '<td class="num">'+fmt(r.entry_price_usd, 2)+'</td>'
    + '<td class="num">'+fmt(r.price_binance)+'</td>'
    + '<td class="num">'+fmt(r.price_bybit)+'</td>'
    + '<td class="num">'+fmt(r.price_okx)+'</td>'
    + '<td class="num">'+fmt(r.price_bingx)+'</td>'
    + '<td class="num">'+fmt(r.vol_3m)+'</td>'
    + '<td class="num">'+fmt(r.vol_6m)+'</td>'
    + '<td class="num">'+fmt(r.vol_9m)+'</td>'
    + '<td>'+fmtPct(r.chg_3m)+'</td>'
    + '<td>'+fmtPct(r.chg_6m)+'</td>'
    + '<td>'+fmtPct(r.chg_9m)+'</td>'
    + '<td>'+(r.held_since ? esc(r.held_since) : '<span class="na">н/д</span>')+'</td>'
    + '<td class="meta">'+esc(r.source||'')+'</td>'
    + '</tr>').join('');
}}
function renderLegend() {{
  const el = document.getElementById('legend');
  const tokens = Object.keys(COLORS).sort();
  el.innerHTML = tokens.map(t => {{
    const active = tokenFilter === t ? ' active' : '';
    return '<span class="chip'+active+'" data-tok="'+t+'"><span class="dot" style="background:'+COLORS[t]+'"></span>'+t+'</span>';
  }}).join('') + '<span class="chip" data-tok="">all</span>';
  el.querySelectorAll('.chip').forEach(ch => ch.onclick = () => {{
    tokenFilter = ch.getAttribute('data-tok') || '';
    renderLegend(); render();
  }});
}}
document.querySelectorAll('th[data-col]').forEach(th => {{
  th.onclick = () => {{
    const col = th.getAttribute('data-col');
    if (sortCol === col) sortDir *= -1;
    else {{ sortCol = col; sortDir = th.hasAttribute('data-num') ? -1 : 1; }}
    render();
  }};
}});
document.getElementById('q').oninput = render;
document.getElementById('typeFilter').onchange = render;
renderLegend();
render();
</script>
</body>
</html>
""".replace("{payload}", payload).replace("{colors_json}", colors_json)


def write_report(
    rows: list[dict[str, Any]],
    path: Path,
    title: str = "Crypto Funds Portfolio",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_html(rows, title=title), encoding="utf-8")
    return path
