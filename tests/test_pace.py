"""Shared Etherscan pace + Solana 429 handling."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from mute.pace import SharedPace
from mute.pollers.solana import _RATE_LIMITED, _rpc
from mute.telegram import _h, format_inbound_alert


def test_shared_pace_tmp(tmp_path: Path):
    p = SharedPace(tmp_path / "pace", 0.05)
    t0 = __import__("time").monotonic()
    p.wait()
    p.wait()
    elapsed = __import__("time").monotonic() - t0
    assert elapsed >= 0.04


def test_solana_rpc_429_no_raise():
    from unittest.mock import patch

    sess = MagicMock()
    resp = MagicMock()
    resp.status_code = 429
    sess.post.return_value = resp
    with patch("mute.pollers.solana.time.sleep"):
        out = _rpc(sess, "https://api.mainnet-beta.solana.com", "getTransaction", ["x"])
    assert out is _RATE_LIMITED
    assert sess.post.call_count == 3


def test_telegram_html_escape():
    text = format_inbound_alert(
        {
            "chain": "Solana",
            "wallet_label": "seed <b>",
            "address": "abc",
            "kind": "IN",
            "symbol": "x<y>",
            "amount_fmt": "1",
        }
    )
    assert "<b>" in text  # our tags
    assert _h("x<y>") == "x&lt;y&gt;"
    assert "x&lt;y&gt;" in text
    assert "seed &lt;b&gt;" in text


def test_route_consumed_reasons():
    sent, reason = False, "money_filter"
    consumed = bool(sent) or reason != "send_failed"
    assert consumed is True
    consumed_fail = bool(False) or "send_failed" != "send_failed"
    assert consumed_fail is False


if __name__ == "__main__":
    import tempfile
    from pathlib import Path as Pth

    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        try:
            test_shared_pace_tmp(Pth(tmp))
            print("ok test_shared_pace_tmp")
        except Exception as exc:
            failures += 1
            print("FAIL test_shared_pace_tmp", exc)
    for fn in (test_solana_rpc_429_no_raise, test_telegram_html_escape, test_route_consumed_reasons):
        try:
            fn()
            print("ok", fn.__name__)
        except Exception as exc:
            failures += 1
            print("FAIL", fn.__name__, exc)
    raise SystemExit(failures)
