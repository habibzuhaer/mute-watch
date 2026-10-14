"""Unified address wiki — one snapshot over intel + rozvidka + graph."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.config import ROOT
from agents.frames import attach

logger = logging.getLogger(__name__)

WIKI_DIR = Path(__file__).resolve().parent.parent / "data" / "wiki"
SNAP_FILE = WIKI_DIR / "snapshot.json"
INDEX_MD = WIKI_DIR / "index.md"
FAM_MD = WIKI_DIR / "families.md"
OUT_HTML = ROOT / "out" / "wiki.html"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure() -> None:
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    (WIKI_DIR / "addresses").mkdir(parents=True, exist_ok=True)


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, data: Any) -> None:
    ensure()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _intel_bundle() -> dict[str, Any]:
    base = ROOT / "data" / "intel"
    fam = _load(base / "families.json", {})
    addrs = _load(base / "addresses.json", {})
    if not isinstance(addrs, dict):
        addrs = {}
    families = list((fam.get("families") or []) if isinstance(fam, dict) else [])
    return {"families": families, "addresses": addrs, "stats": (fam.get("stats") if isinstance(fam, dict) else {}) or {}}


def _roz_bundle() -> dict[str, Any]:
    base = ROOT / "data" / "rozvidka" / "db"
    fam = _load(base / "families.json", {})
    addrs = _load(base / "addresses.json", {})
    if not isinstance(addrs, dict):
        addrs = {}
    families = []
    for f in (fam.get("families") or []) if isinstance(fam, dict) else []:
        hub = f.get("hub") or ""
        chain = f.get("chain") or "evm"
        families.append(
            {
                "id": f.get("id") or f"roz_{hub[:8]}",
                "source": "rozvidka",
                "chain": chain,
                "hub": hub,
                "hub_key": f.get("hub_key") or (f"{chain}:{hub}" if hub else ""),
                "short": f.get("hub_short") or f.get("short") or hub[:10],
                "size": f.get("size") or len(f.get("members") or []),
                "members": f.get("members") or [],
                "tokens": (f.get("pump_tokens") or f.get("tokens") or [])[:25],
                "token_n": f.get("pump_n") or f.get("token_n") or 0,
                "score": int(f.get("score") or 0),
            }
        )
    return {"families": families, "addresses": addrs, "stats": (fam.get("stats") if isinstance(fam, dict) else {}) or {}}


def _graph_families() -> list[dict[str, Any]]:
    path = ROOT / "pump_prep" / "out" / "deployer_clusters.json"
    raw = _load(path, {})
    clusters = raw.get("clusters") if isinstance(raw, dict) else None
    if not isinstance(clusters, list):
        return []
    out = []
    for c in clusters[:20]:
        dep = c.get("deployer") or ""
        if not dep:
            continue
        out.append(
            {
                "id": f"dep_{dep[:10]}",
                "source": "graph",
                "chain": c.get("chain") or "evm",
                "hub": dep,
                "hub_key": f"evm:{dep}",
                "short": dep[:6] + "…" + dep[-4:] if len(dep) > 12 else dep,
                "size": int(c.get("token_count") or 0),
                "members": [f"evm:{dep}"],
                "tokens": (c.get("symbols") or [])[:12],
                "token_n": int(c.get("token_count") or 0),
                "score": min(100, 20 + 10 * int(c.get("pump_count") or 0) + int(c.get("token_count") or 0)),
                "role_hint": "deployer",
            }
        )
    return out


def _ensure_move(fam: dict[str, Any], addrs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if fam.get("move") and fam.get("patron") and fam.get("frames"):
        return fam
    signal = None
    if fam.get("source") == "graph":
        signal = {"score": min(int(fam.get("score") or 0), 45), "signal_kind": "deployer"}
    return attach(fam, addrs=addrs, signal=signal)


def rebuild(*, reason: str = "manual", board: bool = True) -> dict[str, Any]:
    ensure()
    intel = _intel_bundle()
    roz = _roz_bundle()
    graph = _graph_families()

    addrs: dict[str, dict[str, Any]] = {}
    addrs.update(roz.get("addresses") or {})
    addrs.update(intel.get("addresses") or {})

    families: list[dict[str, Any]] = []
    seen: set[str] = set()
    for src, bundle in (("intel", intel["families"]), ("rozvidka", roz["families"]), ("graph", graph)):
        for fam in bundle:
            fam = dict(fam)
            fam.setdefault("source", src)
            _ensure_move(fam, addrs)
            fid = str(fam.get("id") or "")
            if not fid or fid in seen:
                continue
            seen.add(fid)
            families.append(fam)

    families.sort(key=lambda f: (-int((f.get("move") or {}).get("score") or f.get("score") or 0), -int(f.get("size") or 0)))

    goes = [f for f in families if (f.get("move") or {}).get("move") == "go"]
    submits = [f for f in families if (f.get("move") or {}).get("move") == "submit"]
    hands = [f for f in families if (f.get("move") or {}).get("move") == "hand"]

    snap = {
        "version": 1,
        "built_at": _now(),
        "reason": reason,
        "sources": {
            "intel_families": len(intel["families"]),
            "rozvidka_families": len(roz["families"]),
            "graph_deployers": len(graph),
            "addresses": len(addrs),
        },
        "stats": {
            "families": len(families),
            "go": len(goes),
            "submit": len(submits),
            "hand": len(hands),
            "watch": sum(1 for f in families if (f.get("move") or {}).get("move") == "watch"),
        },
        "families": families[:80],
        "moves": [
            {
                "id": f.get("id"),
                "source": f.get("source"),
                "short": f.get("short"),
                "chain": f.get("chain"),
                "patron": f.get("patron"),
                "frames": f.get("frames"),
                "move": f.get("move"),
                "tokens": (f.get("tokens") or [])[:6],
            }
            for f in (goes + submits + hands)[:24]
        ],
    }
    _save(SNAP_FILE, snap)
    _write_markdown(snap)
    write_ui(snap)
    _write_top_cards(snap)

    paper_n = 0
    try:
        from agents import trades

        paper_n = len(trades.sync_goes(goes, limit=8))
    except Exception:
        logger.debug("paper sync skipped", exc_info=True)

    if board:
        _post_board(snap, reason)

    snap["paper_opened"] = paper_n
    return snap


def rebuild_safe(reason: str = "cycle") -> dict[str, Any] | None:
    try:
        return rebuild(reason=reason)
    except Exception:
        logger.debug("unified wiki rebuild skipped", exc_info=True)
        return None


def load_snapshot() -> dict[str, Any]:
    data = _load(SNAP_FILE, {})
    return data if isinstance(data, dict) else {}


def _write_markdown(snap: dict[str, Any]) -> None:
    ensure()
    st = snap.get("stats") or {}
    lines = [
        "# MUTE wiki",
        "",
        f"_{snap.get('built_at')}_ · {snap.get('reason')}",
        "",
        f"сімʼї {st.get('families')} · ходити {st.get('go')} · подати {st.get('submit')} · рука {st.get('hand')}",
        "",
        "Джерела: intel + rozvidka + graph (deployer). Локальні вікі пакетів лишаються, це зведення.",
        "",
    ]
    INDEX_MD.write_text("\n".join(lines), encoding="utf-8")
    fam_lines = ["# Сімʼї · патрон · рамки · хід", ""]
    for f in snap.get("families") or []:
        mv = f.get("move") or {}
        pat = f.get("patron") or {}
        fr = f.get("frames") or {}
        fam_lines.append(
            f"- **{f.get('id')}** `{f.get('short')}` [{f.get('chain')}] · "
            f"{(mv.get('move_uk') or mv.get('move') or '—')} · "
            f"{(mv.get('where') or {}).get('hint') or '—'} · "
            f"патрон {pat.get('short') or '—'} ({pat.get('source') or ''}) · "
            f"рамки {fr.get('status') or '—'} "
            f"med={fr.get('median')} ratio={fr.get('amount_ratio')} · "
            f"{(mv.get('why') or '')}"
        )
    FAM_MD.write_text("\n".join(fam_lines[:120]), encoding="utf-8")


def _write_top_cards(snap: dict[str, Any]) -> None:
    ensure()
    folder = WIKI_DIR / "addresses"
    n = 0
    for f in snap.get("families") or []:
        pat = f.get("patron") or {}
        key = pat.get("key") or f.get("hub_key") or f.get("id")
        if not key:
            continue
        safe = str(key).replace("/", "_").replace(":", "_")[:120]
        mv = f.get("move") or {}
        fr = f.get("frames") or {}
        body = "\n".join(
            [
                f"# {f.get('short') or key}",
                "",
                f"- family: `{f.get('id')}`",
                f"- source: {f.get('source')}",
                f"- patron: `{pat.get('address')}` ({pat.get('source')}, confident={pat.get('confident')})",
                f"- frames: {fr.get('status')} median={fr.get('median')} ratio={fr.get('amount_ratio')} burst={fr.get('burst')}",
                f"- move: **{mv.get('move_uk') or mv.get('move')}** @ {(mv.get('where') or {}).get('hint')}",
                f"- why: {mv.get('why')}",
                f"- tokens: {', '.join((f.get('tokens') or [])[:12])}",
                "",
            ]
        )
        (folder / f"{safe}.md").write_text(body, encoding="utf-8")
        n += 1
        if n >= 40:
            break


def _post_board(snap: dict[str, Any], reason: str) -> None:
    try:
        from agents.board import post, raise_hand
    except Exception:
        return
    st = snap.get("stats") or {}
    post(
        "intel",
        f"вікі · сімʼї {st.get('families')} · ходити {st.get('go')} · подати {st.get('submit')}",
        kind="wiki",
        detail=reason,
        ref="job:wiki",
    )
    for row in (snap.get("moves") or [])[:6]:
        mv = row.get("move") or {}
        title = f"{mv.get('move_uk') or mv.get('move')} · {row.get('short')} · {(mv.get('where') or {}).get('hint')}"
        fid = str(row.get("id") or "")[:80]
        key = f"move:{fid}" if fid else ""
        if mv.get("move") == "hand":
            raise_hand("intel", title, detail=mv.get("why") or "", ref=key)
        else:
            post(
                str(row.get("source") or "intel"),
                title,
                kind=str(mv.get("move") or "move"),
                detail=mv.get("why") or "",
                ref=key or fid,
                status="doing" if mv.get("move") == "go" else "backlog",
            )


def write_ui(snap: dict[str, Any] | None = None) -> str:
    snap = snap or load_snapshot()
    payload = json.dumps(snap, ensure_ascii=False, default=str)
    html = f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Вікі · MUTE</title>
<style>
:root {{ --bg:#0c0e12; --panel:#151922; --text:#e8eaed; --muted:#9aa0a6; --line:#2a2f3a;
  --ok:#3dd68c; --warn:#e6b84d; --danger:#f07178; --accent:#7cb3ff; --hand:#f0a36b; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:14px/1.45 ui-sans-serif,system-ui,sans-serif; background:var(--bg); color:var(--text); }}
header {{ padding:14px 18px; border-bottom:1px solid var(--line); position:relative; background:transparent; }}
h1 {{ margin:0; font-size:18px; }}
.sub {{ color:var(--muted); font-size:12px; margin-top:4px; }}
.pills {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
.pill {{ border:1px solid var(--line); border-radius:999px; padding:3px 9px; font-size:11px; color:var(--muted); }}
.pill.go {{ color:var(--ok); border-color:rgba(61,214,140,.4); }}
.pill.submit {{ color:var(--warn); }}
.pill.hand {{ color:var(--hand); }}
main {{ padding:14px 18px 72px; display:grid; gap:10px; }}
article {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:10px 12px; }}
article.go {{ border-color:rgba(61,214,140,.35); }}
article.submit {{ border-color:rgba(230,184,77,.3); }}
article.hand {{ border-color:rgba(240,163,107,.4); }}
.top {{ display:flex; justify-content:space-between; gap:8px; font-size:12px; color:var(--muted); }}
.title {{ font-size:15px; font-weight:650; margin-top:4px; }}
.why {{ color:var(--muted); font-size:12px; margin-top:4px; }}
footer {{ position:fixed; bottom:0; left:0; right:0; padding:8px 14px; border-top:1px solid var(--line);
  background:rgba(12,14,18,.96); display:flex; gap:10px; }}
footer a {{ color:var(--text); text-decoration:none; border:1px solid var(--line); border-radius:8px; padding:6px 10px; }}
</style>
</head>
<body>
<header>
  <h1>Єдина вікі</h1>
  <div class="sub">патрон · рамки сімʼї · ходити / подати / де · спочатку папір</div>
  <div class="pills" id="pills"></div>
</header>
<main id="list"></main>
<footer>
  <a href="/">панель</a>
  <a href="/kanban.html">канбан</a>
  <a href="/intel.html">intel</a>
  <a href="/rozvidka.html">розвідка</a>
</footer>
<script>
const BOOT = {payload};
function esc(v) {{
  return String(v ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}
function render(snap) {{
  const st = snap.stats || {{}};
  document.getElementById('pills').innerHTML = [
    `<span class="pill">сімʼї ${{esc(st.families)}}</span>`,
    `<span class="pill go">ходити ${{esc(st.go)}}</span>`,
    `<span class="pill submit">подати ${{esc(st.submit)}}</span>`,
    `<span class="pill hand">рука ${{esc(st.hand)}}</span>`,
    `<span class="pill">${{esc((snap.built_at||'').replace('T',' ').slice(0,19))}}</span>`
  ].join('');
  const rows = snap.moves || snap.families || [];
  document.getElementById('list').innerHTML = rows.slice(0,40).map(f => {{
    const mv = f.move || {{}};
    const pat = f.patron || {{}};
    const fr = f.frames || {{}};
    const wh = mv.where || {{}};
    const cls = mv.move || 'watch';
    return `<article class="${{cls}}">
      <div class="top"><span>${{esc(mv.move_uk || mv.move)}} · ${{esc(wh.hint)}}</span><span>${{esc(f.source || '')}} · рамки ${{esc(fr.status)}}</span></div>
      <div class="title">${{esc(f.short || f.id)}} · патрон ${{esc(pat.short || '—')}}</div>
      <div class="why">${{esc(mv.why || '')}} · med ${{esc(fr.median)}} · ×${{esc(fr.amount_ratio)}} · ${{esc((f.tokens||[]).slice(0,4).join(', '))}}</div>
    </article>`;
  }}).join('') || '<article>поки порожньо — дочекайся циклу intel/розвідки</article>';
}}
render(BOOT);
async function refresh() {{
  try {{
    const r = await fetch('/api/wiki?ts=' + Date.now(), {{cache:'no-store'}});
    if (r.ok) render(await r.json());
  }} catch (e) {{}}
}}
setInterval(refresh, 8000);
</script>
</body>
</html>
"""
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    from agents.chrome import apply_to_html

    OUT_HTML.write_text(apply_to_html(html, "wiki-page"), encoding="utf-8")
    return str(OUT_HTML)
