"""Live HTML UI — EN/UK + full cycle / health / queue display."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from intel.config import OUT_HTML


def write_ui(snapshot: dict[str, Any]) -> Path:
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, default=str)
    html = f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Intel · MUTE</title>
<style>
:root {{
  --bg:#0f1419; --panel:#1a222c; --text:#e7ecf1; --muted:#8b9aab;
  --accent:#3d9cf0; --ok:#3ecf8e; --bad:#e85d5d; --warn:#e6b84d; --line:#2a3542;
  --font: "IBM Plex Sans", "Segoe UI", sans-serif;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:var(--font); background:linear-gradient(160deg,#0f1419,#15202b 45%,#0f1419);
  color:var(--text); min-height:100vh; padding-bottom:4.5rem; }}
header {{ padding:1.1rem 1.4rem; border-bottom:1px solid var(--line);
  display:flex; flex-wrap:wrap; gap:1rem; align-items:baseline; justify-content:space-between;
  position:relative; }}
h1 {{ margin:0; font-size:1.55rem; }}
.sub,.mini {{ color:var(--muted); font-size:.9rem; }}
.pills {{ display:flex; flex-wrap:wrap; gap:.35rem; }}
.pill {{ background:var(--panel); border:1px solid var(--line); padding:.22rem .55rem; font-size:.72rem; color:var(--muted); }}
.pill.ok {{ color:var(--ok); border-color:#2a5; }}
.pill.bad {{ color:var(--bad); }}
.pill.warn {{ color:var(--warn); }}
.tabs {{ display:flex; gap:.4rem; padding:.8rem 1.4rem 0; flex-wrap:wrap; }}
.tab {{ background:transparent; border:1px solid var(--line); color:var(--muted); padding:.4rem .8rem; cursor:pointer; }}
.tab.on {{ color:var(--text); border-color:var(--accent); }}
main {{ padding:1rem 1.4rem; }}
.panel {{ display:none; }}
.panel.on {{ display:block; }}
.grid {{ display:grid; grid-template-columns:1.15fr 1fr; gap:1rem; }}
@media (max-width:960px) {{ .grid {{ grid-template-columns:1fr; }} }}
.box {{ background:var(--panel); border:1px solid var(--line); padding:1rem; margin-bottom:1rem; }}
.box h3 {{ margin:0 0 .55rem; font-size:.78rem; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }}
ul {{ margin:0; padding:0; list-style:none; }}
li {{ padding:.32rem 0; border-bottom:1px solid var(--line); font-size:.88rem; }}
pre {{ margin:0; white-space:pre-wrap; word-break:break-word; font-size:.75rem; color:var(--muted); }}
.kpi {{ font-size:1.6rem; font-weight:600; }}
footer {{ position:fixed; bottom:0; left:0; right:0; background:#0c1015f2;
  border-top:1px solid var(--line); padding:.55rem 1rem; display:flex; gap:.45rem; flex-wrap:wrap; align-items:center; }}
button {{ background:var(--accent); color:#041018; border:0; padding:.45rem .85rem; font-weight:600; cursor:pointer; }}
button.ghost {{ background:transparent; color:var(--text); border:1px solid var(--line); }}
button.danger {{ background:var(--bad); color:#fff; }}
.lang {{ margin-left:auto; }}
</style>
</head>
<body>
<header>
  <div>
    <h1 id="title">Intel</h1>
    <div class="sub" id="sub"></div>
    <div class="mini" id="goal"></div>
  </div>
  <div class="pills" id="pills"></div>
</header>
<div class="tabs">
  <button class="tab on" data-tab="cycles">Cycles / Цикли</button>
  <button class="tab" data-tab="families">Families / Сімʼї</button>
  <button class="tab" data-tab="signals">Signals / Сигнали</button>
  <button class="tab" data-tab="queue">Queue / Черга</button>
</div>
<main>
  <div class="panel on" id="tab-cycles">
    <div class="grid">
      <div>
        <div class="box"><h3>health</h3><div class="kpi" id="hStatus">—</div><div class="mini" id="hMeta"></div><ul id="hIssues"></ul></div>
        <div class="box"><h3>cycle history / історія циклів</h3><ul id="hist"></ul></div>
      </div>
      <div>
        <div class="box"><h3>session / сесія</h3><pre id="session"></pre></div>
        <div class="box"><h3>last cycle / останній цикл</h3><pre id="lastc"></pre></div>
        <div class="box"><h3>errors</h3><ul id="errs"></ul></div>
      </div>
    </div>
  </div>
  <div class="panel" id="tab-families">
    <div class="grid">
      <div class="box"><h3 id="h-fam">families</h3><ul id="fam"></ul></div>
      <div class="box"><h3>shared tokens</h3><ul id="tok"></ul></div>
    </div>
  </div>
  <div class="panel" id="tab-signals">
    <div class="grid">
      <div class="box"><h3 id="h-pre">pre-pump</h3><ul id="pre"></ul></div>
      <div class="box"><h3 id="h-spk">spikes</h3><ul id="spk"></ul></div>
    </div>
  </div>
  <div class="panel" id="tab-queue">
    <div class="box"><h3>queue preview / черга</h3><ul id="qlist"></ul></div>
    <div class="box"><h3>stats by chain</h3><pre id="stats"></pre></div>
  </div>
</main>
<footer>
  <button type="button" id="btn-once">cycle once</button>
  <button type="button" id="btn-start">start 12h</button>
  <button type="button" class="danger" id="btn-stop">stop</button>
  <button type="button" class="ghost" id="btn-refresh">refresh</button>
  <span class="lang">
    <button type="button" class="ghost" data-lang="uk">UK</button>
    <button type="button" class="ghost" data-lang="en">EN</button>
  </span>
</footer>
<script>
const BOOT = {payload};
let snap = BOOT;
let lang = (BOOT.lang || 'uk');

function esc(s) {{
  return String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}
function i18n(key) {{
  const pack = (snap.i18n || {{}})[lang] || {{}};
  return pack[key] || key;
}}
function fmtSec(s) {{
  if (s == null) return '—';
  s = Math.max(0, Number(s));
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h + 'h ' + m + 'm';
}}
function statusClass(st) {{
  if (st === 'ok') return 'ok';
  if (st === 'stale' || st === 'interrupted') return 'warn';
  return 'bad';
}}
function render() {{
  document.getElementById('title').textContent = i18n('name');
  document.getElementById('sub').textContent = i18n('subtitle');
  document.getElementById('goal').textContent = i18n('goal');
  const h = snap.health || {{}};
  const s = snap.state || {{}};
  const st = snap.stats || {{}};
  document.getElementById('pills').innerHTML = `
    <span class="pill ${{statusClass(h.cycle_status)}}">cycle: ${{esc(h.cycle_status)}}</span>
    <span class="pill ${{h.running ? 'ok' : 'bad'}}">${{h.running ? i18n('collect_running') : i18n('collect_off')}}</span>
    <span class="pill">${{esc(i18n('cycle'))}} ${{esc(h.cycle ?? s.cycle ?? 0)}}</span>
    <span class="pill">${{esc(i18n('queue'))}} ${{esc(h.queue ?? s.queue ?? 0)}}</span>
    <span class="pill">in_flight ${{esc(h.in_flight ?? s.in_flight ?? 0)}}</span>
    <span class="pill">${{esc(i18n('addresses'))}} ${{esc(st.addresses ?? 0)}}</span>
    <span class="pill">${{esc(i18n('edges'))}} ${{esc(st.edges ?? 0)}}</span>
    <span class="pill">${{esc(i18n('families'))}} ${{esc(st.families ?? 0)}}</span>
    <span class="pill">left ${{esc(fmtSec(h.remaining_sec))}}</span>
    <span class="pill">BNB ${{(snap.flags||{{}}).bnb?'on':'off'}}</span>
    <span class="pill">SOL ${{(snap.flags||{{}}).sol?'on':'off'}}</span>
  `;
  document.getElementById('hStatus').textContent = (h.cycle_status || '—').toUpperCase();
  document.getElementById('hMeta').textContent =
    `pid ${{h.pid ?? '—'}} · hb age ${{h.heartbeat_age_sec ?? '—'}}s · stale>${{h.stale_after_sec ?? 600}}s · sessions ${{h.sessions_n ?? 0}}`;
  document.getElementById('hIssues').innerHTML = (h.issues || []).length
    ? (h.issues || []).map(i => `<li>${{esc(i)}}</li>`).join('')
    : `<li class="mini">ok</li>`;
  const hist = snap.cycles || [];
  document.getElementById('hist').innerHTML = hist.length
    ? hist.slice(0,20).map(c => `<li>#${{esc(c.cycle)}} · ${{esc(c.elapsed)}}s · +edges ${{esc(c.edges_new)}} · q ${{esc(c.queue)}} · fam ${{esc(c.families)}}
        <div class="mini">${{esc((c.chains||[]).join(','))}} · prep ${{esc(c.prepump_n)}} · spike ${{esc(c.spike_n)}} · ${{esc(c.ts||'')}}</div></li>`).join('')
    : `<li class="mini">—</li>`;
  document.getElementById('session').textContent = JSON.stringify({{
    started: s.collect_started_at, until: s.collect_until, finished: s.collect_finished_at,
    interrupted: s.collect_interrupted, remaining: fmtSec(h.remaining_sec),
    sessions: s.sessions, last_session: h.last_session
  }}, null, 2);
  document.getElementById('lastc').textContent = JSON.stringify(s.last_cycle || h.last_cycle || {{}}, null, 2);
  document.getElementById('errs').innerHTML = (s.errors || []).length
    ? (s.errors || []).map(e => `<li>${{esc(e)}}</li>`).join('')
    : `<li class="mini">—</li>`;
  const fam = snap.families || [];
  document.getElementById('fam').innerHTML = fam.length
    ? fam.map(f => `<li><b>${{esc(f.short)}}</b> [${{esc(f.chain)}}] · ${{esc(f.size)}} · tok×${{esc(f.token_n)}}
        <div class="mini">${{esc(((f.move||{{}}).move_uk)||'')}} · ${{esc(((f.move||{{}}).where||{{}}).hint||'')}} · патрон ${{esc(((f.patron||{{}}).short)||'—')}} · рамки ${{esc(((f.frames||{{}}).status)||'—')}}</div>
        <div class="mini">${{(f.tokens||[]).slice(0,5).map(esc).join(', ')}}</div></li>`).join('')
    : `<li class="mini">—</li>`;
  document.getElementById('tok').innerHTML = (snap.shared_tokens||[]).length
    ? (snap.shared_tokens||[]).slice(0,12).map(t => `<li>${{esc(t.token)}} · ${{esc(t.n)}} fam</li>`).join('')
    : `<li class="mini">—</li>`;
  document.getElementById('pre').innerHTML = (snap.prepump||[]).length
    ? (snap.prepump||[]).slice(0,12).map(p => `<li><b>${{esc(p.short)}}</b> sc ${{esc(p.score)}} · ×${{esc(p.token_n)}}
        <div class="mini">${{(p.tokens||[]).slice(0,6).map(esc).join(', ')}}</div></li>`).join('')
    : `<li class="mini">—</li>`;
  document.getElementById('spk').innerHTML = (snap.spikes||[]).length
    ? (snap.spikes||[]).slice(0,12).map(x => `<li>[${{esc(x.chain)}}] <b>${{esc(x.symbol)}}</b> tx=${{esc(x.tx)}} uniq=${{esc(x.unique)}}</li>`).join('')
    : `<li class="mini">—</li>`;
  document.getElementById('qlist').innerHTML = (snap.queue_preview||[]).length
    ? (snap.queue_preview||[]).map(q => `<li>[${{esc(q.chain)}}] ${{esc(q.address)}} · hop ${{esc(q.hop)}} · ${{esc(q.reason)}} · p${{esc(q.priority)}}</li>`).join('')
    : `<li class="mini">—</li>`;
  document.getElementById('stats').textContent = JSON.stringify({{stats: st, by_chain: st.by_chain, flags: snap.flags}}, null, 2);
}}
document.querySelectorAll('.tab').forEach(b => b.onclick = () => {{
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('on'));
  document.querySelectorAll('.panel').forEach(x => x.classList.remove('on'));
  b.classList.add('on');
  document.getElementById('tab-' + b.dataset.tab).classList.add('on');
}});
async function act(action) {{
  try {{
    await fetch('/api/action', {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{action}})}});
  }} catch(e) {{}}
  setTimeout(refresh, 1200);
}}
async function refresh() {{
  try {{
    const r = await fetch('/api/intel?ts=' + Date.now());
    if (r.ok) snap = await r.json();
  }} catch (e) {{}}
  render();
}}
document.querySelectorAll('[data-lang]').forEach(b => b.onclick = () => {{ lang = b.dataset.lang; render(); }});
document.getElementById('btn-refresh').onclick = refresh;
document.getElementById('btn-once').onclick = () => act('intel_once');
document.getElementById('btn-start').onclick = () => act('start_intel');
document.getElementById('btn-stop').onclick = () => act('stop_intel');
render();
setInterval(refresh, 8000);
</script>
</body>
</html>
"""
    from agents.chrome import apply_to_html

    OUT_HTML.write_text(apply_to_html(html, "intel"), encoding="utf-8")
    (OUT_HTML.parent / "intel_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return OUT_HTML
