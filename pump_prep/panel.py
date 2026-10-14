"""Build the static control panel HTML with embedded ACT/WATCH + cycles snapshot.

Bilingual (EN default / UK toggle) — text comes from pump_prep.i18n_ui.UI.
"""

from __future__ import annotations

import html as html_mod
import json
from typing import Any

from pump_prep.config import ROOT
from pump_prep.cycles import check_cycle_health, signal_board, write_cycles_json
from pump_prep import graph_store as gs
from pump_prep.signals import MIN_SCORE, WATCH_SCORE
from pump_prep.i18n_ui import DEFAULT_LANG, STORAGE_KEY, UI, normalize_lang, packs_json, t
from agents.chrome import CSS as CHROME_CSS, html as chrome_nav

OUT = ROOT / "out"


def _esc(x: Any) -> str:
    return html_mod.escape("" if x is None else str(x))


def _tip(lang: str, key: str, **fmt: Any) -> str:
    """Escaped tooltip text; newlines become HTML breaks for [data-tip]::after."""
    return _esc(t(lang, key, **fmt)).replace("\n", "&#10;")


# ---------------------------------------------------------------------------
# Static CSS (fully language-independent — no substitutions needed)
# ---------------------------------------------------------------------------
_STYLE = """
:root {
  --bg:#0c0e12; --panel:#151922; --panel2:#1b2030; --text:#e8eaed; --muted:#9aa0a6;
  --line:#2a2f3a; --accent:#7cb3ff; --ok:#3dd68c; --warn:#e6b84d; --danger:#f07178;
  --header-h: 84px;
}
* { box-sizing:border-box; }
body { margin:0; font:14px/1.45 ui-sans-serif,system-ui,sans-serif; background:var(--bg); color:var(--text); }
html { scroll-padding-top: var(--chrome-h, var(--header-h, 84px)); }
header {
  padding:12px 20px 10px; border-bottom:1px solid var(--line);
  background:transparent; position:relative; z-index:1;
}
.header-top { display:flex; flex-wrap:nowrap; gap:10px 16px; align-items:center; justify-content:space-between; padding-bottom:8px; min-height:40px; }
.header-copy { min-width:0; flex:1; }
h1 { margin:0 0 4px; font-size:20px; font-weight:650; }
h2 { margin:0 0 12px; font-size:15px; font-weight:650; letter-spacing:.02em; text-transform:uppercase; color:var(--muted); }
h3 { margin:0 0 8px; font-size:16px; }
.meta { color:var(--muted); font-size:13px; }
.header-copy .meta { display:none; }
@media (min-width:900px) { .header-copy .meta { display:block; margin:0; } }
.badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:650; margin-left:8px; vertical-align:middle; }
.badge-on { background:rgba(61,214,140,.2); color:var(--ok); }
.badge-off { background:rgba(240,113,120,.15); color:var(--danger); }
.badge-wait { background:rgba(230,184,77,.15); color:var(--warn); }
.lang-toggle { display:flex; gap:6px; align-items:center; flex:0 0 auto; }
.lang-btn { padding:6px 10px; font-size:12px; font-weight:700; }
.lang-btn.active { background:#243044; border-color:#3a5080; color:#cfe0ff; }
nav.menu {
  display:flex; flex-direction:column; gap:0; align-items:stretch;
  padding:0 0 8px; border-top:1px solid var(--line); margin:0;
  overflow:visible;
}
.menu-row {
  display:flex; flex-wrap:wrap; gap:4px; align-items:center;
  padding:6px 0 2px;
}
.menu-row.menu-pages { padding:6px 0 2px; border-top:1px solid var(--line); }
nav.menu a {
  color:var(--muted); text-decoration:none; font-size:12px; font-weight:650;
  padding:6px 10px; border-radius:8px; border:1px solid transparent; white-space:nowrap;
  flex:0 0 auto;
}
nav.menu a:hover { color:var(--text); background:var(--panel2); border-color:var(--line); }
nav.menu a.active { color:#cfe0ff; background:#243044; border-color:#3a5080; }
nav.menu .sep { width:1px; height:18px; background:var(--line); margin:0 4px; flex:0 0 auto; }
nav.menu .grp { color:#6b7280; font-size:10px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; margin:0 2px 0 6px; flex:0 0 auto; white-space:nowrap; }
@media (max-width:720px) {
  nav.menu .grp, nav.menu .sep { display:none; }
}
main { padding:18px 24px 56px; max-width:1180px; }
section { margin-bottom:26px; scroll-margin-top: var(--header-h, 128px); }
.grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); }
.grid-2 { display:grid; gap:14px; grid-template-columns:1fr 1fr; }
@media (max-width:900px) { .grid-2 { grid-template-columns:1fr; } }
.card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; }
.proc-board { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:0; overflow:hidden; }
.proc-board .proc-head {
  display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; justify-content:space-between;
  padding:14px 16px; border-bottom:1px solid var(--line); background:var(--panel2);
}
.proc-board .proc-head h3 { margin:0; font-size:15px; }
.proc-summary { font-size:13px; color:var(--muted); }
.proc-summary b.on { color:var(--ok); }
.proc-summary b.off { color:var(--danger); }
.proc-table { width:100%; border-collapse:collapse; font-size:13px; }
.proc-table th, .proc-table td { padding:11px 14px; text-align:left; border-bottom:1px solid var(--line); vertical-align:middle; }
.proc-table th { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; font-weight:700; background:rgba(0,0,0,.15); }
.proc-table tr:last-child td { border-bottom:none; }
.proc-table tr:hover td { background:rgba(124,179,255,.04); }
.proc-name { font-weight:700; font-size:14px; white-space:nowrap; }
.proc-role { color:var(--muted); font-size:12px; max-width:280px; }
.proc-detail { color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; }
.proc-link a { color:var(--accent); text-decoration:none; font-weight:650; font-size:12px; }
.proc-link a:hover { text-decoration:underline; }
.proc-dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; vertical-align:middle; }
.proc-dot.on { background:var(--ok); box-shadow:0 0 0 3px rgba(61,214,140,.2); }
.proc-dot.off { background:var(--danger); }
.proc-dot.wait { background:var(--warn); }
@media (max-width:720px) {
  .proc-table .col-role, .proc-table .col-link { display:none; }
}
.proc-ctrl { white-space:nowrap; }
.proc-ctrl button { padding:4px 8px; font-size:11px; min-width:32px; }
.live-panel { min-height:220px; }
.live-head { display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; justify-content:space-between; margin-bottom:10px; }
.live-kpis { display:flex; flex-wrap:wrap; gap:8px 14px; font-size:12px; color:var(--muted); margin-bottom:10px; }
.live-kpis b { color:var(--text); font-weight:650; }
.live-list { font-size:12px; color:var(--muted); max-height:140px; overflow:auto; }
.live-list li { margin:3px 0; font-family:ui-monospace,Menlo,monospace; }
.live-empty { color:var(--muted); font-size:12px; padding:8px 0; }
.wiki-grid { display:grid; gap:8px; }
@media (min-width:900px) { .wiki-grid { grid-template-columns:1fr 1fr; } }
.wiki-card { border:1px solid var(--line); border-radius:10px; padding:10px 12px; background:var(--panel2); }
.wiki-card.go { border-color:rgba(61,214,140,.4); }
.wiki-card.submit { border-color:rgba(230,184,77,.35); }
.wiki-card.hand { border-color:rgba(240,163,107,.4); }
.wiki-card .mv { font-size:11px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; color:var(--muted); }
.wiki-card.go .mv { color:var(--ok); }
.wiki-card.submit .mv { color:var(--warn); }
.wiki-card .title { font-weight:650; margin:4px 0; }
a.report.missing { opacity:.45; border-style:dashed; }
a.report .rep-st { float:right; font-size:11px; color:var(--muted); font-weight:700; }
.ctrl-grid { display:grid; gap:10px; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); }
.ctrl-grid button { width:100%; }
.sig-meta-grid {
  display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
  gap:4px 10px; margin:8px 0 4px; font-size:11px; color:var(--muted);
}
.sig-meta-grid b { color:var(--text); font-weight:650; }
.sig-kpis {
  display:flex; flex-wrap:wrap; gap:10px 14px; margin:0 0 14px; padding:12px 14px;
  background:var(--panel); border:1px solid var(--line); border-radius:10px; font-size:13px;
}
.sig-kpis .kpi-mini { font-size:20px; font-weight:700; line-height:1.1; }
.sig-kpis .kpi-mini small { display:block; font-size:11px; color:var(--muted); font-weight:600; text-transform:uppercase; }
.sig-table-wrap { overflow-x:auto; margin-top:14px; border:1px solid var(--line); border-radius:10px; background:var(--panel); }
.sig-table { width:100%; border-collapse:collapse; font-size:12px; min-width:960px; }
.sig-table th, .sig-table td { padding:8px 10px; text-align:left; border-bottom:1px solid var(--line); vertical-align:top; }
.sig-table th { color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.04em; background:rgba(0,0,0,.2); position:sticky; top:0; }
.sig-table tr:hover td { background:rgba(124,179,255,.04); }
.sig-table .col-why { max-width:280px; color:var(--muted); font-size:11px; }
.sig-table .tier-pill { font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px; }
.sig-table .tier-act { background:rgba(61,214,140,.2); color:var(--ok); }
.sig-table .tier-watch { background:rgba(230,184,77,.18); color:var(--warn); }
.board .sig-list { max-height:70vh; overflow:auto; padding-right:4px; }
.row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
button, .btn {
  appearance:none; border:1px solid var(--line); background:var(--panel2); color:var(--text);
  border-radius:8px; padding:8px 12px; font:inherit; font-weight:600; cursor:pointer; text-decoration:none; display:inline-block;
}
button:hover, .btn:hover { border-color:var(--accent); }
button.primary { background:#243044; border-color:#3a5080; color:#cfe0ff; }
button.ok { background:rgba(61,214,140,.12); border-color:rgba(61,214,140,.35); color:var(--ok); }
button.danger { background:rgba(240,113,120,.12); border-color:rgba(240,113,120,.35); color:var(--danger); }
.status-line { font-size:12px; color:var(--muted); margin-top:10px; font-family:ui-monospace,Menlo,monospace; white-space:pre-wrap; }
.pbar { height:12px; background:#222833; border-radius:6px; overflow:hidden; margin:10px 0 6px; }
.pbar > i { display:block; height:100%; background:var(--ok); width:0%; }
.warnbox { background:rgba(230,184,77,.08); border:1px solid rgba(230,184,77,.25); color:#e8d59a; border-radius:10px; padding:10px 12px; font-size:13px; margin-bottom:14px; }
.okbox { background:rgba(61,214,140,.08); border:1px solid rgba(61,214,140,.25); color:#b7f0d0; border-radius:10px; padding:10px 12px; font-size:13px; margin-bottom:14px; }
.board { border-radius:12px; border:1px solid var(--line); padding:14px; background:var(--panel); min-height:180px; max-height:none; }
.board.act { border-color:rgba(61,214,140,.45); }
.board.watch { border-color:rgba(230,184,77,.45); }
.board h3 .n { color:var(--muted); font-weight:500; font-size:13px; }
.sig { border:1px solid var(--line); border-radius:10px; padding:10px 12px; margin-top:8px; background:var(--panel2); }
.sig.go { background:rgba(61,214,140,.08); }
.sig.wa { background:rgba(230,184,77,.06); }
.sig-top { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:4px; }
.tier { font-size:11px; font-weight:700; padding:2px 8px; border-radius:6px; }
.sig.go .tier { background:rgba(61,214,140,.2); color:var(--ok); }
.sig.wa .tier { background:rgba(230,184,77,.18); color:var(--warn); }
.money { font-size:11px; font-weight:700; padding:2px 8px; border-radius:6px; background:rgba(124,179,255,.14); color:var(--accent); }
.filters { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:0 0 14px; padding:10px 12px; background:var(--panel); border:1px solid var(--line); border-radius:10px; }
.filters label { color:var(--muted); font-size:12px; font-weight:650; }
.filters select, .filters input {
  background:var(--panel2); color:var(--text); border:1px solid var(--line); border-radius:8px;
  padding:6px 10px; font:inherit; font-size:13px;
}
.filters .hint { color:var(--muted); font-size:11px; }
.why { margin:4px 0 0; padding-left:16px; color:var(--muted); font-size:12px; }
.empty { color:var(--muted); font-size:13px; padding:12px 0; }
.kpi { font-size:28px; font-weight:700; }
.kpi small { font-size:13px; color:var(--muted); font-weight:500; }
a.report { display:block; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; text-decoration:none; color:inherit; }
a.report:hover { border-color:var(--accent); }
.tag { display:inline-block; font-size:10px; font-weight:650; padding:2px 7px; border-radius:999px; margin-bottom:8px; }
.t1 { background:rgba(61,214,140,.18); color:var(--ok); }
.t2 { background:rgba(240,113,120,.18); color:var(--danger); }
.t3 { background:rgba(124,179,255,.15); color:var(--accent); }
.t4 { background:rgba(230,184,77,.15); color:var(--warn); }
#toast { position:fixed; right:16px; bottom:16px; max-width:420px; background:var(--panel2); border:1px solid var(--line); border-radius:10px; padding:12px 14px; display:none; z-index:20; font-size:13px; white-space:pre-wrap; }
[data-tip] { position:relative; cursor:help; border-bottom:1px dotted rgba(154,160,166,.45); }
.help[data-tip], .badge[data-tip], button[data-tip], a[data-tip] { border-bottom:none; }
[data-tip]::after {
  content: attr(data-tip); position:absolute; left:0; top:calc(100% + 8px); z-index:120;
  min-width:200px; max-width:320px; padding:10px 12px; border-radius:8px;
  background:#0b0d12; color:#d7dbe2; border:1px solid #3a4252; font-size:12px; font-weight:400; line-height:1.45;
  opacity:0; pointer-events:none; white-space:pre-line; box-shadow:0 8px 24px rgba(0,0,0,.45);
}
[data-tip].tip-right::after { left:auto; right:0; }
nav.menu a[data-tip]::after { display:none; }
[data-tip]:hover::after, [data-tip]:focus::after { opacity:1; }
.help { display:inline-flex; width:16px; height:16px; align-items:center; justify-content:center; border-radius:50%; border:1px solid var(--line); color:var(--muted); font-size:11px; font-weight:700; margin-left:6px; cursor:help; vertical-align:middle; }
ul.issues { margin:6px 0 0; padding-left:18px; color:var(--muted); font-size:12px; }
.snap-note { font-size:11px; color:var(--muted); margin-top:8px; }
.gloss { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; margin-bottom:22px; }
.gloss summary { cursor:pointer; font-weight:650; color:var(--text); list-style:none; }
.gloss summary::-webkit-details-marker { display:none; }
.gloss summary::before { content:"\\25B8 "; color:var(--accent); }
.gloss[open] summary::before { content:"\\25BE "; }
.gloss dl { display:grid; grid-template-columns:minmax(110px,160px) 1fr; gap:8px 14px; margin:12px 0 0; }
.gloss dt { color:var(--accent); font-weight:650; font-size:12px; }
.gloss dd { margin:0; color:var(--muted); font-size:12px; line-height:1.45; }
@media (max-width:720px) { .gloss dl { grid-template-columns:1fr; gap:2px 0; } .gloss dt { margin-top:6px; } }
.term { cursor:help; border-bottom:1px dotted rgba(154,160,166,.5); }
.btn-hint { display:block; color:var(--muted); font-size:11px; margin-top:8px; line-height:1.4; }
"""
_STYLE = _STYLE + CHROME_CSS

# ---------------------------------------------------------------------------
# JS — templated with @@TOKEN@@ placeholders substituted after the fact, so
# none of the (many) literal braces below need doubling.
# ---------------------------------------------------------------------------
_SCRIPT = """
const SNAP = @@SNAP_JSON@@;
const I18N = @@I18N_JSON@@;
const LANG_KEY = '@@LANG_KEY@@';
const DEFAULT_LANG = '@@DEFAULT_LANG@@';
let currentLang = DEFAULT_LANG;

const API = (() => {
  if (location.protocol.startsWith('http') && /^(127\\.0\\.0\\.1|localhost)$/i.test(location.hostname)) return '';
  return 'http://127.0.0.1:8765';
})();

function normalizeLang(v) {
  v = (v || '').toLowerCase().trim();
  if (['ua', 'ukr', 'украинский', 'українська'].includes(v)) return 'uk';
  if (I18N[v]) return v;
  return DEFAULT_LANG;
}

function t(key, fmt) {
  const pack = I18N[currentLang] || I18N[DEFAULT_LANG] || {};
  let s = pack[key] || (I18N[DEFAULT_LANG] && I18N[DEFAULT_LANG][key]) || key;
  if (fmt) {
    s = s.replace(/\\{(\\w+)\\}/g, (m, k) => (fmt[k] !== undefined ? fmt[k] : m));
  }
  return s;
}

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.style.display = 'block';
  clearTimeout(toast._t); toast._t = setTimeout(() => el.style.display = 'none', 5000);
}
function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function setBadge(id, on) {
  const el = document.getElementById(id); if (!el) return;
  el.textContent = on ? 'on' : 'off';
  el.className = 'badge ' + (on ? 'badge-on' : 'badge-off');
}

function fmtAge(ts, saved) {
  let t = ts || saved;
  if (!t) return '\\u2014';
  if (typeof t === 'string' && t.includes('T')) {
    t = Date.parse(t) / 1000;
  }
  t = Number(t);
  if (!t || Number.isNaN(t)) return '\\u2014';
  // ms vs sec
  if (t > 1e12) t = t / 1000;
  const sec = Math.max(0, Date.now() / 1000 - t);
  if (sec < 3600) return Math.round(sec / 60) + 'm';
  if (sec < 86400) return (sec / 3600).toFixed(1) + 'h';
  return (sec / 86400).toFixed(1) + 'd';
}
function shortHash(h) {
  if (!h) return '\\u2014';
  const s = String(h);
  return s.length > 14 ? s.slice(0, 8) + '\\u2026' + s.slice(-4) : s;
}
function renderCards(rows, kind) {
  const KIND_TIP = {
    expand_hit: t('kind_expand_hit'),
    hop_chain: t('kind_hop_chain'),
    fresh_hop: t('kind_fresh_hop'),
    bridge_hop: t('kind_bridge_hop'),
    cex_deposit: t('kind_cex_deposit'),
    cex_touch: t('kind_cex_touch'),
    seed_touch: t('kind_seed_touch'),
    mm_touch: t('kind_mm_touch'),
    prep_live: t('kind_prep_live'),
    new_token_in: t('kind_prep_live'),
  };
  const title = kind === 'act' ? t('act_title') : t('watch_title');
  if (!rows || !rows.length) return '<div class="empty">' + escapeHtml(t('empty_filter', { kind: title })) + '</div>';
  return rows.map(s => {
    const reasons = (currentLang === 'uk' && s.reasons_uk && s.reasons_uk.length) ? s.reasons_uk : (s.reasons || []);
    const summary = (currentLang === 'uk' && s.summary_uk) ? s.summary_uk : (s.summary || '');
    const why = reasons.map(r => '<li>' + escapeHtml(r) + '</li>').join('') || '<li>\\u2014</li>';
    const cls = kind === 'act' ? 'go' : 'wa';
    const sk = s.signal_kind || '';
    const tip = KIND_TIP[sk] || t('kind_default');
    const mcap = s.mcap_fmt || '\\u2014';
    const band = s.money_band || 'unknown';
    const mcapAttr = s.mcap != null ? s.mcap : '';
    const tg = s.telegram_worthy ? 'TG\\u2713' : 'TG\\u2014';
    return '<article class="sig ' + cls + '" data-mcap="' + escapeHtml(mcapAttr) + '" data-band="' + escapeHtml(band) + '">' +
      '<div class="sig-top">' +
      '<span class="tier">' + escapeHtml(title) + ' \\u00b7 ' + escapeHtml(s.score) + '/100</span>' +
      '<b>' + escapeHtml(s.symbol || '?') + '</b>' +
      '<span class="money">' + escapeHtml(mcap) + '</span>' +
      '<span class="meta">' + escapeHtml(tg) + '</span>' +
      '</div>' +
      '<div class="meta" style="margin:4px 0">' + escapeHtml(summary) + '</div>' +
      '<div class="sig-meta-grid">' +
      '<span>kind <b data-tip="' + escapeHtml(tip) + '">' + escapeHtml(sk || '\\u2014') + '</b></span>' +
      '<span>dir <b>' + escapeHtml(s.direction || '\\u2014') + '</b></span>' +
      '<span>entity <b>' + escapeHtml(s.match_entity || '\\u2014') + '</b></span>' +
      '<span>role <b>' + escapeHtml(s.match_role || '\\u2014') + '</b></span>' +
      '<span>source <b>' + escapeHtml(s.source || '\\u2014') + '</b></span>' +
      '<span>band <b>' + escapeHtml(s.money_label || band) + '</b></span>' +
      '<span>age <b>' + escapeHtml(fmtAge(s.timestamp, s.saved_at)) + '</b></span>' +
      '<span>tx <b>' + escapeHtml(shortHash(s.hash)) + '</b></span>' +
      '</div>' +
      '<ul class="why">' + why + '</ul></article>';
  }).join('');
}
function renderSigTable(act, watch) {
  const rows = [...(act || []).map(s => ({...s, _shelf: 'ACT'})), ...(watch || []).map(s => ({...s, _shelf: 'WATCH'}))];
  if (!rows.length) return '<div class="empty">\\u2014</div>';
  const body = rows.map(s => {
    const reasons = (currentLang === 'uk' && s.reasons_uk && s.reasons_uk.length) ? s.reasons_uk : (s.reasons || []);
    const why = reasons.slice(0, 8).join(' \\u00b7 ');
    const tierCls = s._shelf === 'ACT' ? 'tier-act' : 'tier-watch';
    return '<tr>' +
      '<td><span class="tier-pill ' + tierCls + '">' + escapeHtml(s._shelf) + '</span></td>' +
      '<td><b>' + escapeHtml(s.symbol || '?') + '</b></td>' +
      '<td>' + escapeHtml(s.score) + '</td>' +
      '<td>' + escapeHtml(s.signal_kind || '\\u2014') + '</td>' +
      '<td>' + escapeHtml(s.direction || '\\u2014') + '</td>' +
      '<td>' + escapeHtml(s.match_entity || '\\u2014') + '</td>' +
      '<td>' + escapeHtml(s.mcap_fmt || '\\u2014') + '</td>' +
      '<td>' + escapeHtml(s.money_label || s.money_band || '\\u2014') + '</td>' +
      '<td>' + escapeHtml(s.source || '\\u2014') + '</td>' +
      '<td>' + escapeHtml(fmtAge(s.timestamp, s.saved_at)) + '</td>' +
      '<td>' + (s.telegram_worthy ? '\\u2713' : '\\u2014') + '</td>' +
      '<td class="col-why">' + escapeHtml(why) + '</td>' +
      '</tr>';
  }).join('');
  return '<table class="sig-table"><thead><tr>' +
    '<th>shelf</th><th>token</th><th>score</th><th>kind</th><th>dir</th><th>entity</th>' +
    '<th>mcap</th><th>band</th><th>source</th><th>age</th><th>TG</th><th>why</th>' +
    '</tr></thead><tbody>' + body + '</tbody></table>';
}
function applySigKpis(board, act, watch) {
  const el = document.getElementById('sigKpis');
  if (!el) return;
  const tiers = board.tiers_sample || {};
  const bands = board.money_bands || {};
  const bandBits = Object.keys(bands).filter(k => k !== 'any').map(k => {
    const c = (bands[k] && bands[k].count) || 0;
    return c ? (k + ':' + c) : null;
  }).filter(Boolean).join(' \\u00b7 ');
  el.innerHTML =
    '<div><div class="kpi-mini" style="color:var(--ok)">' + escapeHtml(act.length) + '<small>ACT shown</small></div></div>' +
    '<div><div class="kpi-mini" style="color:var(--warn)">' + escapeHtml(watch.length) + '<small>WATCH shown</small></div></div>' +
    '<div><div class="kpi-mini">' + escapeHtml(board.act_count || 0) + '<small>ACT total</small></div></div>' +
    '<div><div class="kpi-mini">' + escapeHtml(board.watch_count || 0) + '<small>WATCH total</small></div></div>' +
    '<div><div class="kpi-mini">' + escapeHtml(tiers.actionable || 0) + '<small>tier act</small></div></div>' +
    '<div><div class="kpi-mini">' + escapeHtml(tiers.watch || 0) + '<small>tier watch</small></div></div>' +
    '<div><div class="kpi-mini">' + escapeHtml(tiers.noise || 0) + '<small>noise</small></div></div>' +
    '<div class="meta" style="flex:1;min-width:180px">mcap bands: ' + escapeHtml(bandBits || '\\u2014') +
    '<br/>min ACT \\u2265' + escapeHtml(board.min_score || SNAP.min_score) +
    ' \\u00b7 WATCH \\u2265' + escapeHtml(board.watch_score || SNAP.watch_score) +
    ' \\u00b7 updated ' + escapeHtml((board.generated_at || '').replace('T', ' ').slice(0, 19) || '\\u2014') +
    '</div>';
}

let BOARD_RAW = SNAP.board || { act: [], watch: [] };
let CYCLES_RAW = SNAP.cycles || {};

function passMoneyFilter(s) {
  const band = (document.getElementById('moneyBand') || {}).value || 'any';
  const minRaw = (document.getElementById('minMcap') || {}).value;
  const minM = minRaw === '' || minRaw == null ? null : Number(minRaw);
  const mcap = s.mcap == null || s.mcap === '' ? null : Number(s.mcap);
  if (minM != null && !Number.isNaN(minM) && minM > 0) {
    if (mcap == null || mcap < minM) return false;
  }
  if (band === 'any' || band === 'all') return true;
  if (band === 'unknown') return mcap == null || Number.isNaN(mcap);
  const ranges = {
    micro: [0, 350000],
    small: [350000, 3000000],
    mid: [3000000, 10000000],
    large: [10000000, 60000000],
    mega: [60000000, Infinity],
  };
  const r = ranges[band];
  if (!r) return true;
  if (mcap == null || Number.isNaN(mcap)) return false;
  return mcap >= r[0] && mcap < r[1];
}

function applyBoard(board) {
  if (!board) return;
  BOARD_RAW = board;
  const actAll = board.act || [];
  const watchAll = board.watch || [];
  const act = actAll.filter(passMoneyFilter);
  const watch = watchAll.filter(passMoneyFilter);
  document.getElementById('actCount').textContent = '(' + act.length + (act.length !== actAll.length ? '/' + actAll.length : '') + ')';
  document.getElementById('watchCount').textContent = '(' + watch.length + (watch.length !== watchAll.length ? '/' + watchAll.length : '') + ')';
  document.getElementById('actBoard').innerHTML = renderCards(act, 'act');
  document.getElementById('watchBoard').innerHTML = renderCards(watch, 'watch');
  const table = document.getElementById('sigTable');
  if (table) table.innerHTML = renderSigTable(act, watch);
  applySigKpis(board, act, watch);
  const hint = document.getElementById('moneyFilterHint');
  if (hint) {
    const band = document.getElementById('moneyBand').value;
    const minRaw = document.getElementById('minMcap').value;
    const parts = [];
    if (band !== 'any') parts.push(document.getElementById('moneyBand').selectedOptions[0].textContent);
    if (minRaw) parts.push(t('money_min') + minRaw);
    hint.textContent = parts.length ? t('money_hint_filter', { parts: parts.join(' \\u00b7 '), n: (act.length + watch.length) }) : t('money_hint_all');
  }
}
function bindMoneyFilters() {
  const band = document.getElementById('moneyBand');
  const min = document.getElementById('minMcap');
  if (band) band.addEventListener('change', () => applyBoard(BOARD_RAW));
  if (min) min.addEventListener('input', () => applyBoard(BOARD_RAW));
  // restore from URL ?money=small&min_mcap=1000000
  const q = new URLSearchParams(location.search);
  if (q.get('money') && band) band.value = q.get('money');
  if (q.get('min_mcap') && min) min.value = q.get('min_mcap');
}
bindMoneyFilters();

function setProc(id, running, detail, pid, wait) {
  const on = !!running;
  const st = document.getElementById('st-' + id);
  const dot = document.getElementById('dot-' + id);
  const det = document.getElementById('det-' + id);
  const pidEl = document.getElementById('pid-' + id);
  const cls = wait ? 'badge-wait' : (on ? 'badge-on' : 'badge-off');
  const label = wait ? 'stale' : (on ? 'ON' : 'off');
  if (st) { st.textContent = label; st.className = 'badge ' + cls; }
  if (dot) { dot.className = 'proc-dot ' + (wait ? 'wait' : (on ? 'on' : 'off')); }
  if (det) det.textContent = detail || (on ? 'running' : 'stopped');
  if (pidEl) pidEl.textContent = pid ? ('pid ' + pid) : '';
  // legacy badges if present
  const legacy = ({ dwf: 'dwfBadge', prep: 'prepBadge', scanner: 'scanBadge', intel: 'intelBadge', rozvidka: 'rozBadge' })[id];
  if (legacy) setBadge(legacy, on && !wait);
}
function applyAllProcesses(d) {
  if (!d) return;
  const ih = d.intel_health || {};
  const rh = d.rozvidka_health || {};
  const cyc = d.cycles || {};
  const prog = d.progress || {};
  const dash = d.dashboard || {};
  setProc('dashboard', dash.running, dash.state || 'api :8765', dash.pid);
  setProc('dwf', d.dwf && d.dwf.running, 'live wallet monitor', d.dwf && d.dwf.pid);
  setProc('prep', d.prep && d.prep.running, 'prep alerts', d.prep && d.prep.pid);
  const scanDetail = 'graph ' + (prog.pct != null ? prog.pct + '%' : '') +
    (prog.done != null ? (' · ' + prog.done + '/' + prog.total) : '') +
    (cyc.expand_queue != null ? (' · expand_q ' + cyc.expand_queue) : '');
  const scanWait = !!(d.scanner && d.scanner.running && cyc.cycle_status === 'stale');
  setProc('scanner', d.scanner && d.scanner.running, scanDetail || 'token walker', d.scanner && d.scanner.pid, scanWait);
  const intelWait = !!(d.intel && d.intel.running && ih.cycle_status === 'stale');
  const intelDet = (ih.cycle_status || '') +
    (ih.cycle != null ? (' · cycle ' + ih.cycle) : '') +
    (ih.queue != null ? (' · queue ' + ih.queue) : '') +
    (ih.remaining_sec != null ? (' · left ' + Math.round(ih.remaining_sec / 60) + 'm') : '');
  setProc('intel', d.intel && d.intel.running, intelDet || 'collect', d.intel && d.intel.pid, intelWait);
  const rozWait = !!(d.rozvidka && d.rozvidka.running && rh.cycle_status === 'stale');
  const rozDet = (rh.cycle_status || '') +
    (rh.turn != null ? (' · turn ' + rh.turn) : '') +
    (rh.model ? (' · ' + rh.model) : '');
  setProc('rozvidka', d.rozvidka && d.rozvidka.running, rozDet || 'agent', d.rozvidka && d.rozvidka.pid, rozWait);
  const orch = d.orch || {};
  const orchDet = orch.line || (orch.last_report && (orch.last_report.kind + ' ' + (orch.last_report.module || ''))) || 'sleep';
  setProc('orch', orch.running, orchDet, orch.pid);

  const rows = [
    ['dashboard', dash.running],
    ['dwf', d.dwf && d.dwf.running],
    ['prep', d.prep && d.prep.running],
    ['scanner', d.scanner && d.scanner.running],
    ['intel', d.intel && d.intel.running],
    ['rozvidka', d.rozvidka && d.rozvidka.running],
    ['orch', orch.running],
  ];
  const onN = rows.filter(r => r[1]).length;
  const sum = document.getElementById('procSummary');
  if (sum) sum.innerHTML = '<b class="on">' + onN + ' ON</b> · <b class="off">' + (rows.length - onN) + ' off</b> · ' + rows.length + ' total';
  const il = document.getElementById('intelLine');
  const rl = document.getElementById('rozLine');
  if (il) il.textContent = 'intel: ' + (intelDet || '—');
  if (rl) rl.textContent = 'rozvidka: ' + (rozDet || '—');
  const ol = document.getElementById('orchLine');
  if (ol) ol.textContent = orch.line || 'орк: —';
  const pl = document.getElementById('procLine');
  if (pl) {
    pl.textContent = [
      'DWF ' + (d.dwf && d.dwf.running ? 'ON' : 'off'),
      'Prep ' + (d.prep && d.prep.running ? 'ON' : 'off'),
      'Scan ' + (d.scanner && d.scanner.running ? 'ON' : 'off'),
      'Intel ' + (d.intel && d.intel.running ? 'ON' : 'off'),
      'Roz ' + (d.rozvidka && d.rozvidka.running ? 'ON' : 'off'),
      'Orch ' + (orch.running ? 'ON' : 'off'),
    ].join(' · ');
  }
}
function applyReports(reports) {
  if (!reports) return;
  document.querySelectorAll('#reportsGrid a.report[data-key]').forEach(a => {
    const ok = !!reports[a.dataset.key];
    a.classList.toggle('missing', !ok);
    let st = a.querySelector('.rep-st');
    if (!st) {
      st = document.createElement('span');
      st.className = 'rep-st';
      a.insertBefore(st, a.firstChild);
    }
    st.textContent = ok ? '\\u2713' : '\\u2014';
  });
}
function fmtTs(iso) {
  if (!iso) return '\\u2014';
  try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
}
function renderIntelLive(j) {
  const el = document.getElementById('intelLiveBody');
  if (!el) return;
  if (!j || j.error) {
    el.innerHTML = '<div class="live-empty">' + escapeHtml(j && j.error ? j.error : 'no data') + '</div>';
    return;
  }
  const st = j.state || {};
  const h = j.health || {};
  const stats = j.stats || {};
  const qPrev = (j.queue_preview || []).slice(0, 8).map(x =>
    '<li>p' + escapeHtml(x.priority) + ' ' + escapeHtml(x.chain) + ' ' + escapeHtml((x.address || '').slice(0, 14)) + '\\u2026 ' + escapeHtml(x.reason || '') + '</li>'
  ).join('') || '<li class="live-empty">queue empty</li>';
  const fam = (j.families || []).slice(0, 5).map(f =>
    '<li>' + escapeHtml(f.id || f.family_id || '?') + ' · ' + escapeHtml(f.hub_short || f.hub || '') + ' · n=' + escapeHtml(f.size || f.members) + '</li>'
  ).join('') || '<li class="live-empty">—</li>';
  const prep = (j.prepump || []).slice(0, 4).map(p =>
    '<li>' + escapeHtml(p.short || p.address || '?') + ' · ' + escapeHtml((p.tokens || []).slice(0, 3).join(', ')) + '</li>'
  ).join('') || '';
  el.innerHTML =
    '<div class="live-kpis">' +
    '<span>cycle <b>' + escapeHtml(st.cycle != null ? st.cycle : h.cycle) + '</b></span>' +
    '<span>queue <b>' + escapeHtml(st.queue != null ? st.queue : h.queue) + '</b></span>' +
    '<span>addr <b>' + escapeHtml(stats.addresses) + '</b></span>' +
    '<span>edges <b>' + escapeHtml(stats.edges) + '</b></span>' +
    '<span>families <b>' + escapeHtml(stats.families) + '</b></span>' +
    '<span>until <b>' + escapeHtml(fmtTs(st.collect_until)) + '</b></span>' +
    '</div>' +
    '<div class="meta">status: ' + escapeHtml(h.cycle_status || (st.running ? 'running' : 'stopped')) +
    (h.remaining_sec != null ? (' · left ' + Math.round(h.remaining_sec / 60) + 'm') : '') + '</div>' +
    '<h4 style="margin:10px 0 4px;font-size:12px;color:var(--muted)">queue</h4><ul class="live-list">' + qPrev + '</ul>' +
    '<h4 style="margin:10px 0 4px;font-size:12px;color:var(--muted)">families</h4><ul class="live-list">' + fam + '</ul>' +
    (prep ? ('<h4 style="margin:10px 0 4px;font-size:12px;color:var(--muted)">pre-pump</h4><ul class="live-list">' + prep + '</ul>') : '');
}
function renderRozLive(j) {
  const el = document.getElementById('rozLiveBody');
  if (!el) return;
  if (!j || j.error) {
    el.innerHTML = '<div class="live-empty">' + escapeHtml(j && j.error ? j.error : 'no data') + '</div>';
    return;
  }
  const st = j.state || {};
  const h = j.health || {};
  const rel = j.relations || {};
  const tops = (rel.top_families || []).slice(0, 5).map(f =>
    '<li>' + escapeHtml(f.short || f.hub || '?') + ' · pump=' + escapeHtml(f.pump_n) + ' · n=' + escapeHtml(f.size) + '</li>'
  ).join('') || '<li class="live-empty">—</li>';
  const findings = (j.findings || []).slice(0, 5).map(f =>
    '<li>' + escapeHtml(f.title || f.type || '?') + ' · sc=' + escapeHtml(f.score) + '</li>'
  ).join('') || '<li class="live-empty">—</li>';
  const last = j.last_turn || {};
  el.innerHTML =
    '<div class="live-kpis">' +
    '<span>turn <b>' + escapeHtml(st.turn != null ? st.turn : h.turn) + '</b></span>' +
    '<span>model <b>' + escapeHtml(st.model || j.model || '?') + '</b></span>' +
    '<span>ollama <b>' + escapeHtml((j.ollama && j.ollama.ok) ? 'ok' : 'off') + '</b></span>' +
    '<span>families <b>' + escapeHtml((rel.stats || {}).families || (rel.stats || {}).family_count) + '</b></span>' +
    '</div>' +
    '<div class="meta">status: ' + escapeHtml(h.cycle_status || (st.running ? 'running' : 'stopped')) +
    (last.title ? (' · ' + escapeHtml(last.title)) : '') + '</div>' +
    '<h4 style="margin:10px 0 4px;font-size:12px;color:var(--muted)">findings</h4><ul class="live-list">' + findings + '</ul>' +
    '<h4 style="margin:10px 0 4px;font-size:12px;color:var(--muted)">families</h4><ul class="live-list">' + tops + '</ul>';
}
function renderWikiLive(j) {
  const kpis = document.getElementById('wikiKpis');
  const board = document.getElementById('wikiBoard');
  if (!board) return;
  if (!j || j.error) {
    board.innerHTML = '<div class="live-empty">' + escapeHtml(j && j.error ? j.error : 'немає вікі — натисни Оновити вікі') + '</div>';
    return;
  }
  const st = j.stats || {};
  if (kpis) {
    kpis.innerHTML =
      '<span>сімʼї <b>' + escapeHtml(st.families) + '</b></span>' +
      '<span>ходити <b>' + escapeHtml(st.go) + '</b></span>' +
      '<span>подати <b>' + escapeHtml(st.submit) + '</b></span>' +
      '<span>рука <b>' + escapeHtml(st.hand) + '</b></span>' +
      '<span>папір <b>' + escapeHtml((j.paper && j.paper.paper_n) || 0) + '</b></span>';
  }
  const rows = j.moves || [];
  board.innerHTML = rows.length ? rows.slice(0, 12).map(f => {
    const mv = f.move || {};
    const pat = f.patron || {};
    const fr = f.frames || {};
    const wh = mv.where || {};
    const cls = mv.move || 'watch';
    return '<article class="wiki-card ' + cls + '">' +
      '<div class="mv">' + escapeHtml(mv.move_uk || mv.move || '') + ' · ' + escapeHtml(wh.hint || '') + '</div>' +
      '<div class="title">' + escapeHtml(f.short || f.id || '?') + ' · патрон ' + escapeHtml(pat.short || '—') + '</div>' +
      '<div class="meta">рамки ' + escapeHtml(fr.status || '—') +
      ' · med ' + escapeHtml(fr.median) + ' · ×' + escapeHtml(fr.amount_ratio) +
      ' · ' + escapeHtml((f.tokens || []).slice(0, 4).join(', ')) + '</div>' +
      '<div class="meta">' + escapeHtml(mv.why || '') + '</div></article>';
  }).join('') : '<div class="live-empty">поки немає сімей — збір intel/розвідка ще порожній</div>';
}
async function refreshAgents() {
  try {
    const [ri, rr, rw] = await Promise.all([
      fetch(API + '/api/intel?ts=' + Date.now(), { cache: 'no-store' }),
      fetch(API + '/api/rozvidka?ts=' + Date.now(), { cache: 'no-store' }),
      fetch(API + '/api/wiki?ts=' + Date.now(), { cache: 'no-store' }),
    ]);
    if (ri.ok) renderIntelLive(await ri.json());
    if (rr.ok) renderRozLive(await rr.json());
    if (rw.ok) renderWikiLive(await rw.json());
  } catch (e) {}
}
function applyCycles(c) {
  if (!c) return;
  CYCLES_RAW = c;
  const b = document.getElementById('cycleBadge');
  if (b) {
    b.textContent = 'cycle: ' + (c.cycle_status || '?');
    b.className = 'badge ' + ({ ok: 'badge-on', stale: 'badge-wait', stopped: 'badge-off' }[c.cycle_status] || 'badge-wait');
  }
  const age = document.getElementById('cycleAge');
  if (age) age.textContent = c.age_sec != null ? c.age_sec : '\\u2014';
  const ul = document.getElementById('cycleIssues');
  const issues = (c.issues_i18n && c.issues_i18n[currentLang]) || c.issues || [];
  if (ul) ul.innerHTML = issues.length ? issues.map(i => '<li>' + escapeHtml(i) + '</li>').join('') : '<li>' + escapeHtml(t('issues_none')) + '</li>';
}
function applyProgress(p) {
  if (!p) return;
  const pct = p.pct != null ? p.pct : 0;
  document.getElementById('kpiPct').innerHTML = escapeHtml(pct) + '%<small> \\u00b7 ' + escapeHtml(p.done) + '/' + escapeHtml(p.total) + '</small>';
  document.getElementById('progBar').style.width = Math.max(0, Math.min(100, Number(pct))) + '%';
  document.getElementById('progLabel').textContent = 'last=' + (p.last_token || '\\u2014');
}

function applyLang(lang) {
  lang = normalizeLang(lang);
  currentLang = lang;
  try { localStorage.setItem(LANG_KEY, lang); } catch (e) {}
  document.documentElement.lang = lang;
  const FMT = { min: SNAP.min_score, watch: SNAP.watch_score, min1: SNAP.min_score - 1, url: '<code>http://127.0.0.1:8765/</code>' };
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n, FMT); });
  document.querySelectorAll('[data-i18n-tip]').forEach(el => { el.setAttribute('data-tip', t(el.dataset.i18nTip, FMT)); });
  document.querySelectorAll('[data-i18n-html]').forEach(el => { el.innerHTML = t(el.dataset.i18nHtml, FMT); });
  document.querySelectorAll('.lang-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.lang === lang));
  document.title = t('title', FMT);
  applyBoard(BOARD_RAW);
  applyCycles(CYCLES_RAW);
}

applyProgress(SNAP.progress);
let savedLang = null;
try { savedLang = localStorage.getItem(LANG_KEY); } catch (e) {}
applyLang(savedLang || DEFAULT_LANG);

document.querySelectorAll('.lang-btn').forEach(btn => {
  btn.addEventListener('click', () => applyLang(btn.dataset.lang));
});

async function refresh() {
  try {
    const r = await fetch(API + '/api/status', { cache: 'no-store' });
    const d = await r.json();
    document.getElementById('offlineHint').style.display = 'none';
    const srv = document.getElementById('srvBadge');
    srv.textContent = 'online'; srv.className = 'badge badge-on';
    if (d.board) applyBoard(d.board);
    if (d.cycles) applyCycles(d.cycles);
    applyAllProcesses(d);
    if (d.progress) applyProgress(d.progress);
    if (d.reports) applyReports(d.reports);
    const jobs = Object.values(d.jobs || {});
    document.getElementById('jobOut').textContent = jobs.length
      ? jobs.map(j => j.name + ' pid=' + j.pid + (j.running ? ' RUN' : ' done')).join('\\n')
      : t('jobs_none');
  } catch (e) {
    document.getElementById('offlineHint').style.display = 'block';
    const srv = document.getElementById('srvBadge');
    srv.textContent = 'offline/static'; srv.className = 'badge badge-wait';
  }
}

async function act(action) {
  const sysOut = document.getElementById('sysOut');
  const jobOut = document.getElementById('jobOut');
  const jobActions = new Set([
    'backfill_signals', 'rebuild_hub', 'graph_html', 'run_prep', 'run_deployers', 'run_scans',
    'rebuild_panel', 'check_cycles', 'intel_once', 'intel_hubs', 'intel_ui',
    'rozvidka_once', 'rozvidka_once_nolm', 'rozvidka_ui',
  ]);
  const outEl = jobActions.has(action) ? (jobOut || sysOut) : (sysOut || jobOut);
  if (outEl) outEl.textContent = '\\u2026 ' + action;
  try {
    const r = await fetch(API + '/api/action', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    const d = await r.json();
    const msg = (d.out || d.error || JSON.stringify(d)).slice(0, 800);
    if (outEl) outEl.textContent = msg;
    toast((d.ok === false ? 'FAIL: ' : 'OK: ') + action);
    setTimeout(refresh, 900);
    if (action.startsWith('intel') || action.startsWith('rozvidka') || action.startsWith('orch') || action.includes('intel')) {
      setTimeout(refreshAgents, 1200);
    }
  } catch (e) {
    if (outEl) outEl.textContent = t('toast_no_server');
    toast(t('toast_no_link'));
  }
}

document.querySelectorAll('button[data-action]').forEach(btn => {
  btn.addEventListener('click', () => act(btn.dataset.action));
});

(function navActive() {
  const chrome = document.querySelector('.mute-chrome');
  const links = [...document.querySelectorAll('.mute-chrome a[data-nav]')];
  const sections = links.map(a => document.getElementById(a.dataset.nav)).filter(Boolean);
  let locked = null;
  let lockT = 0;
  function headerH() {
    const h = chrome ? chrome.offsetHeight : 84;
    document.documentElement.style.setProperty('--header-h', h + 'px');
    document.documentElement.style.setProperty('--chrome-h', h + 'px');
    return h;
  }
  function setActive(id) {
    links.forEach(a => a.classList.toggle('active', a.dataset.nav === id));
  }
  function sync() {
    headerH();
    if (locked && Date.now() < lockT) return;
    locked = null;
    let cur = sections[0] && sections[0].id;
    const y = window.scrollY + headerH() + 12;
    for (const s of sections) {
      if (s.offsetTop <= y) cur = s.id;
    }
    setActive(cur);
  }
  links.forEach(a => {
    a.addEventListener('click', (e) => {
      const id = a.dataset.nav;
      const el = document.getElementById(id);
      if (!el) return;
      e.preventDefault();
      locked = id;
      lockT = Date.now() + 900;
      setActive(id);
      const top = el.getBoundingClientRect().top + window.scrollY - headerH() - 8;
      window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
      history.replaceState(null, '', '#' + id);
    });
  });
  window.addEventListener('scroll', sync, { passive: true });
  window.addEventListener('resize', headerH, { passive: true });
  headerH();
  sync();
})();

refresh();
refreshAgents();
setInterval(refresh, 4000);
setInterval(refreshAgents, 8000);
"""


def write_dashboard_html() -> str:
    """Generate out/dashboard.html — full static panel + live API hooks (EN default, UK toggle)."""
    progress = gs.progress_snapshot()
    cycles = check_cycle_health()
    board = signal_board(limit_act=100, limit_watch=100)
    write_cycles_json(OUT / "cycles_health.json")

    lang = normalize_lang(DEFAULT_LANG)

    def T(key: str, **fmt: Any) -> str:
        return _esc(t(lang, key, **fmt))

    def TIP(key: str, **fmt: Any) -> str:
        return _tip(lang, key, **fmt)

    pct = progress.get("pct") or 0
    pct_w = max(0, min(100, float(pct)))
    tiers = progress.get("signals_by_tier") or {}
    min1 = MIN_SCORE - 1
    snap = {
        "progress": progress,
        "cycles": cycles,
        "board": board,
        "min_score": MIN_SCORE,
        "watch_score": WATCH_SCORE,
    }
    snap_json = json.dumps(snap, ensure_ascii=False).replace("</", "<\\/")
    i18n_json = packs_json().replace("</", "<\\/")

    issues = cycles.get("issues") or []
    issues_html = (
        "".join(f"<li>{_esc(i)}</li>" for i in issues)
        if issues
        else f"<li>{_esc(UI.get(lang, UI[DEFAULT_LANG])['issues_none'])}</li>"
    )
    cstat = cycles.get("cycle_status") or "stopped"
    cbadge = {"ok": "badge-on", "stale": "badge-wait", "stopped": "badge-off"}.get(cstat, "badge-wait")
    en_active = " active" if lang == "en" else ""
    uk_active = " active" if lang == "uk" else ""
    offline_body_html = t(lang, "offline_body", url="<code>http://127.0.0.1:8765/</code>")

    doc = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title data-i18n="title">{T('title')}</title>
<style>{_STYLE}</style>
</head>
<body>
{chrome_nav("home")}
<header>
  <div class="header-top">
    <div class="header-copy">
      <h1>MUTE
        <span id="srvBadge" class="badge badge-wait" data-i18n-tip="tip_srv" data-tip="{TIP('tip_srv')}">static</span>
        <span id="cycleBadge" class="badge {cbadge}" data-i18n-tip="tip_cycle" data-tip="{TIP('tip_cycle')}">cycle: {_esc(cstat)}</span>
        <span class="help" data-i18n-tip="tip_mute" data-tip="{TIP('tip_mute')}">?</span>
      </h1>
      <p class="meta" data-i18n="meta_line">{T('meta_line', min=MIN_SCORE, watch=WATCH_SCORE)}</p>
    </div>
    <div class="row lang-toggle" role="group" aria-label="Language">
      <button type="button" class="btn lang-btn{en_active}" data-lang="en" data-i18n="lang_en" data-i18n-tip="lang_tip" data-tip="{TIP('lang_tip')}">{_esc(UI[DEFAULT_LANG]['lang_en'])}</button>
      <button type="button" class="btn lang-btn{uk_active}" data-lang="uk" data-i18n="lang_uk" data-i18n-tip="lang_tip" data-tip="{TIP('lang_tip')}">{_esc(UI[DEFAULT_LANG]['lang_uk'])}</button>
    </div>
  </div>
</header>
<main>
  <div id="offlineHint" class="warnbox" style="display:none">
    <b data-i18n="offline_title">{T('offline_title')}</b><span data-i18n-html="offline_body">{offline_body_html}</span>
    <code>./scripts/start_dashboard.sh</code>
    <span data-i18n="offline_tail">{T('offline_tail')}</span>
  </div>

  <section id="now">
    <h2><span data-i18n="h2_now">{T('h2_now')}</span>
      <span class="help" data-i18n-tip="tip_now" data-tip="{TIP('tip_now', min=MIN_SCORE, watch=WATCH_SCORE, min1=min1)}">?</span>
    </h2>
    <div class="sig-kpis" id="sigKpis"></div>
    <div class="filters" id="moneyFilters">
      <label for="moneyBand" data-i18n="money_label" data-i18n-tip="tip_money" data-tip="{TIP('tip_money')}">{T('money_label')}</label>
      <select id="moneyBand" title="Market cap">
        <option value="any" data-i18n="money_any">{T('money_any')}</option>
        <option value="micro">&lt; $350K</option>
        <option value="small">$350K\u2013$3M</option>
        <option value="mid">$3M\u2013$10M</option>
        <option value="large">$10M\u2013$60M</option>
        <option value="mega">\u2265 $60M</option>
        <option value="unknown" data-i18n="money_unknown">{T('money_unknown')}</option>
      </select>
      <label for="minMcap" data-i18n="money_min">{T('money_min')}</label>
      <input id="minMcap" type="number" min="0" step="1000" placeholder="0" style="width:110px" title="Min market cap USD"/>
      <span class="hint" id="moneyFilterHint" data-i18n="money_hint_all">{T('money_hint_all')}</span>
    </div>
    <div class="grid-2">
      <div class="board act">
        <h3><span data-i18n="act_title">{T('act_title')}</span> <span class="n" id="actCount">({board.get('act_count', 0)})</span>
          <span class="help" data-i18n-tip="tip_act" data-tip="{TIP('tip_act')}">?</span>
        </h3>
        <p class="meta" data-i18n="act_sub">{T('act_sub')}</p>
        <div class="sig-list" id="actBoard"></div>
      </div>
      <div class="board watch">
        <h3><span data-i18n="watch_title">{T('watch_title')}</span> <span class="n" id="watchCount">({board.get('watch_count', 0)})</span>
          <span class="help" data-i18n-tip="tip_watch" data-tip="{TIP('tip_watch')}">?</span>
        </h3>
        <p class="meta" data-i18n="watch_sub">{T('watch_sub')}</p>
        <div class="sig-list" id="watchBoard"></div>
      </div>
    </div>
    <div class="sig-table-wrap">
      <div id="sigTable"></div>
    </div>
    <p class="snap-note">
      <span data-i18n="snap_note">{T('snap_note')}</span>
      <span class="term" data-i18n-tip="tip_act_count" data-tip="{TIP('tip_act_count', min=MIN_SCORE)}">act={tiers.get('actionable', 0)}</span> \u00b7
      <span class="term" data-i18n-tip="tip_watch_count" data-tip="{TIP('tip_watch_count', watch=WATCH_SCORE, min1=min1)}">watch={tiers.get('watch', 0)}</span> \u00b7
      <span class="term" data-i18n-tip="tip_noise_count" data-tip="{TIP('tip_noise_count', watch=WATCH_SCORE)}">noise={tiers.get('noise', 0)}</span> \u00b7
      <span data-i18n="tg_threshold">{T('tg_threshold', min=MIN_SCORE)}</span>
    </p>
  </section>

  <section id="wiki">
    <h2>Сімʼї · коли діяти</h2>
    <p class="meta">Патрон фінансує сімʼю. Рамки — норма сум/частоти. <b>ходити</b> = перевірити вхід · <b>подати</b> = сигнал, не гнатися · <b>де</b> = мережа / DEX·CEX. Трейд спочатку на папері.</p>
    <div class="live-kpis" id="wikiKpis">\u2014</div>
    <div class="wiki-grid" id="wikiBoard"><div class="live-empty">loading /api/wiki \u2026</div></div>
    <div class="row" style="margin-top:10px">
      <button data-action="rebuild_wiki">Оновити вікі</button>
      <a class="btn" href="/wiki.html">wiki.html</a>
      <a class="btn" href="/kanban.html">канбан</a>
    </div>
  </section>

  <section id="procs">
    <h2>Processes · процеси</h2>
    <div class="proc-board">
      <div class="proc-head">
        <h3>All services</h3>
        <div class="proc-summary" id="procSummary">\u2014</div>
      </div>
      <table class="proc-table" aria-label="MUTE processes">
        <thead>
          <tr>
            <th>Process</th>
            <th>Status</th>
            <th class="col-ctrl">Controls</th>
            <th class="col-role">What it does / роль</th>
            <th>Details</th>
            <th class="col-link">Open</th>
          </tr>
        </thead>
        <tbody id="procBody">
          <tr data-proc="dashboard">
            <td class="proc-name"><span class="proc-dot off" id="dot-dashboard"></span>Dashboard</td>
            <td><span class="badge badge-off" id="st-dashboard">off</span> <span class="meta" id="pid-dashboard"></span></td>
            <td class="proc-ctrl col-ctrl"><span class="meta">always on</span></td>
            <td class="proc-role col-role">Panel API :8765 · HTML control</td>
            <td class="proc-detail" id="det-dashboard">\u2014</td>
            <td class="proc-link col-link"><a href="/">panel</a></td>
          </tr>
          <tr data-proc="dwf">
            <td class="proc-name"><span class="proc-dot off" id="dot-dwf"></span>DWF monitor</td>
            <td><span class="badge badge-off" id="st-dwf">off</span> <span class="meta" id="pid-dwf"></span></td>
            <td class="proc-ctrl col-ctrl">
              <button class="ok" data-action="start_dwf" title="Start">▶</button>
              <button class="danger" data-action="stop_dwf" title="Stop">■</button>
            </td>
            <td class="proc-role col-role">Live MM/seed wallets \u2192 Telegram</td>
            <td class="proc-detail" id="det-dwf">\u2014</td>
            <td class="proc-link col-link"><a href="#launch">controls</a></td>
          </tr>
          <tr data-proc="prep">
            <td class="proc-name"><span class="proc-dot off" id="dot-prep"></span>Prep monitor</td>
            <td><span class="badge badge-off" id="st-prep">off</span> <span class="meta" id="pid-prep"></span></td>
            <td class="proc-ctrl col-ctrl">
              <button class="ok" data-action="start_prep" title="Start">▶</button>
              <button class="danger" data-action="stop_prep" title="Stop">■</button>
            </td>
            <td class="proc-role col-role">Pump-prep live scores (act \u2192 Telegram)</td>
            <td class="proc-detail" id="det-prep">\u2014</td>
            <td class="proc-link col-link"><a href="#now">live</a></td>
          </tr>
          <tr data-proc="scanner">
            <td class="proc-name"><span class="proc-dot off" id="dot-scanner"></span>Graph scanner</td>
            <td><span class="badge badge-off" id="st-scanner">off</span> <span class="meta" id="pid-scanner"></span></td>
            <td class="proc-ctrl col-ctrl">
              <button class="ok" data-action="start_scanner" title="Start">▶</button>
              <button class="danger" data-action="stop_scanner" title="Stop">■</button>
            </td>
            <td class="proc-role col-role">Token walk · edges · expand queue</td>
            <td class="proc-detail" id="det-scanner">\u2014</td>
            <td class="proc-link col-link"><a href="/reports/graph_live.html">graph</a></td>
          </tr>
          <tr data-proc="intel">
            <td class="proc-name"><span class="proc-dot off" id="dot-intel"></span>Intel collect</td>
            <td><span class="badge badge-off" id="st-intel">off</span> <span class="meta" id="pid-intel"></span></td>
            <td class="proc-ctrl col-ctrl">
              <button class="ok" data-action="start_intel_2h" title="Start 2h">▶2h</button>
              <button class="ok" data-action="start_intel" title="Resume">▶</button>
              <button class="danger" data-action="stop_intel" title="Stop">■</button>
            </td>
            <td class="proc-role col-role">Solana+BNB families · pre-pump · cycles</td>
            <td class="proc-detail" id="det-intel">\u2014</td>
            <td class="proc-link col-link"><a href="/intel.html">intel</a></td>
          </tr>
          <tr data-proc="rozvidka">
            <td class="proc-name"><span class="proc-dot off" id="dot-rozvidka"></span>Rozvidka agent</td>
            <td><span class="badge badge-off" id="st-rozvidka">off</span> <span class="meta" id="pid-rozvidka"></span></td>
            <td class="proc-ctrl col-ctrl">
              <button class="ok" data-action="start_rozvidka" title="Start">▶</button>
              <button class="danger" data-action="stop_rozvidka" title="Stop">■</button>
            </td>
            <td class="proc-role col-role">DeepSeek \u043e\u0431\u0435\u0440\u0442\u0438 · wiki · profit</td>
            <td class="proc-detail" id="det-rozvidka">\u2014</td>
            <td class="proc-link col-link"><a href="/rozvidka.html">rozvidka</a></td>
          </tr>
          <tr data-proc="orch">
            <td class="proc-name"><span class="proc-dot off" id="dot-orch"></span>Orch</td>
            <td><span class="badge badge-off" id="st-orch">off</span> <span class="meta" id="pid-orch"></span></td>
            <td class="proc-ctrl col-ctrl">
              <button class="ok" data-action="start_orch" title="Start">▶</button>
              <button class="danger" data-action="stop_orch" title="Stop">■</button>
            </td>
            <td class="proc-role col-role">Спить · шина подій · рестарт · звіти мережі</td>
            <td class="proc-detail" id="det-orch">\u2014</td>
            <td class="proc-link col-link"><a href="#procs">swarm</a></td>
          </tr>
        </tbody>
      </table>
      <div class="row" style="padding:12px 14px;border-top:1px solid var(--line);flex-wrap:wrap">
        <button class="primary" data-action="start_all_full">Start ALL (full)</button>
        <button class="danger" data-action="stop_all_full">Stop ALL (full)</button>
        <button class="primary" data-action="start_all">Start system</button>
        <button class="danger" data-action="stop_all">Stop system</button>
        <button data-action="test_telegram">Test TG</button>
        <button data-action="intel_hubs">Intel hubs</button>
        <button data-action="intel_once">Intel once</button>
        <button data-action="rozvidka_once">Roz once</button>
        <button data-action="rebuild_panel">Refresh panel</button>
        <span class="meta" id="procHint">/api/status · ~4s · agents ~8s</span>
      </div>
    </div>
  </section>

  <section id="agents">
    <h2>Agents · live · включатели</h2>
    <div class="grid-2">
      <div class="card live-panel">
        <div class="live-head">
          <h3 style="margin:0">Intel collect</h3>
          <div class="row">
            <button class="ok" data-action="start_intel_2h">▶ 2h</button>
            <button class="ok" data-action="start_intel_12h">▶ 12h</button>
            <button class="ok" data-action="start_intel">▶ resume</button>
            <button class="danger" data-action="stop_intel">■</button>
            <button data-action="intel_once">once</button>
            <button data-action="intel_hubs">hubs</button>
            <button data-action="intel_ui">ui</button>
            <a class="btn" href="/intel.html">intel.html</a>
          </div>
        </div>
        <div id="intelLiveBody"><div class="live-empty">loading /api/intel …</div></div>
      </div>
      <div class="card live-panel">
        <div class="live-head">
          <h3 style="margin:0">Rozvidka agent</h3>
          <div class="row">
            <button class="ok" data-action="start_rozvidka">▶ start</button>
            <button class="danger" data-action="stop_rozvidka">■ stop</button>
            <button data-action="rozvidka_once">once</button>
            <button data-action="rozvidka_once_nolm">once no-LLM</button>
            <button data-action="rozvidka_ui">ui</button>
            <a class="btn" href="/rozvidka.html">rozvidka.html</a>
          </div>
        </div>
        <div id="rozLiveBody"><div class="live-empty">loading /api/rozvidka …</div></div>
      </div>
    </div>
  </section>

  <section id="cycles">
    <h2><span data-i18n="h2_cycles">{T('h2_cycles')}</span>
      <span class="help" data-i18n-tip="tip_cycles_h2" data-tip="{TIP('tip_cycles_h2')}">?</span>
    </h2>
    <div class="grid">
      <div class="card">
        <h3><span data-i18n="h3_scan">{T('h3_scan')}</span> <span class="help" data-i18n-tip="tip_scan" data-tip="{TIP('tip_scan')}">?</span></h3>
        <div class="kpi" id="kpiPct">{_esc(pct)}%<small> \u00b7 {_esc(progress.get('done'))}/{_esc(progress.get('total'))}</small></div>
        <div class="pbar"><i id="progBar" style="width:{pct_w}%"></i></div>
        <div class="meta" id="progLabel">last={_esc(progress.get('last_token'))}</div>
        <p class="btn-hint" data-i18n="scan_hint">{T('scan_hint')}</p>
      </div>
      <div class="card">
        <h3><span data-i18n="h3_cycle">{T('h3_cycle')}</span> <span class="help" data-i18n-tip="tip_cycle_card" data-tip="{TIP('tip_cycle_card')}">?</span></h3>
        <div class="kpi">{_esc(cycles.get('cycles'))}<small> cycles</small></div>
        <div class="meta">age <span id="cycleAge">{_esc(cycles.get('age_sec'))}</span>s \u00b7 stale&gt;{_esc(cycles.get('stale_after_sec'))}s</div>
        <div class="meta">expand_q={_esc(cycles.get('expand_queue'))} \u00b7 pass2={_esc(cycles.get('pass2_tokens'))}</div>
        <ul class="issues" id="cycleIssues">{issues_html}</ul>
      </div>
      <div class="card">
        <h3><span data-i18n="h3_procs">{T('h3_procs')}</span> <span class="help" data-i18n-tip="tip_procs" data-tip="{TIP('tip_procs', min=MIN_SCORE)}">?</span></h3>
        <div class="row" style="gap:10px">
          <span class="term" data-i18n-tip="tip_dwf" data-tip="{TIP('tip_dwf')}">DWF</span>
          <span id="dwfBadge" class="badge badge-off">off</span>
          <span class="term" data-i18n-tip="tip_prep_badge" data-tip="{TIP('tip_prep_badge')}">Prep</span>
          <span id="prepBadge" class="badge badge-off">off</span>
          <span class="term" data-i18n-tip="tip_scan_badge" data-tip="{TIP('tip_scan_badge')}">Scan</span>
          <span id="scanBadge" class="badge badge-off">off</span>
        </div>
        <div class="status-line" id="procLine">\u2014</div>
      </div>
      <div class="card">
        <h3>Agents · цикли</h3>
        <div class="row" style="gap:10px">
          <span>Intel</span>
          <span id="intelBadge" class="badge badge-off">off</span>
          <span>Rozvidka</span>
          <span id="rozBadge" class="badge badge-off">off</span>
        </div>
        <div class="meta" id="intelLine">intel: \u2014</div>
        <div class="meta" id="rozLine">rozvidka: \u2014</div>
        <div class="meta" id="orchLine">орк: \u2014</div>
        <div class="row" style="margin-top:8px">
          <button class="ok" data-action="start_intel">Intel start</button>
          <button class="danger" data-action="stop_intel">Intel stop</button>
          <button data-action="intel_once">Intel once</button>
          <button class="ok" data-action="start_rozvidka">Roz start</button>
          <button class="danger" data-action="stop_rozvidka">Roz stop</button>
          <button class="ok" data-action="start_orch">Orch start</button>
          <button class="danger" data-action="stop_orch">Orch stop</button>
        </div>
        <p class="btn-hint">Durable cycles: crash/restart resumes queue. Orch wakes voice on new signal. <a href="/intel.html">intel.html</a> · <a href="/rozvidka.html">rozvidka.html</a></p>
      </div>
    </div>
  </section>

  <section id="launch">
    <h2><span data-i18n="h2_launch">{T('h2_launch')}</span> <span class="help" data-i18n-tip="tip_launch_h2" data-tip="{TIP('tip_launch_h2')}">?</span></h2>
    <div class="grid">
      <div class="card">
        <h3 data-i18n="h3_all">{T('h3_all')}</h3>
        <p class="meta" data-i18n="all_meta">{T('all_meta')}</p>
        <div class="ctrl-grid">
          <button class="primary" data-action="start_all_full">Start ALL (full)</button>
          <button class="danger" data-action="stop_all_full">Stop ALL (full)</button>
          <button class="primary" data-action="start_all" data-i18n="btn_start_all" data-i18n-tip="tip_start_all" data-tip="{TIP('tip_start_all')}">{T('btn_start_all')}</button>
          <button class="danger" data-action="stop_all" data-i18n="btn_stop_all" data-i18n-tip="tip_stop_all" data-tip="{TIP('tip_stop_all')}">{T('btn_stop_all')}</button>
          <button data-action="test_telegram" data-i18n="btn_test_tg" data-i18n-tip="tip_test_tg" data-tip="{TIP('tip_test_tg')}">{T('btn_test_tg')}</button>
        </div>
        <div class="status-line" id="sysOut">\u2014</div>
      </div>
      <div class="card">
        <h3><span data-i18n="h3_monitors">{T('h3_monitors')}</span> <span class="help" data-i18n-tip="tip_monitors" data-tip="{TIP('tip_monitors')}">?</span></h3>
        <div class="row">
          <button class="ok" data-action="start_dwf" data-i18n-tip="tip_start_dwf" data-tip="{TIP('tip_start_dwf')}">DWF start</button>
          <button class="danger" data-action="stop_dwf">DWF stop</button>
          <button class="ok" data-action="start_prep" data-i18n-tip="tip_start_prep" data-tip="{TIP('tip_start_prep')}">Prep start</button>
          <button class="danger" data-action="stop_prep">Prep stop</button>
        </div>
        <p class="btn-hint" data-i18n="monitors_hint">{T('monitors_hint')}</p>
      </div>
      <div class="card">
        <h3><span data-i18n="h3_scanner">{T('h3_scanner')}</span> <span class="help" data-i18n-tip="tip_scanner_card" data-tip="{TIP('tip_scanner_card')}">?</span></h3>
        <div class="ctrl-grid">
          <button class="primary" data-action="start_scanner" data-i18n-tip="tip_start_scanner" data-tip="{TIP('tip_start_scanner')}">Scanner start</button>
          <button class="danger" data-action="stop_scanner">Scanner stop</button>
          <button data-action="backfill_signals" data-i18n="btn_backfill" data-i18n-tip="tip_backfill" data-tip="{TIP('tip_backfill')}">{T('btn_backfill')}</button>
          <button data-action="rebuild_hub" data-i18n="btn_hub" data-i18n-tip="tip_hub_btn" data-tip="{TIP('tip_hub_btn')}">{T('btn_hub')}</button>
          <button data-action="graph_html">Graph HTML</button>
          <button data-action="run_prep">Run prep scan</button>
          <button data-action="run_deployers">Deployers</button>
          <button data-action="run_scans">Prep+Deployers</button>
          <button data-action="rebuild_panel" data-i18n="btn_panel" data-i18n-tip="tip_panel_btn" data-tip="{TIP('tip_panel_btn')}">{T('btn_panel')}</button>
          <button data-action="check_cycles" data-i18n="btn_check" data-i18n-tip="tip_check" data-tip="{TIP('tip_check')}">{T('btn_check')}</button>
        </div>
        <div class="status-line" id="jobOut">\u2014</div>
      </div>
      <div class="card">
        <h3>Intel · Rozvidka</h3>
        <p class="meta">Collect cycles + DeepSeek agent · durable resume</p>
        <div class="ctrl-grid">
          <button class="ok" data-action="start_intel_2h">Intel 2h</button>
          <button class="ok" data-action="start_intel_12h">Intel 12h</button>
          <button class="ok" data-action="start_intel">Intel resume</button>
          <button class="danger" data-action="stop_intel">Intel stop</button>
          <button data-action="intel_once">Intel once</button>
          <button data-action="intel_hubs">Intel hubs</button>
          <button data-action="intel_ui">Intel ui</button>
          <button class="ok" data-action="start_rozvidka">Roz start</button>
          <button class="danger" data-action="stop_rozvidka">Roz stop</button>
          <button data-action="rozvidka_once">Roz once</button>
          <button data-action="rozvidka_once_nolm">Roz no-LLM</button>
          <button data-action="rozvidka_ui">Roz ui</button>
        </div>
        <p class="btn-hint"><a href="#agents">Live view</a> · <a href="/intel.html">intel.html</a> · <a href="/rozvidka.html">rozvidka.html</a></p>
      </div>
    </div>
  </section>

  <section id="gloss">
    <details class="gloss" open>
      <summary data-i18n="gloss_summary">{T('gloss_summary')}</summary>
      <dl>
        <dt data-i18n="g_mcap_dt">{T('g_mcap_dt')}</dt>
        <dd data-i18n="g_mcap_dd">{T('g_mcap_dd')}</dd>
        <dt data-i18n="g_score_dt">{T('g_score_dt')}</dt>
        <dd data-i18n="g_score_dd">{T('g_score_dd', min=MIN_SCORE, watch=WATCH_SCORE)}</dd>
        <dt data-i18n="g_mm_dt">{T('g_mm_dt')}</dt>
        <dd data-i18n="g_mm_dd">{T('g_mm_dd')}</dd>
        <dt data-i18n="g_cex_dt">{T('g_cex_dt')}</dt>
        <dd data-i18n="g_cex_dd">{T('g_cex_dd')}</dd>
        <dt data-i18n="g_dep_dt">{T('g_dep_dt')}</dt>
        <dd data-i18n="g_dep_dd">{T('g_dep_dd')}</dd>
        <dt data-i18n="g_exp_dt">{T('g_exp_dt')}</dt>
        <dd data-i18n="g_exp_dd">{T('g_exp_dd')}</dd>
        <dt data-i18n="g_hop_dt">{T('g_hop_dt')}</dt>
        <dd data-i18n="g_hop_dd">{T('g_hop_dd')}</dd>
        <dt data-i18n="g_br_dt">{T('g_br_dt')}</dt>
        <dd data-i18n="g_br_dd">{T('g_br_dd')}</dd>
        <dt data-i18n="g_match_dt">{T('g_match_dt')}</dt>
        <dd data-i18n="g_match_dd">{T('g_match_dd')}</dd>
        <dt data-i18n="g_ath_dt">{T('g_ath_dt')}</dt>
        <dd data-i18n="g_ath_dd">{T('g_ath_dd')}</dd>
        <dt data-i18n="g_prep_dt">{T('g_prep_dt')}</dt>
        <dd data-i18n="g_prep_dd">{T('g_prep_dd')}</dd>
        <dt data-i18n="g_hub_dt">{T('g_hub_dt')}</dt>
        <dd data-i18n="g_hub_dd">{T('g_hub_dd')}</dd>
        <dt data-i18n="g_cyc_dt">{T('g_cyc_dt')}</dt>
        <dd data-i18n="g_cyc_dd">{T('g_cyc_dd')}</dd>
        <dt data-i18n="g_noise_dt">{T('g_noise_dt')}</dt>
        <dd data-i18n="g_noise_dd">{T('g_noise_dd')}</dd>
        <dt data-i18n="g_pass2_dt">{T('g_pass2_dt')}</dt>
        <dd data-i18n="g_pass2_dd">{T('g_pass2_dd')}</dd>
      </dl>
    </details>
  </section>

  <section id="reports">
    <h2><span data-i18n="h2_reports">{T('h2_reports')}</span> <span class="help" data-i18n-tip="tip_reports" data-tip="{TIP('tip_reports')}">?</span></h2>
    <div class="grid" id="reportsGrid">
      <a class="report" href="/reports/signals_hub.html" data-key="hub" data-i18n-tip="tip_rep_hub" data-tip="{TIP('tip_rep_hub')}">
        <span class="tag t1">\u2605</span><h3>Signals Hub</h3><p class="meta" data-i18n="rep_hub">{T('rep_hub')}</p></a>
      <a class="report" href="/intel.html" data-key="intel" data-tip="Intel — Solana+BNB families, queue, cycles">
        <span class="tag t1">I</span><h3>Intel UI</h3><p class="meta">Live collect · families · queue</p></a>
      <a class="report" href="/rozvidka.html" data-key="rozvidka" data-tip="DeepSeek оберти · вікі адрес · групи для пампа">
        <span class="tag t1">R</span><h3>Розвідка</h3><p class="meta">DeepSeek · wiki · groups</p></a>
      <a class="report" href="/reports/graph_live.html" data-key="graph" data-i18n-tip="tip_rep_graph" data-tip="{TIP('tip_rep_graph')}">
        <span class="tag t1">0</span><h3>Graph live</h3><p class="meta" data-i18n="rep_graph">{T('rep_graph')}</p></a>
      <a class="report" href="/reports/deployer_trace.html" data-key="deployer" data-i18n-tip="tip_rep_dep" data-tip="{TIP('tip_rep_dep')}">
        <span class="tag t3">1</span><h3>Deployer trace</h3><p class="meta" data-i18n="rep_dep">{T('rep_dep')}</p></a>
      <a class="report" href="/reports/pump_prep_report.html" data-key="prep" data-i18n-tip="tip_rep_prep" data-tip="{TIP('tip_rep_prep')}">
        <span class="tag t3">2</span><h3>Prep report</h3><p class="meta" data-i18n="rep_prep">{T('rep_prep')}</p></a>
      <a class="report" href="/reports/mm_pump_dump_watchlist.html" data-key="mm" data-i18n-tip="tip_rep_mm" data-tip="{TIP('tip_rep_mm')}">
        <span class="tag t2">3</span><h3>MM watchlist</h3><p class="meta" data-i18n="rep_mm">{T('rep_mm')}</p></a>
      <a class="report" href="/cycles_health.json" data-key="cycles" data-i18n-tip="tip_rep_cycles" data-tip="{TIP('tip_rep_cycles')}">
        <span class="tag t4">JSON</span><h3>cycles_health.json</h3><p class="meta" data-i18n="rep_cycles">{T('rep_cycles')}</p></a>
      <a class="report" href="/reports/tokens_mcap_350k_60m.html" data-key="tokens_350k" data-tip="Tokens $350K–$60M">
        <span class="tag t4">$</span><h3>Tokens 350K–60M</h3><p class="meta">mcap band scan</p></a>
      <a class="report" href="/reports/tokens_mcap_3m_800m.html" data-key="tokens_3m" data-tip="Tokens $3M–$800M">
        <span class="tag t4">$$</span><h3>Tokens 3M–800M</h3><p class="meta">mcap band scan</p></a>
      <a class="report" href="/reports/crypto_funds_report.html" data-key="funds" data-tip="Crypto funds tracker">
        <span class="tag t4">F</span><h3>Crypto funds</h3><p class="meta">funds report</p></a>
      <a class="report" href="/intel_cycles_health.json" data-key="intel_cycles" data-tip="Intel agent cycle health">
        <span class="tag t4">JSON</span><h3>intel_cycles_health.json</h3><p class="meta">Intel cycles</p></a>
      <a class="report" href="/rozvidka_cycles_health.json" data-key="rozvidka_cycles" data-tip="Rozvidka agent cycle health">
        <span class="tag t4">JSON</span><h3>rozvidka_cycles_health.json</h3><p class="meta">Rozvidka cycles</p></a>
    </div>
  </section>
</main>
<div id="toast"></div>
<script>{_script(snap_json, i18n_json, lang)}</script>
</body>
</html>
"""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "dashboard.html"
    path.write_text(doc, encoding="utf-8")
    try:
        from pump_prep.i18n_ui import write_static_packs

        write_static_packs(OUT)
    except Exception:
        pass
    return str(path)


def _script(snap_json: str, i18n_json: str, lang: str) -> str:
    return (
        _SCRIPT.replace("@@SNAP_JSON@@", snap_json)
        .replace("@@I18N_JSON@@", i18n_json)
        .replace("@@LANG_KEY@@", STORAGE_KEY)
        .replace("@@DEFAULT_LANG@@", lang)
    )
