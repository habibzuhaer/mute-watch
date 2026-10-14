"""Tests for agents package."""

from __future__ import annotations

from pathlib import Path

import agents.board as board
import agents.bus as bus
import agents.config as cfg
import agents.netguard as ng
from agents.bus import should_wake_speak
from agents.hooks import swarm_src
from agents.inference import strip_think
from agents.netguard import classify


def _tmp_agents(tmp_path: Path, monkeypatch) -> Path:
    data = tmp_path / "agents"
    monkeypatch.setattr(cfg, "DATA_DIR", data)
    monkeypatch.setattr(cfg, "BUS_FILE", data / "bus.jsonl")
    monkeypatch.setattr(cfg, "REPORTS_FILE", data / "reports.jsonl")
    monkeypatch.setattr(cfg, "VOICES_FILE", data / "voices.jsonl")
    monkeypatch.setattr(cfg, "STATE_FILE", data / "state.json")
    monkeypatch.setattr(cfg, "NUDGE_FILE", data / "nudge_speak.json")
    monkeypatch.setattr(cfg, "BOARD_FILE", data / "board.jsonl")
    monkeypatch.setattr(cfg, "KANBAN_FILE", data / "kanban.json")
    monkeypatch.setattr(cfg, "HANDS_FILE", data / "hands.json")
    monkeypatch.setattr(ng, "DATA_DIR", data)
    monkeypatch.setattr(ng, "REPORTS_FILE", data / "reports.jsonl")
    monkeypatch.setattr(ng, "STATE_FILE", data / "state.json")
    monkeypatch.setattr(ng, "NET_FAILS_BEFORE_RESTART", 3)
    monkeypatch.setattr(bus, "BUS_FILE", data / "bus.jsonl")
    monkeypatch.setattr(bus, "DATA_DIR", data)
    monkeypatch.setattr(bus, "NUDGE_FILE", data / "nudge_speak.json")
    monkeypatch.setattr(bus, "VOICES_FILE", data / "voices.jsonl")
    monkeypatch.setattr(board, "DATA_DIR", data)
    monkeypatch.setattr(board, "BOARD_FILE", data / "board.jsonl")
    monkeypatch.setattr(board, "KANBAN_FILE", data / "kanban.json")
    monkeypatch.setattr(board, "HANDS_FILE", data / "hands.json")
    monkeypatch.setattr(board, "ROOT", tmp_path)
    data.mkdir(parents=True)
    return data


def test_bus_emit_and_tail(tmp_path, monkeypatch):
    _tmp_agents(tmp_path, monkeypatch)
    row = bus.emit("mute", "prep_act", level="ACT", score=62, ref="TEA")
    assert row["src"] == "mute"
    rows, off = bus.tail(0)
    assert len(rows) == 1
    assert rows[0]["ref"] == "TEA"
    rows2, off2 = bus.tail(off)
    assert rows2 == []
    assert off2 == off


def test_should_wake_speak():
    assert should_wake_speak({"src": "mute", "kind": "prep_act", "level": "ACT", "score": 62})
    assert should_wake_speak({"src": "intel", "kind": "activity_spike", "level": "WATCH", "score": 44})
    assert not should_wake_speak({"src": "rozvidka", "kind": "turn", "level": "ACT", "score": 90})
    assert not should_wake_speak({"src": "mute", "kind": "net_tg", "level": "INFO", "score": 0})
    assert not should_wake_speak({"src": "mute", "kind": "info", "level": "INFO", "score": 10})


def test_nudge_consume(tmp_path, monkeypatch):
    _tmp_agents(tmp_path, monkeypatch)
    bus.write_nudge("mute:prep_act", {"src": "mute", "kind": "prep_act"})
    first = bus.consume_nudge(after_epoch=0)
    assert first and first["reason"] == "mute:prep_act"
    assert bus.consume_nudge(after_epoch=0) is None


def test_classify_and_report(tmp_path, monkeypatch):
    _tmp_agents(tmp_path, monkeypatch)
    monkeypatch.setattr(ng, "ROOT", tmp_path)
    assert classify("Ollama timeout after 30s") == "net_llm"
    assert classify("telegram 401", hint="net_tg") == "net_tg"
    assert classify("HTTPSConnectionPool timeout etherscan") == "net_rpc"
    ng.report("mute", "net_rpc", "etherscan timeout", raise_hand=False)
    ng.report("mute", "net_rpc", "etherscan timeout 2", raise_hand=False)
    st = ng.load_orch_state()
    assert st["net_fails"]["mute"]["n"] == 2
    assert ng.recent_reports(5)[0]["kind"] == "net_rpc"
    assert not ng.should_restart_for_net("mute", "net_tg")
    assert not ng.should_restart_for_net("mute", "net_llm")
    assert not ng.should_restart_for_net("mute", "net_rpc")
    ng.report("mute", "net_rpc", "etherscan timeout 3", raise_hand=False)
    assert ng.should_restart_for_net("mute", "net_rpc")


def test_strip_think():
    assert strip_think("<think>secret</think>\nhello") == "hello"


def test_swarm_src():
    assert swarm_src("live_prep") == "mute"
    assert swarm_src("intel") == "intel"
    assert swarm_src("rozvidka") == "rozvidka"
    assert swarm_src("graph") == "intel"


def test_hooks_do_not_raise(tmp_path, monkeypatch):
    _tmp_agents(tmp_path, monkeypatch)
    monkeypatch.setattr(ng, "ROOT", tmp_path)
    from agents.hooks import beat, on_net_fail, on_signal, _sig_seen, _net_seen

    _sig_seen.clear()
    _net_seen.clear()
    assert on_signal("intel", "activity_spike", level="ACT", score=70, ref="xyz") is True
    assert on_signal("intel", "activity_spike", level="ACT", score=70, ref="xyz") is False
    on_net_fail("intel", TimeoutError("rpc"), hint="net_rpc")
    beat("mute")
    rows, _ = bus.tail(0)
    assert any(r["src"] == "intel" for r in rows)


def test_board_post_hand_and_ack(tmp_path, monkeypatch):
    _tmp_agents(tmp_path, monkeypatch)
    c = board.post("mute", "TEA inbound", kind="prep_act", level="ACT", ref="TEA")
    assert c["src"] == "mute"
    assert c["status"] == "doing"
    assert c["ref"] == "TEA"
    c2 = board.post("mute", "TEA inbound again", kind="prep_act", level="ACT", ref="TEA")
    assert c2["id"] == c["id"]
    assert c2["title"] == "TEA inbound again"
    h = board.raise_hand("rozvidka", "що з сімʼєю X?")
    snap = board.snapshot()
    assert snap["open_hands"] >= 1
    assert any(x["id"] == h["id"] for x in snap["columns"]["hand"])
    assert any(x["id"] == c["id"] for x in snap["columns"]["doing"])
    board.ack(h["id"])
    snap2 = board.snapshot()
    assert all(x["id"] != h["id"] for x in snap2["columns"]["hand"])
    assert any(x["id"] == h["id"] for x in snap2["columns"]["doing"])


def test_kanban_move_and_manual(tmp_path, monkeypatch):
    _tmp_agents(tmp_path, monkeypatch)
    c = board.post("intel", "черга адрес", kind="collect", ref="job:intel-test")
    moved = board.move(c["id"], "backlog")
    assert moved["ok"] is True
    assert moved["card"]["status"] == "backlog"
    assert moved["card"]["manual"] is True
    again = board.post("intel", "черга адрес 2", kind="collect", ref="job:intel-test")
    assert again["id"] == c["id"]
    assert again["status"] == "backlog"
    board.follow(c["id"])
    live = board.post("intel", "збір іде", kind="collect", ref="job:intel-test")
    assert live["status"] == "doing"
    board.done(c["id"])
    snap = board.snapshot()
    assert any(x["id"] == c["id"] for x in snap["columns"]["done"])


if __name__ == "__main__":
    class _P:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    import tempfile
    from pathlib import Path as Pth

    failures = 0
    for fn in (test_should_wake_speak, test_strip_think, test_swarm_src):
        try:
            fn()
            print("ok", fn.__name__)
        except Exception as exc:
            failures += 1
            print("FAIL", fn.__name__, exc)
    with tempfile.TemporaryDirectory() as tmp:
        mp = _P()
        base = Pth(tmp)
        for fn in (
            test_bus_emit_and_tail,
            test_nudge_consume,
            test_classify_and_report,
            test_hooks_do_not_raise,
            test_board_post_hand_and_ack,
            test_kanban_move_and_manual,
        ):
            try:
                fn(base / fn.__name__, mp)
                print("ok", fn.__name__)
            except Exception as exc:
                failures += 1
                print("FAIL", fn.__name__, exc)
    raise SystemExit(failures)
