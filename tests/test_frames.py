"""Patron / frames / go-submit-where — no chain I/O."""

from __future__ import annotations

from agents.frames import decide_move, is_patron_card, pick_patron, frames_from_amounts


def test_patron_label_beats_flow():
    members = ["bnb:0xhub", "bnb:0xmm"]
    addrs = {
        "bnb:0xmm": {"role": "mm", "entity": "DWF", "tags": ["seed"], "out_n": 2, "short": "0xmm"},
        "bnb:0xhub": {"out_n": 90, "short": "hub"},
    }
    p = pick_patron(members, addrs=addrs, out_weight={"bnb:0xhub": 50}, hub_key="bnb:0xhub")
    assert p["key"] == "bnb:0xmm"
    assert p["confident"] is True
    assert p["source"] == "label"
    assert is_patron_card(addrs["bnb:0xmm"])
    assert not is_patron_card({"tags": ["cex"], "entity": "Binance"})


def test_frames_deviant_on_amount():
    fr = frames_from_amounts([10, 10, 12], [40], [1, 2, 3], recent_n=1, chain="solana", now_ts=10)
    assert fr["status"] == "вихід"
    assert fr["deviant"] is True
    assert fr["amount_ratio"] >= 2


def test_decide_go_submit_hand():
    go = decide_move(
        frames={"deviant": True, "n": 8, "chain": "solana"},
        patron={"confident": True, "chain": "solana"},
        family_score=70,
    )
    assert go["move"] == "go"
    assert go["move_uk"] == "ходити"
    assert go["where"]["venue"] == "dex"

    no_frames = decide_move(
        frames={"n": 0},
        patron={"confident": True},
        family_score=90,
    )
    assert no_frames["move"] == "submit"

    cex = decide_move(
        frames={"deviant": True, "n": 8, "chain": "bnb"},
        patron={"confident": True},
        signal={"score": 80, "signal_kind": "cex_deposit", "chain": "bnb"},
    )
    assert cex["move"] == "submit"
    assert cex["where"]["venue"] == "cex"

    hand = decide_move(frames={}, patron={}, family_score=10)
    assert hand["move"] == "hand"


def test_paper_refuses_real(tmp_path, monkeypatch):
    import agents.board as board
    import agents.config as cfg
    import agents.trades as tr

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tr, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tr, "PAPER_FILE", tmp_path / "paper.jsonl")
    monkeypatch.setattr(tr, "ALLOW_REAL", False)
    monkeypatch.setattr(board, "DATA_DIR", tmp_path)
    monkeypatch.setattr(board, "BOARD_FILE", tmp_path / "board.jsonl")
    monkeypatch.setattr(board, "HANDS_FILE", tmp_path / "hands.json")
    row = tr.open_paper(family_id="fam_x", symbol="TEA", move={"move": "go", "move_uk": "ходити", "where": {"hint": "sol / dex"}, "why": "test"})
    assert row["status"] == "paper"
    out = tr.promote_real(row["id"])
    assert out["ok"] is False
    assert "real disabled" in (out.get("error") or "")


if __name__ == "__main__":
    class _P:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    import tempfile
    from pathlib import Path

    failures = 0
    for fn in (test_patron_label_beats_flow, test_frames_deviant_on_amount, test_decide_go_submit_hand):
        try:
            fn()
            print("ok", fn.__name__)
        except Exception as exc:
            failures += 1
            print("FAIL", fn.__name__, exc)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            test_paper_refuses_real(Path(tmp), _P())
            print("ok test_paper_refuses_real")
        except Exception as exc:
            failures += 1
            print("FAIL test_paper_refuses_real", exc)
    raise SystemExit(failures)
