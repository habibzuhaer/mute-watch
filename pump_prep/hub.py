"""Signals hub — one HTML that links progress, signals, clusters, trades.

Bilingual (EN default / UK toggle) — text comes from pump_prep.i18n_ui.UI,
same localStorage key (mute_lang) and toggle UX as the dashboard.
"""

from __future__ import annotations

import html as html_mod
import json
from datetime import datetime, timezone
from typing import Any

from pump_prep import graph_store as gs
from pump_prep.clusters import build_deployer_clusters, trade_stats
from pump_prep.config import OUT_DIR
from pump_prep.cycles import enrich_signal_money
from pump_prep.i18n_ui import DEFAULT_LANG, STORAGE_KEY, normalize_lang, packs_json, t
from pump_prep.labels import load_known
from pump_prep.signals import MIN_SCORE, WATCH_SCORE

_TIER_KEY = {"actionable": "tier_act", "watch": "tier_watch", "noise": "tier_noise"}
_TIER_CLASS = {"actionable": "go", "watch": "wa", "noise": "no"}


def _esc(x: Any) -> str:
    return html_mod.escape("" if x is None else str(x))


def _ts_chain(t_: Any) -> str:
    if not t_:
        return "—"
    try:
        return datetime.fromtimestamp(int(t_), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(t_)


def write_hub_html() -> str:
    lang = normalize_lang(DEFAULT_LANG)

    def T(key: str, **fmt: Any) -> str:
        return _esc(t(lang, key, **fmt))

    def TIP(key: str, **fmt: Any) -> str:
        return _esc(t(lang, key, **fmt)).replace("\n", "&#10;")

    progress = gs.progress_snapshot()
    clusters = build_deployer_clusters()
    trades = trade_stats()
    known = load_known()
    signals = [enrich_signal_money(s) for s in gs.read_jsonl_tail(gs.SIGNAL_FILE, 200)]
    actionable = [s for s in signals if s.get("tier") == "actionable"]
    watch = [s for s in signals if s.get("tier") == "watch"]
    actionable.sort(key=lambda s: (-(s.get("score") or 0), -(s.get("mcap") or 0), s.get("saved_at") or ""))
    watch.sort(key=lambda s: (-(s.get("score") or 0), -(s.get("mcap") or 0), s.get("saved_at") or ""))

    pct = progress.get("pct") or 0
    bar_w = max(0, min(100, float(pct)))
    tiers = progress.get("signals_by_tier") or {}
    min1 = MIN_SCORE - 1

    def tier_badge(tier: str, score: Any) -> str:
        key = _TIER_KEY.get(tier, "tier_noise")
        cls = _TIER_CLASS.get(tier, "no")
        label = t(lang, key)
        return f"<span class='tb {cls}'><span data-i18n='{key}'>{_esc(label)}</span> · {_esc(score)}/100</span>"

    def reasons_cell(rs_en: Any, rs_uk: Any) -> str:
        items_en = list(rs_en or [])[:5]
        items_uk = list(rs_uk or [])[:5]
        show = items_uk if (lang == "uk" and items_uk) else items_en
        html_items = "".join(f"<li>{_esc(r)}</li>" for r in show) or "<li>—</li>"
        data_en = _esc(json.dumps(items_en, ensure_ascii=False))
        data_uk = _esc(json.dumps(items_uk, ensure_ascii=False))
        return f"<td data-reasons=\"{data_en}\" data-reasons-uk=\"{data_uk}\"><ul>{html_items}</ul></td>"

    sig_rows = []
    for s in (actionable + watch)[:60]:
        band = s.get("money_band") or "unknown"
        mcap_v = "" if s.get("mcap") is None else s.get("mcap")
        sig_rows.append(
            f"<tr class='{s.get('tier')}' data-band='{_esc(band)}' data-mcap='{_esc(mcap_v)}'>"
            f"<td>{tier_badge(s.get('tier') or '', s.get('score'))}</td>"
            f"<td><b>{_esc(s.get('symbol'))}</b>"
            f"<div class='sub'>{_esc(s.get('signal_kind') or '')}</div></td>"
            f"<td class='num' data-i18n-tip='tip_mcap_card' data-tip='{TIP('tip_mcap_card')}'>{_esc(s.get('mcap_fmt') or '—')}</td>"
            f"<td>{_esc(s.get('direction'))} → {_esc(s.get('match_entity'))}</td>"
            f"<td>{_esc(_ts_chain(s.get('timestamp')))}</td>"
            f"{reasons_cell(s.get('reasons'), s.get('reasons_uk'))}"
            f"<td class='act'>"
            f"<button type='button' data-trade='enter' data-symbol='{_esc(s.get('symbol'))}' "
            f"data-score='{_esc(s.get('score'))}' data-tier='{_esc(s.get('tier'))}' "
            f"data-entity='{_esc(s.get('match_entity'))}' data-kind='{_esc(s.get('signal_kind'))}' "
            f"data-i18n='hub_btn_enter'>{T('hub_btn_enter')}</button> "
            f"<button type='button' data-trade='watch' data-symbol='{_esc(s.get('symbol'))}' "
            f"data-score='{_esc(s.get('score'))}' data-tier='{_esc(s.get('tier'))}' "
            f"data-entity='{_esc(s.get('match_entity'))}' data-kind='{_esc(s.get('signal_kind'))}' "
            f"data-i18n='hub_btn_watch'>{T('hub_btn_watch')}</button> "
            f"<button type='button' data-trade='skip' data-symbol='{_esc(s.get('symbol'))}' "
            f"data-score='{_esc(s.get('score'))}' data-tier='{_esc(s.get('tier'))}' "
            f"data-entity='{_esc(s.get('match_entity'))}' data-kind='{_esc(s.get('signal_kind'))}' "
            f"data-i18n='hub_btn_skip'>{T('hub_btn_skip')}</button>"
            f"</td></tr>"
        )

    cl_rows = []
    for c in (clusters.get("clusters") or [])[:30]:
        if c.get("token_count", 0) < 1:
            continue
        flag = ""
        if c.get("pump_count"):
            flag = (
                "<span class='tb wa'><span data-i18n='hub_flag_pump_label'>"
                + T("hub_flag_pump_label")
                + "</span>\u00d7" + _esc(c.get("pump_count")) + "</span> "
            )
        if c.get("token_count", 0) >= 2:
            flag += f"<span class='tb go' data-i18n='hub_flag_repeat'>{T('hub_flag_repeat')}</span>"
        cl_rows.append(
            f"<tr>"
            f"<td class='mono' title='{_esc(c.get('deployer'))}'>{_esc((c.get('deployer') or '')[:10])}…</td>"
            f"<td class='num'>{_esc(c.get('token_count'))}</td>"
            f"<td class='num'>{_esc(c.get('pump_count'))}</td>"
            f"<td class='num'>{_esc(c.get('score_hint'))}</td>"
            f"<td>{_esc(', '.join(c.get('symbols') or [])[:80])}</td>"
            f"<td>{flag}</td>"
            f"</tr>"
        )

    tr_rows = []
    for tr in trades.get("recent") or []:
        tr_rows.append(
            f"<tr>"
            f"<td>{_esc(tr.get('action'))}</td>"
            f"<td><b>{_esc(tr.get('symbol'))}</b></td>"
            f"<td>{_esc(tr.get('score'))}</td>"
            f"<td>{_esc(tr.get('match_entity'))}</td>"
            f"<td>{_esc(tr.get('note'))}</td>"
            f"<td>{_esc(tr.get('result') or '—')}</td>"
            f"<td class='sub'>{_esc((tr.get('saved_at') or '')[:19])}</td>"
            f"</tr>"
        )

    role_counts: dict[str, int] = {}
    for v in known.values():
        r = v.get("role") or "?"
        role_counts[r] = role_counts.get(r, 0) + 1
    roles_html = " · ".join(f"{_esc(k)}:{v}" for k, v in sorted(role_counts.items(), key=lambda x: -x[1]))

    en_active = " active" if lang == "en" else ""
    uk_active = " active" if lang == "uk" else ""

    i18n_json = packs_json().replace("</", "<\\/")

    doc = f"""<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta http-equiv="refresh" content="90"/>
<title data-i18n="hub_title">{T('hub_title')}</title>
<style>
:root {{ --bg:#0c0e12; --panel:#151922; --text:#e8eaed; --muted:#9aa0a6; --line:#2a2f3a;
  --ok:#3dd68c; --warn:#e6b84d; --accent:#7cb3ff; }}
body {{ margin:0; font:14px/1.45 ui-sans-serif,system-ui,sans-serif; background:var(--bg); color:var(--text); }}
header {{ padding:14px 22px 0; border-bottom:1px solid var(--line); position:relative; background:transparent; z-index:1; }}
.header-top {{ display:flex; flex-wrap:wrap; gap:10px 16px; align-items:flex-start; justify-content:space-between; }}
.header-copy {{ min-width:0; flex:1; }}
h1 {{ margin:0 0 6px; font-size:20px; }} h2 {{ margin:22px 0 8px; font-size:15px; scroll-margin-top:110px; }}
.tip,.stats,.sub {{ color:var(--muted); font-size:12px; }}
.stats {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:8px; }}
.bar {{ height:12px; background:#222833; border-radius:6px; max-width:640px; overflow:hidden; margin:10px 0 4px; }}
.bar>i {{ display:block; height:100%; width:{bar_w}%; background:var(--ok); }}
.row {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
.lang-toggle {{ flex:0 0 auto; }}
.lang-btn {{ padding:6px 10px; font-size:12px; font-weight:700; }}
.lang-btn.active {{ background:#243044; border-color:#3a5080; color:#cfe0ff; }}
nav.menu {{
  display:flex; flex-wrap:wrap; gap:6px; align-items:center;
  padding:8px 0 12px; border-top:1px solid var(--line); margin-top:10px;
}}
nav.menu a {{
  color:var(--muted); text-decoration:none; font-size:12px; font-weight:650;
  padding:6px 10px; border-radius:8px; border:1px solid transparent; white-space:nowrap;
}}
nav.menu a:hover {{ color:var(--text); background:#1b2030; border-color:var(--line); }}
nav.menu a.home {{ color:#cfe0ff; background:#243044; border-color:#3a5080; }}
nav.menu .sep {{ width:1px; height:18px; background:var(--line); margin:0 4px; }}
.wrap {{ padding:12px 18px 48px; overflow:auto; }}
table {{ width:100%; border-collapse:collapse; min-width:960px; }}
th,td {{ padding:7px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
th {{ background:#1b2030; color:var(--muted); font-size:11px; text-transform:uppercase; }}
td.num,.mono {{ font-family:ui-monospace,Menlo,monospace; }}
td.num {{ text-align:right; }}
.tb {{ display:inline-block; padding:2px 8px; border-radius:6px; font-size:11px; font-weight:700; }}
.tb.go {{ background:rgba(61,214,140,.2); color:var(--ok); }}
.tb.wa {{ background:rgba(230,184,77,.18); color:var(--warn); }}
.tb.no {{ background:#2a2f3a; color:var(--muted); }}
tr.actionable td {{ background:rgba(61,214,140,.08); }}
tr.watch td {{ background:rgba(230,184,77,.05); }}
ul {{ margin:0; padding-left:16px; color:var(--muted); font-size:12px; }}
.links a {{ color:var(--accent); margin-right:14px; }}
button {{ appearance:none; border:1px solid var(--line); background:#1b2030; color:var(--text);
  border-radius:6px; padding:4px 8px; font:inherit; font-size:11px; cursor:pointer; margin:1px; }}
button:hover {{ border-color:var(--accent); }}
#toast {{ position:fixed; right:14px; bottom:14px; background:#1b2030; border:1px solid var(--line);
  padding:10px 12px; border-radius:8px; display:none; max-width:360px; font-size:12px; }}
.flow {{ margin:8px 0; color:var(--muted); font-size:12px; }}
.flow b {{ color:var(--text); }}
[data-tip] {{ position:relative; cursor:help; }}
[data-tip]::after {{
  content: attr(data-tip); position:absolute; left:0; bottom:calc(100% + 8px); z-index:40;
  min-width:220px; max-width:340px; padding:9px 11px; border-radius:8px;
  background:#0b0d12; color:#d7dbe2; border:1px solid #3a4252; font-size:12px; font-weight:400; line-height:1.4;
  opacity:0; pointer-events:none; white-space:pre-line; box-shadow:0 8px 20px rgba(0,0,0,.4);
}}
[data-tip]:hover::after {{ opacity:1; }}
.help {{ display:inline-flex; width:15px; height:15px; align-items:center; justify-content:center; border-radius:50%; border:1px solid var(--line); color:var(--muted); font-size:10px; font-weight:700; margin-left:5px; cursor:help; vertical-align:middle; }}
.gloss {{ background:#151922; border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin:14px 0 22px; }}
.gloss summary {{ cursor:pointer; font-weight:650; }}
.gloss dl {{ display:grid; grid-template-columns:minmax(100px,150px) 1fr; gap:6px 12px; margin:10px 0 0; }}
.gloss dt {{ color:var(--accent); font-weight:650; font-size:12px; }}
.gloss dd {{ margin:0; color:var(--muted); font-size:12px; }}
.term {{ border-bottom:1px dotted rgba(154,160,166,.45); }}
.filters {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:10px 0 14px; padding:10px 12px; background:#151922; border:1px solid var(--line); border-radius:10px; }}
.filters label {{ color:var(--muted); font-size:12px; font-weight:650; }}
.filters select, .filters input {{ background:#1b2030; color:var(--text); border:1px solid var(--line); border-radius:8px; padding:6px 10px; font:inherit; font-size:13px; }}
.filters .hint {{ color:var(--muted); font-size:11px; }}
td.num {{ font-variant-numeric: tabular-nums; }}
</style></head><body>
<header>
  <div class="header-top">
    <div class="header-copy">
      <h1 data-i18n="hub_h1">{T('hub_h1')} <span class="help" data-i18n-tip="hub_tip_h1" data-tip="{TIP('hub_tip_h1')}">?</span></h1>
      <p class="tip">
        <span data-i18n="hub_meta_scan">{T('hub_meta_scan')}</span> →
        <span class="term" data-i18n="hub_term_score_why" data-i18n-tip="hub_tip_score_why" data-tip="{TIP('hub_tip_score_why')}">{T('hub_term_score_why')}</span> →
        <span class="term" data-i18n="hub_term_clusters" data-i18n-tip="hub_tip_clusters" data-tip="{TIP('hub_tip_clusters')}">{T('hub_term_clusters')}</span> →
        <span class="term" data-i18n="hub_term_journal" data-i18n-tip="hub_tip_journal" data-tip="{TIP('hub_tip_journal')}">{T('hub_term_journal')}</span>.
        <span data-i18n="hub_meta_tg">{T('hub_meta_tg', min=MIN_SCORE)}</span>
      </p>
    </div>
    <div class="row lang-toggle" role="group" aria-label="Language">
      <button type="button" class="btn lang-btn{en_active}" data-lang="en" data-i18n="lang_en" data-i18n-tip="lang_tip" data-tip="{TIP('lang_tip')}">{T('lang_en')}</button>
      <button type="button" class="btn lang-btn{uk_active}" data-lang="uk" data-i18n="lang_uk" data-i18n-tip="lang_tip" data-tip="{TIP('lang_tip')}">{T('lang_uk')}</button>
    </div>
  </div>
  <div class="bar"><i></i></div>
  <div class="stats">
    <span data-i18n-tip="hub_stat_pct_tip" data-tip="{TIP('hub_stat_pct_tip')}"><b>{_esc(pct)}%</b> · {_esc(progress.get('done'))}/{_esc(progress.get('total'))}</span>
    <span data-i18n-tip="hub_tip_tiers" data-tip="{TIP('hub_tip_tiers', min=MIN_SCORE, watch=WATCH_SCORE)}">
      <span data-i18n="tier_act">{T('tier_act')}</span> {_esc(tiers.get('actionable',0))} ·
      <span data-i18n="tier_watch">{T('tier_watch')}</span> {_esc(tiers.get('watch',0))} ·
      <span data-i18n="tier_noise">{T('tier_noise')}</span> {_esc(tiers.get('noise',0))}
    </span>
    <span data-i18n-tip="hub_stat_clusters_tip" data-tip="{TIP('hub_stat_clusters_tip')}">
      <span data-i18n="hub_word_clusters">{T('hub_word_clusters')}</span> {_esc(clusters.get('cluster_count'))} ·
      <span data-i18n="hub_word_repeat">{T('hub_word_repeat')}</span> {_esc(clusters.get('repeat_deployers'))} ·
      <span data-i18n="hub_word_pumpdep">{T('hub_word_pumpdep')}</span> {_esc(clusters.get('pump_deployers'))}
    </span>
    <span data-i18n-tip="hub_stat_labels_tip" data-tip="{TIP('hub_stat_labels_tip')}"><span data-i18n="hub_stat_labels_prefix">{T('hub_stat_labels_prefix')}</span> {roles_html}</span>
    <span data-i18n-tip="hub_stat_trades_tip" data-tip="{TIP('hub_stat_trades_tip')}"><span data-i18n="hub_stat_trades_prefix">{T('hub_stat_trades_prefix')}</span> {_esc(trades.get('total'))}</span>
    <span data-i18n-tip="hub_stat_last_tip" data-tip="{TIP('hub_stat_last_tip')}"><span data-i18n="hub_stat_last_prefix">{T('hub_stat_last_prefix')}</span> {_esc(progress.get('last_token'))}</span>
  </div>
  <p class="flow"><b data-i18n="hub_funnel_label">{T('hub_funnel_label')}</b>
    <span class="term" data-i18n="hub_funnel_term_match" data-i18n-tip="hub_tip_match" data-tip="{TIP('hub_tip_match')}">{T('hub_funnel_term_match')}</span> →
    <span data-i18n="hub_funnel_check">{T('hub_funnel_check')}</span>
    <span class="term" data-i18n="hub_funnel_term_reasons_ath" data-i18n-tip="hub_tip_reasons_ath" data-tip="{TIP('hub_tip_reasons_ath')}">{T('hub_funnel_term_reasons_ath')}</span> →
    <span class="term" data-i18n="hub_funnel_term_deployer_q" data-i18n-tip="hub_tip_deployer_cluster" data-tip="{TIP('hub_tip_deployer_cluster')}">{T('hub_funnel_term_deployer_q')}</span> →
    <span data-i18n="hub_funnel_journal">{T('hub_funnel_journal')}</span>
    <span class="term" data-i18n="hub_funnel_term_hitrate" data-i18n-tip="hub_tip_hitrate" data-tip="{TIP('hub_tip_hitrate')}">{T('hub_funnel_term_hitrate')}</span></p>
  <nav class="menu" aria-label="Navigation">
    <a class="home" href="/" data-i18n="hub_nav_home" data-i18n-tip="hub_tip_nav_home" data-tip="{TIP('hub_tip_nav_home')}">{T('hub_nav_home')}</a>
    <a href="/launch.html" data-i18n="nav_launch_page" data-i18n-tip="tip_nav_launch_page" data-tip="{TIP('tip_nav_launch_page')}">{T('nav_launch_page')}</a>
    <a href="#signals" data-i18n="hub_nav_signals" data-i18n-tip="hub_tip_nav_signals" data-tip="{TIP('hub_tip_nav_signals')}">{T('hub_nav_signals')}</a>
    <a href="#clusters" data-i18n="hub_nav_clusters" data-i18n-tip="hub_tip_nav_clusters" data-tip="{TIP('hub_tip_nav_clusters')}">{T('hub_nav_clusters')}</a>
    <a href="#journal" data-i18n="hub_nav_journal" data-i18n-tip="hub_tip_nav_journal" data-tip="{TIP('hub_tip_nav_journal')}">{T('hub_nav_journal')}</a>
    <a href="#gloss" data-i18n="nav_gloss" data-i18n-tip="tip_nav_gloss" data-tip="{TIP('tip_nav_gloss')}">{T('nav_gloss')}</a>
    <span class="sep" aria-hidden="true"></span>
    <a href="/reports/graph_live.html" data-i18n-tip="tip_graph" data-tip="{TIP('tip_graph')}">Graph</a>
    <a href="/reports/deployer_trace.html" data-i18n-tip="tip_deployer" data-tip="{TIP('tip_deployer')}">Deployer</a>
    <a href="/reports/mm_pump_dump_watchlist.html" data-i18n-tip="tip_mm" data-tip="{TIP('tip_mm')}">MM</a>
    <a href="/cycles_health.json" data-i18n-tip="tip_cycles_json" data-tip="{TIP('tip_cycles_json')}">cycles.json</a>
  </nav>
</header>
<div class="wrap">
  <details class="gloss" id="gloss" open>
    <summary data-i18n="gloss_summary">{T('gloss_summary')}</summary>
    <dl>
      <dt data-i18n="hub_g_money_dt">{T('hub_g_money_dt')}</dt>
      <dd data-i18n="hub_g_money_dd">{T('hub_g_money_dd')}</dd>
      <dt data-i18n="hub_g_score_dt">{T('hub_g_score_dt')}</dt>
      <dd data-i18n="hub_g_score_dd">{T('hub_g_score_dd', min=MIN_SCORE)}</dd>
      <dt data-i18n="hub_g_dep_dt">{T('hub_g_dep_dt')}</dt>
      <dd data-i18n="hub_g_dep_dd">{T('hub_g_dep_dd')}</dd>
      <dt data-i18n="hub_g_ath_dt">{T('hub_g_ath_dt')}</dt>
      <dd data-i18n="hub_g_ath_dd">{T('hub_g_ath_dd')}</dd>
      <dt data-i18n="hub_g_mm_dt">{T('hub_g_mm_dt')}</dt>
      <dd data-i18n="hub_g_mm_dd">{T('hub_g_mm_dd')}</dd>
      <dt data-i18n="hub_g_journal_dt">{T('hub_g_journal_dt')}</dt>
      <dd data-i18n="hub_g_journal_dd">{T('hub_g_journal_dd')}</dd>
      <dt data-i18n="hub_g_expand_dt">{T('hub_g_expand_dt')}</dt>
      <dd data-i18n="hub_g_expand_dd">{T('hub_g_expand_dd')}</dd>
    </dl>
  </details>

  <h2 id="signals" data-i18n="hub_h2_signals">{T('hub_h2_signals')}
    <span class="help" data-i18n-tip="hub_tip_h2_signals" data-tip="{TIP('hub_tip_h2_signals')}">?</span>
  </h2>
  <div class="filters">
    <label for="moneyBand" data-i18n="money_label">{T('money_label')}</label>
    <select id="moneyBand">
      <option value="any" data-i18n="money_any">{T('money_any')}</option>
      <option value="micro">&lt; $350K</option>
      <option value="small">$350K–$3M</option>
      <option value="mid">$3M–$10M</option>
      <option value="large">$10M–$60M</option>
      <option value="mega">≥ $60M</option>
      <option value="unknown" data-i18n="money_unknown">{T('money_unknown')}</option>
    </select>
    <label for="minMcap" data-i18n="money_min">{T('money_min')}</label>
    <input id="minMcap" type="number" min="0" step="1000" placeholder="0" style="width:110px"/>
    <span class="hint" id="moneyHint" data-i18n="money_hint_all">{T('money_hint_all')}</span>
  </div>
  <table id="sigTable"><thead><tr>
    <th data-i18n="hub_col_score" data-i18n-tip="hub_tip_col_score" data-tip="{TIP('hub_tip_col_score')}">{T('hub_col_score')}</th>
    <th data-i18n="hub_col_token" data-i18n-tip="hub_tip_col_token" data-tip="{TIP('hub_tip_col_token')}">{T('hub_col_token')}</th>
    <th data-i18n="hub_col_mcap" data-i18n-tip="tip_mcap_card" data-tip="{TIP('tip_mcap_card')}">{T('hub_col_mcap')}</th>
    <th data-i18n="hub_col_link" data-i18n-tip="hub_tip_col_link" data-tip="{TIP('hub_tip_col_link')}">{T('hub_col_link')}</th>
    <th data-i18n="hub_col_when" data-i18n-tip="hub_tip_col_when" data-tip="{TIP('hub_tip_col_when')}">{T('hub_col_when')}</th>
    <th data-i18n="hub_col_why" data-i18n-tip="hub_tip_col_why" data-tip="{TIP('hub_tip_col_why')}">{T('hub_col_why')}</th>
    <th data-i18n="hub_col_decision" data-i18n-tip="hub_tip_col_decision" data-tip="{TIP('hub_tip_col_decision')}">{T('hub_col_decision')}</th>
  </tr></thead>
  <tbody>{''.join(sig_rows) or f'<tr><td colspan="7" data-i18n="hub_empty_signals">{T("hub_empty_signals")}</td></tr>'}</tbody></table>

  <h2 id="clusters" data-i18n="hub_h2_clusters">{T('hub_h2_clusters')}
    <span class="help" data-i18n-tip="hub_tip_h2_clusters" data-tip="{TIP('hub_tip_h2_clusters')}">?</span>
  </h2>
  <p class="tip" data-i18n="hub_clusters_note">{T('hub_clusters_note')}</p>
  <table><thead><tr>
    <th data-i18n="hub_col_deployer" data-i18n-tip="hub_tip_col_deployer" data-tip="{TIP('hub_tip_col_deployer')}">{T('hub_col_deployer')}</th>
    <th data-i18n="hub_col_tokens" data-i18n-tip="hub_tip_col_tokens" data-tip="{TIP('hub_tip_col_tokens')}">{T('hub_col_tokens')}</th>
    <th data-i18n="hub_col_pumps" data-i18n-tip="hub_tip_col_pumps" data-tip="{TIP('hub_tip_col_pumps')}">{T('hub_col_pumps')}</th>
    <th data-i18n="hub_col_hint" data-i18n-tip="hub_tip_col_hint" data-tip="{TIP('hub_tip_col_hint')}">{T('hub_col_hint')}</th>
    <th data-i18n="hub_col_symbols" data-i18n-tip="hub_tip_col_symbols" data-tip="{TIP('hub_tip_col_symbols')}">{T('hub_col_symbols')}</th>
    <th data-i18n="hub_col_flags" data-i18n-tip="hub_tip_col_flags" data-tip="{TIP('hub_tip_col_flags')}">{T('hub_col_flags')}</th>
  </tr></thead>
  <tbody>{''.join(cl_rows) or f'<tr><td colspan="6" data-i18n="hub_empty_clusters">{T("hub_empty_clusters")}</td></tr>'}</tbody></table>

  <h2 id="journal" data-i18n="hub_h2_journal">{T('hub_h2_journal')}
    <span class="help" data-i18n-tip="hub_tip_h2_journal" data-tip="{TIP('hub_tip_h2_journal')}">?</span>
  </h2>
  <table><thead><tr>
    <th data-i18n="hub_col_action" data-i18n-tip="hub_tip_col_action" data-tip="{TIP('hub_tip_col_action')}">{T('hub_col_action')}</th>
    <th data-i18n="hub_col_symbol_j">{T('hub_col_symbol_j')}</th><th data-i18n="hub_col_score_j">{T('hub_col_score_j')}</th>
    <th data-i18n="hub_col_entity">{T('hub_col_entity')}</th><th data-i18n="hub_col_note">{T('hub_col_note')}</th>
    <th data-i18n="hub_col_result" data-i18n-tip="hub_tip_col_result" data-tip="{TIP('hub_tip_col_result')}">{T('hub_col_result')}</th>
    <th data-i18n="hub_col_when_j">{T('hub_col_when_j')}</th>
  </tr></thead>
  <tbody>{''.join(tr_rows) or f'<tr><td colspan="7" data-i18n="hub_empty_journal">{T("hub_empty_journal")}</td></tr>'}</tbody></table>
</div>
<div id="toast"></div>
<script>
const I18N = {i18n_json};
const LANG_KEY = '{STORAGE_KEY}';
const DEFAULT_LANG = '{lang}';
const MIN_SCORE = {MIN_SCORE};
const WATCH_SCORE = {WATCH_SCORE};
let currentLang = DEFAULT_LANG;

function normalizeLang(v) {{
  v = (v || '').toLowerCase().trim();
  if (['ua', 'ukr', 'украинский', 'українська'].includes(v)) return 'uk';
  if (I18N[v]) return v;
  return DEFAULT_LANG;
}}
function t(key, fmt) {{
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
  const FMT = {{ min: MIN_SCORE, watch: WATCH_SCORE, min1: MIN_SCORE - 1 }};
  document.querySelectorAll('[data-i18n]').forEach(el => {{ el.textContent = t(el.dataset.i18n, FMT); }});
  document.querySelectorAll('[data-i18n-tip]').forEach(el => {{ el.setAttribute('data-tip', t(el.dataset.i18nTip, FMT)); }});
  document.querySelectorAll('.lang-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.lang === lang));
  document.title = t('hub_title', FMT);
  applyRowReasons();
  moneyFilterApply();
}}

async function logTrade(btn) {{
  const body = {{
    action: btn.dataset.trade,
    symbol: btn.dataset.symbol,
    score: Number(btn.dataset.score||0),
    tier: btn.dataset.tier,
    match_entity: btn.dataset.entity,
    signal_kind: btn.dataset.kind,
    note: '',
  }};
  try {{
    const r = await fetch('/api/trade', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify(body),
    }});
    const d = await r.json();
    const tt = document.getElementById('toast');
    tt.textContent = d.ok ? ('OK · ' + body.action + ' · ' + body.symbol) : (d.error||'fail');
    tt.style.display = 'block';
    setTimeout(()=> tt.style.display='none', 3500);
    if (d.ok) setTimeout(()=> location.reload(), 800);
  }} catch(e) {{
    alert(t('hub_alert_need_panel'));
  }}
}}
document.querySelectorAll('button[data-trade]').forEach(b => b.addEventListener('click', () => logTrade(b)));

let moneyFilterApply = function() {{}};
(function moneyFilter() {{
  const bandEl = document.getElementById('moneyBand');
  const minEl = document.getElementById('minMcap');
  const hint = document.getElementById('moneyHint');
  const table = document.getElementById('sigTable');
  if (!bandEl || !table) return;
  const ranges = {{
    micro: [0, 350000], small: [350000, 3000000], mid: [3000000, 10000000],
    large: [10000000, 60000000], mega: [60000000, Infinity],
  }};
  function apply() {{
    const band = bandEl.value;
    const minM = minEl && minEl.value !== '' ? Number(minEl.value) : null;
    let shown = 0, total = 0;
    table.querySelectorAll('tbody tr[data-band]').forEach(tr => {{
      total += 1;
      const raw = tr.getAttribute('data-mcap');
      const mcap = raw === '' || raw == null ? null : Number(raw);
      let ok = true;
      if (minM != null && !Number.isNaN(minM) && minM > 0) ok = mcap != null && mcap >= minM;
      if (ok) {{
        if (band === 'unknown') ok = mcap == null || Number.isNaN(mcap);
        else if (band !== 'any') {{
          const r = ranges[band];
          ok = !!r && mcap != null && mcap >= r[0] && mcap < r[1];
        }}
      }}
      tr.style.display = ok ? '' : 'none';
      if (ok) shown += 1;
    }});
    if (hint) hint.textContent = (band === 'any' && !minM) ? t('money_hint_all') : t('hub_money_hint_filter', {{ shown, total }});
  }}
  moneyFilterApply = apply;
  bandEl.addEventListener('change', apply);
  if (minEl) minEl.addEventListener('input', apply);
  const q = new URLSearchParams(location.search);
  if (q.get('money')) bandEl.value = q.get('money');
  if (q.get('min_mcap') && minEl) minEl.value = q.get('min_mcap');
  apply();
}})();

let savedLang = null;
try {{ savedLang = localStorage.getItem(LANG_KEY); }} catch (e) {{}}
applyLang(savedLang || DEFAULT_LANG);
document.querySelectorAll('.lang-btn').forEach(btn => {{
  btn.addEventListener('click', () => applyLang(btn.dataset.lang));
}});
</script>
</body></html>
"""
    from agents.chrome import apply_to_html

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "signals_hub.html"
    path.write_text(apply_to_html(doc, "hub"), encoding="utf-8")
    return str(path)


def rebuild_all() -> dict[str, str]:
    """Refresh clusters + hub + graph_live together."""
    from pump_prep.continuous import write_graph_html

    build_deployer_clusters()
    hub = write_hub_html()
    graph = write_graph_html()
    return {"hub": hub, "graph": graph}
