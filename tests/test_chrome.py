"""Tiny chrome inject checks."""

from agents.chrome import apply_to_html, html


def test_apply_idempotent():
    src = "<html><head></head><body><p>x</p></body></html>"
    once = apply_to_html(src, "home")
    twice = apply_to_html(once, "home")
    assert "mute-chrome" in once
    assert twice == once
    assert once.count("<nav class=\"mute-chrome\"") == 1
    assert "Панель" in once
    assert "Оркестр" in once
    assert "--chrome-h: 84px" in once
    assert "padding-top: var(--chrome-h)" in once


def test_html_active():
    nav = html("kanban")
    assert 'data-chrome="kanban" class="active"' in nav or 'class="active"' in nav
    assert "MUTE" in nav


if __name__ == "__main__":
    failures = 0
    for fn in (test_apply_idempotent, test_html_active):
        try:
            fn()
            print("ok", fn.__name__)
        except Exception as exc:
            failures += 1
            print("FAIL", fn.__name__, exc)
    raise SystemExit(failures)
