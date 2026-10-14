"""Fixed MUTE chrome — same two rows on every page. Does not scroll away."""

from __future__ import annotations

CSS = """
:root { --chrome-h: 84px; }
.mute-chrome {
  position: fixed; top: 0; left: 0; right: 0; z-index: 2000;
  height: var(--chrome-h);
  display: flex; flex-direction: column; justify-content: center; gap: 0;
  box-sizing: border-box;
  padding: 4px 12px;
  background: rgba(12,14,18,.98);
  border-bottom: 1px solid #2a2f3a;
  backdrop-filter: blur(8px);
}
.mute-chrome .mute-row {
  display: flex; flex-wrap: nowrap; align-items: center; gap: 4px;
  height: 36px; min-height: 36px; max-height: 36px;
  overflow-x: auto; overflow-y: hidden;
  scrollbar-width: none; -ms-overflow-style: none;
}
.mute-chrome .mute-row::-webkit-scrollbar { display: none; height: 0; }
.mute-chrome a, .mute-chrome .mute-brand {
  flex: 0 0 auto; white-space: nowrap;
  color: #9aa0a6; text-decoration: none; font-size: 12px; font-weight: 650;
  padding: 6px 10px; border-radius: 8px; border: 1px solid transparent;
  font-family: ui-sans-serif, system-ui, sans-serif;
}
.mute-chrome .mute-brand { color: #e8eaed; font-weight: 750; letter-spacing: .04em; padding-left: 2px; }
.mute-chrome a:hover { color: #e8eaed; background: #1b2030; border-color: #2a2f3a; }
.mute-chrome a.active { color: #cfe0ff; background: #243044; border-color: #3a5080; }
html { scroll-padding-top: calc(var(--chrome-h) + 8px); }
body { padding-top: var(--chrome-h) !important; }
"""

_PAGES = (
    ("/", "Панель", "home"),
    ("/wiki.html", "Вікі", "wiki-page"),
    ("/kanban.html", "Оркестр", "kanban"),
    ("/intel.html", "Intel", "intel"),
    ("/rozvidka.html", "Розвідка", "rozvidka"),
    ("/launch.html", "Запуск", "launch"),
    ("/reports/signals_hub.html", "Hub", "hub"),
)
_SECTIONS = (
    ("/#now", "Зараз", "now"),
    ("/#wiki", "Сімʼї", "wiki"),
    ("/#procs", "Система", "procs"),
    ("/#agents", "Агенти", "agents"),
    ("/#cycles", "Цикли", "cycles"),
    ("/#launch", "Кнопки", "launch-sec"),
    ("/#reports", "Звіти", "reports"),
)


def html(active: str = "") -> str:
    def row(items: tuple, *, extra: str = "") -> str:
        bits = [extra] if extra else []
        for href, label, key in items:
            cls = ' class="active"' if active and key == active else ""
            nav_id = href[2:] if href.startswith("/#") else ""
            nav = f' data-nav="{nav_id}"' if nav_id else ""
            bits.append(f'<a href="{href}" data-chrome="{key}"{nav}{cls}>{label}</a>')
        return '<div class="mute-row">' + "".join(bits) + "</div>"

    top = row(_PAGES, extra='<span class="mute-brand">MUTE</span>')
    return (
        '<nav class="mute-chrome" aria-label="MUTE">'
        + top
        + row(_SECTIONS)
        + "</nav>\n"
        + _MARK_SCRIPT
    )


_MARK_SCRIPT = """<script>
(function () {
  const path = (location.pathname || '/').replace(/\\/+$/, '') || '/';
  const home = path === '/' || /\\/(dashboard|index|panel)(\\.html)?$/.test(path);
  document.querySelectorAll('.mute-chrome a[data-chrome]').forEach(a => {
    const href = a.getAttribute('href') || '';
    if (href.startsWith('/#')) return;
    if (home && href === '/') a.classList.add('active');
    else if (!home && (href === path || href === location.pathname)) a.classList.add('active');
  });
})();
</script>
"""


def apply_to_html(doc: str, active: str = "") -> str:
    """Idempotent: inject chrome CSS + nav if missing."""
    if "mute-chrome" in doc:
        return doc
    nav = html(active)
    if "</head>" in doc:
        doc = doc.replace("</head>", f"<style>{CSS}</style>\n</head>", 1)
    low = doc.lower()
    i = low.find("<body")
    if i >= 0:
        j = doc.find(">", i)
        if j >= 0:
            doc = doc[: j + 1] + "\n" + nav + doc[j + 1 :]
    return doc
