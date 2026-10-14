"""Live orchestra kanban — persistent cards, workflow columns, hydrates from /api/kanban."""

from __future__ import annotations

from pathlib import Path

from agents.config import ROOT

OUT_HTML = ROOT / "out" / "kanban.html"

_HTML = r"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Оркестр · MUTE</title>
<style>
:root {
  --bg:#07080b; --panel:#10131a; --panel2:#161b26; --line:#252b38;
  --text:#e8eaed; --muted:#8b93a7; --accent:#7cb3ff; --ok:#3dd68c;
  --warn:#e6b84d; --danger:#f07178; --hand:#f0a36b;
  --mono:ui-monospace,Menlo,Consolas,monospace;
}
* { box-sizing:border-box; }
body { margin:0; font:14px/1.45 ui-sans-serif,system-ui,sans-serif; background:var(--bg); color:var(--text); }
header {
  display:flex; flex-wrap:wrap; gap:12px 18px; align-items:flex-start; justify-content:space-between;
  padding:14px 18px 12px; border-bottom:1px solid var(--line);
}
header h1 { margin:0; font-size:18px; font-weight:650; }
header .sub { color:var(--muted); font-size:12px; margin-top:4px; max-width:760px; }
.conductor {
  font:13px/1.4 var(--mono); color:#cfe0ff; background:#121826; border:1px solid #2a3a58;
  border-radius:10px; padding:8px 12px; margin:10px 18px 8px;
}
.players { display:flex; gap:8px; flex-wrap:wrap; }
.pill { font-size:11px; font-weight:700; padding:4px 9px; border-radius:999px; border:1px solid var(--line); color:var(--muted); cursor:pointer; background:transparent; }
.pill.on { color:var(--ok); border-color:rgba(61,214,140,.4); }
.pill.off { color:var(--muted); }
.pill.hand { color:var(--hand); border-color:rgba(240,163,107,.5); animation: pulse 1.8s ease-in-out infinite; }
.pill.active { color:#cfe0ff; border-color:#3a5080; background:#1a2740; }
@keyframes pulse { 50% { opacity:.55; } }
.board {
  display:grid; grid-template-columns:repeat(4,minmax(180px,1fr)); gap:10px;
  padding:0 18px 110px; align-items:start;
}
@media (max-width:1100px) { .board { grid-template-columns:repeat(2,1fr); } }
@media (max-width:620px) { .board { grid-template-columns:1fr; } }
.col { background:var(--panel); border:1px solid var(--line); border-radius:14px; min-height:48vh; padding:10px; }
.col.hand { border-color:rgba(240,163,107,.35); background:#14110e; }
.col.drag { outline:1px dashed var(--accent); }
.col-h { display:flex; justify-content:space-between; align-items:baseline; margin:0 0 8px; }
.col-h h2 { margin:0; font-size:12px; letter-spacing:.05em; text-transform:uppercase; color:var(--muted); }
.col-h .n { font:700 11px var(--mono); color:var(--accent); }
.card {
  background:var(--panel2); border:1px solid var(--line); border-radius:10px;
  padding:8px 10px; margin-bottom:8px; cursor:grab;
}
.card:active { cursor:grabbing; }
.card .top { display:flex; justify-content:space-between; gap:8px; font-size:11px; color:var(--muted); }
.card .kind { color:var(--accent); font-weight:650; }
.card .owner { font-weight:700; }
.card .title { margin:4px 0 0; font-size:13px; }
.card .detail { margin:4px 0 0; font-size:12px; color:var(--muted); }
.card.lv-ACT .kind, .card.lv-CRITICAL .kind { color:var(--danger); }
.card.lv-WATCH .kind { color:var(--warn); }
.card.hand-open { border-color:rgba(240,163,107,.45); }
.card.system { opacity:.92; }
.card .acts { display:flex; flex-wrap:wrap; gap:4px; margin-top:6px; }
button.ack, button.mv {
  appearance:none; border:1px solid var(--line); background:#1a2030;
  color:var(--text); border-radius:7px; padding:3px 7px; font:650 11px inherit; cursor:pointer;
}
button.ack { border-color:rgba(240,163,107,.5); background:#2a1c12; color:var(--hand); }
.empty { color:var(--muted); font-size:12px; padding:8px 2px; }
footer {
  position:fixed; left:0; right:0; bottom:0; display:flex; flex-wrap:wrap; gap:8px 12px;
  align-items:center; justify-content:space-between; padding:10px 16px;
  border-top:1px solid var(--line); background:rgba(7,8,11,.96); font-size:12px; color:var(--muted);
}
footer form { display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
footer input, footer select {
  background:var(--panel2); color:var(--text); border:1px solid var(--line);
  border-radius:8px; padding:6px 8px; font:inherit;
}
footer input { min-width:180px; }
footer a, footer button {
  appearance:none; border:1px solid var(--line); background:var(--panel2); color:var(--text);
  border-radius:8px; padding:6px 10px; font:inherit; font-weight:650; text-decoration:none; cursor:pointer;
}
.err { color:var(--danger); padding:12px 18px; }
</style>
</head>
<body>
<header>
  <div>
    <h1>Канбан</h1>
    <div class="sub">Картки — жива робота агентів, не стрічка логів. Колонки: черга → в роботі → рука (питання до тебе) → готово. Перетягни або кнопки. Рука після відповіді йде в роботу, не зникає.</div>
  </div>
  <div class="players" id="players"></div>
</header>
<div class="conductor" id="conductor">завантаження…</div>
<div class="board" id="board"></div>
<footer>
  <form id="addForm">
    <select id="addSrc" aria-label="агент">
      <option value="orch">орк</option>
      <option value="mute">збір</option>
      <option value="intel">звʼязки</option>
      <option value="rozvidka">патерни</option>
      <option value="trades">папір</option>
    </select>
    <input id="addTitle" type="text" maxlength="180" placeholder="нова картка в чергу" required/>
    <button type="submit">додати</button>
  </form>
  <nav>
    <span id="foot">● live</span>
    <button type="button" id="ackAll">опустити всі руки</button>
  </nav>
</footer>
<script>
const COLS = [
  {id:'backlog', label:'Черга'},
  {id:'doing', label:'В роботі'},
  {id:'hand', label:'Рука'},
  {id:'done', label:'Готово'},
];
const OWNER_UK = {mute:'збір', intel:'звʼязки', rozvidka:'патерни', trades:'папір', orch:'орк'};
let filterOwner = '';
let dragging = false;
let lastSig = '';
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function when(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d)) return esc(ts).slice(11,19);
  return d.toLocaleTimeString('uk-UA', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}
function cardHtml(c) {
  const lv = (c.level || '').toUpperCase();
  const st = c.status || c.col || '';
  const isHand = st === 'hand';
  const owner = c.src || c.owner || '';
  const acts = [];
  if (st !== 'backlog') acts.push(`<button class="mv" data-move="backlog" data-id="${esc(c.id)}">черга</button>`);
  if (st !== 'doing') acts.push(`<button class="mv" data-move="doing" data-id="${esc(c.id)}">в роботу</button>`);
  if (st !== 'hand') acts.push(`<button class="mv" data-move="hand" data-id="${esc(c.id)}">рука</button>`);
  if (st !== 'done') acts.push(`<button class="mv" data-move="done" data-id="${esc(c.id)}">готово</button>`);
  if (isHand) acts.push(`<button class="ack" data-ack="${esc(c.id)}">відповісти → в роботу</button>`);
  if (c.manual) acts.push(`<button class="mv" data-follow="${esc(c.id)}">жити з фактом</button>`);
  return `<article class="card ${lv ? 'lv-'+lv : ''} ${isHand ? 'hand-open' : ''} ${c.system ? 'system' : ''}" draggable="true" data-id="${esc(c.id)}">
    <div class="top">
      <span><span class="kind">${esc(c.kind || 'дія')}</span> · <span class="owner">${esc(OWNER_UK[owner] || owner)}</span>${c.system ? ' · факт' : ''}${c.manual ? ' · руками' : ''}</span>
      <span>${esc(when(c.ts))}</span>
    </div>
    <div class="title">${esc(c.title)}</div>
    ${c.detail ? `<div class="detail">${esc(c.detail)}</div>` : ''}
    ${c.ref ? `<div class="detail">${esc(c.ref)}</div>` : ''}
    <div class="acts">${acts.join('')}</div>
  </article>`;
}
async function api(body) {
  await fetch('/api/kanban', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  lastSig = '';
  refresh();
}
async function refresh() {
  if (dragging) return;
  try {
    const r = await fetch('/api/kanban?ts=' + Date.now(), {cache:'no-store'});
    const d = await r.json();
    const sig = JSON.stringify({c:d.counts, h:d.open_hands, t:d.conductor, o:filterOwner, cols:d.columns});
    if (sig === lastSig) {
      document.getElementById('foot').textContent = 'оновлено ' + when(d.ts);
      return;
    }
    lastSig = sig;
    document.getElementById('conductor').textContent = d.conductor || '';
    const pl = d.players || {};
    const pills = ['mute','intel','rozvidka'].map(id => {
      const p = pl[id] || {};
      const on = filterOwner === id ? ' active' : '';
      return `<button type="button" class="pill ${p.running ? 'on' : 'off'}${on}" data-owner="${id}">${esc(p.role || id)} ${p.running ? 'грає' : 'тиша'}</button>`;
    }).join('') + `<button type="button" class="pill ${(d.orch && d.orch.running) ? 'on' : 'off'}${filterOwner==='orch'?' active':''}" data-owner="orch">диригент ${(d.orch && d.orch.running) ? 'веде' : 'мовчить'}</button>`
      + `<button type="button" class="pill${filterOwner==='trades'?' active':''}" data-owner="trades">папір</button>`
      + (d.open_hands ? `<span class="pill hand">рук ${d.open_hands}</span>` : '')
      + (filterOwner ? `<button type="button" class="pill active" data-owner="">усі</button>` : '');
    document.getElementById('players').innerHTML = pills;
    const cols = d.columns || {};
    document.getElementById('board').innerHTML = COLS.map(def => {
      let items = cols[def.id] || [];
      if (filterOwner) items = items.filter(c => (c.src || c.owner) === filterOwner);
      const body = items.length ? items.map(cardHtml).join('') : `<div class="empty">порожньо</div>`;
      return `<section class="col ${def.id === 'hand' ? 'hand' : ''}" data-col="${def.id}">
        <div class="col-h"><h2>${def.label}</h2><span class="n">${items.length}</span></div>
        ${body}
      </section>`;
    }).join('');
    bindBoard();
    document.getElementById('foot').textContent = 'оновлено ' + when(d.ts) + (d.open_hands ? ' · рук ' + d.open_hands : '');
  } catch (e) {
    document.getElementById('conductor').innerHTML = '<span class="err">немає /api/kanban — запустіть dashboard</span>';
  }
}
function bindBoard() {
  const board = document.getElementById('board');
  board.onclick = (e) => {
    const ack = e.target.closest('[data-ack]');
    if (ack) { api({op:'ack', id: ack.getAttribute('data-ack')}); return; }
    const follow = e.target.closest('[data-follow]');
    if (follow) { api({op:'follow', id: follow.getAttribute('data-follow')}); return; }
    const mv = e.target.closest('[data-move]');
    if (mv) { api({op:'move', id: mv.getAttribute('data-id'), status: mv.getAttribute('data-move')}); return; }
    const own = e.target.closest('[data-owner]');
    if (own) { filterOwner = own.getAttribute('data-owner') || ''; lastSig=''; refresh(); }
  };
  board.querySelectorAll('.card').forEach(el => {
    el.addEventListener('dragstart', ev => {
      dragging = true;
      ev.dataTransfer.setData('text/plain', el.getAttribute('data-id'));
      ev.dataTransfer.effectAllowed = 'move';
    });
    el.addEventListener('dragend', () => { dragging = false; });
  });
  board.querySelectorAll('.col').forEach(col => {
    col.addEventListener('dragover', ev => { ev.preventDefault(); col.classList.add('drag'); });
    col.addEventListener('dragleave', () => col.classList.remove('drag'));
    col.addEventListener('drop', ev => {
      ev.preventDefault();
      col.classList.remove('drag');
      dragging = false;
      const id = ev.dataTransfer.getData('text/plain');
      const status = col.getAttribute('data-col');
      if (id && status) api({op:'move', id, status});
    });
  });
}
document.getElementById('players').onclick = (e) => {
  const own = e.target.closest('[data-owner]');
  if (own) { filterOwner = own.getAttribute('data-owner') || ''; lastSig=''; refresh(); }
};
document.getElementById('ackAll').onclick = () => api({op:'ack_all'});
document.getElementById('addForm').onsubmit = (e) => {
  e.preventDefault();
  const title = document.getElementById('addTitle').value.trim();
  if (!title) return;
  api({op:'add', src: document.getElementById('addSrc').value, title, status:'backlog'});
  document.getElementById('addTitle').value = '';
};
refresh();
setInterval(refresh, 2500);
</script>
</body>
</html>
"""


def write_ui(path: Path | None = None) -> str:
    path = path or OUT_HTML
    path.parent.mkdir(parents=True, exist_ok=True)
    from agents.chrome import apply_to_html

    path.write_text(apply_to_html(_HTML, "kanban"), encoding="utf-8")
    return str(path)
