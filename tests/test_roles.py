"""Collector vs analyst roles: no public Solana RPC, rozvidka does not rewrite DBs."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from mute.config import solana_rpc_usable


def test_solana_rpc_usable():
    assert solana_rpc_usable("", "https://api.mainnet-beta.solana.com") is False
    assert solana_rpc_usable("k", "https://api.mainnet-beta.solana.com") is True
    assert solana_rpc_usable("", "https://mainnet.helius-rpc.com/?api-key=x") is True
    assert solana_rpc_usable("", "https://my-private-rpc.example") is True
    assert solana_rpc_usable("", "") is False


def test_load_existing_graph_does_not_write(tmp_path: Path):
    import rozvidka.relations as rel

    db = tmp_path / "roz"
    db.mkdir()
    fam_path = db / "families.json"
    addr_path = db / "addresses.json"
    body = {
        "built_at": "x",
        "stats": {"families": 1, "addresses": 1},
        "families": [
            {
                "id": "fam_1",
                "hub": "0xabc",
                "hub_short": "0xabc",
                "size": 3,
                "pump_n": 1,
                "score": 10,
                "pump_tokens": ["PUMP"],
                "top_links": [],
            }
        ],
    }
    fam_path.write_text(json.dumps(body), encoding="utf-8")
    addr_path.write_text("{}", encoding="utf-8")
    before = fam_path.read_text(encoding="utf-8")
    with (
        patch.object(rel, "DB_DIR", db),
        patch.object(rel, "FAMILY_DB", fam_path),
        patch.object(rel, "ADDR_DB", addr_path),
        patch.object(rel, "ROOT", tmp_path),
        patch.object(rel, "save_json", side_effect=AssertionError("save")),
    ):
        out = rel.load_existing_graph()
    assert out["read_only"] is True
    assert out["persisted"]["read_only"] is True
    assert fam_path.read_text(encoding="utf-8") == before
    assert out["top_families"][0]["id"] == "fam_1"


def test_run_family_pass_default_is_read_only():
    import rozvidka.relations as rel

    with (
        patch.object(rel, "load_existing_graph", return_value={"read_only": True, "ok": True}),
        patch.object(rel, "persist_graph", side_effect=AssertionError("persist")),
    ):
        out = rel.run_family_pass()
    assert out["read_only"] is True


def test_run_one_turn_ollama_down_no_hand(tmp_path: Path):
    import rozvidka.config as rcfg
    import rozvidka.runtime as rt
    import rozvidka.wiki as wiki

    data = tmp_path / "rozvidka"
    data.mkdir()
    hand = MagicMock()
    with (
        patch.object(rt, "DATA_DIR", data),
        patch.object(rt, "STATE_FILE", data / "state.json"),
        patch.object(rt, "TURNS_FILE", data / "turns.jsonl"),
        patch.object(rt, "ACTIONS_FILE", data / "actions.jsonl"),
        patch.object(rcfg, "DATA_DIR", data),
        patch.object(wiki, "WIKI_DIR", data / "wiki"),
        patch.object(wiki, "ensure", lambda: None),
        patch.object(rt, "ping", lambda: {"ok": False}),
        patch.object(
            rt,
            "run_observe_phase",
            lambda *a, **k: {
                "findings": [],
                "regularities": [],
                "relations": {},
                "relation_patterns": [],
                "snapshot_stats": {},
            },
        ),
        patch.object(rt, "_apply_wiki", lambda *a, **k: []),
        patch.object(rt, "write_ui", lambda *a, **k: None),
        patch.object(rt, "build_snapshot", lambda *a, **k: {"ok": True}),
        patch("rozvidka.cycles.append_cycle", lambda *a, **k: None),
        patch("agents.hooks.on_hand", hand),
    ):
        row = rt.run_one_turn(use_llm=True, do_expand=False)
    assert not row.get("hand")
    assert "без моделі" not in (row.get("title") or "")
    assert row.get("noise") is True
    hand.assert_not_called()


if __name__ == "__main__":
    import tempfile

    failures = 0
    for fn in (test_solana_rpc_usable, test_run_family_pass_default_is_read_only):
        try:
            fn()
            print("ok", fn.__name__)
        except Exception as exc:
            failures += 1
            print("FAIL", fn.__name__, exc)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        for fn in (test_load_existing_graph_does_not_write, test_run_one_turn_ollama_down_no_hand):
            try:
                fn(p)
                print("ok", fn.__name__)
            except Exception as exc:
                failures += 1
                print("FAIL", fn.__name__, exc)
    raise SystemExit(failures)
