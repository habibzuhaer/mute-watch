"""Tests for alerts template engine and router."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from alerts.levels import resolve_level, should_push
from alerts.normalize import from_live_prep, from_intel_prepump
from alerts.router import ActivityRouter
from alerts.template_engine import TemplateEngine


def test_resolve_level_act():
    assert resolve_level({"score": 60, "tier": "actionable"}) == "ACT"
    assert resolve_level({"score": 30, "tier": "noise"}) == "NOISE"


def test_should_push_watch():
    assert should_push("ACT") is True
    assert should_push("WATCH", push_watch=True) is True
    assert should_push("INFO") is False


def test_render_prep_act_uk():
    engine = TemplateEngine(lang="uk")
    activity = from_live_prep(
        {
            "prep_type": "new_token_in",
            "score": 62,
            "tier": "actionable",
            "chain": "ethereum",
            "symbol": "TEA",
            "amount_fmt": "1000",
            "kind": "IN",
            "wallet_label": "seed",
            "address": "0xfb770638ac4bc24720aac4b337ec098a26685f64",
            "from_address": "0xabc1234567890abc1234567890abc1234567890",
            "reasons": ["obscure token"],
            "reasons_uk": ["obscure token"],
        }
    )
    text = engine.render(activity, level="ACT")
    assert "TEA" in text
    assert "ДІЯ" in text or "score" in text
    assert "→" in text


def test_router_dedup_and_journal():
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        journal = data / "alerts.jsonl"
        dedup = data / "dedup.json"

        import alerts.config as cfg
        import alerts.router as router_mod

        old_j, old_d = cfg.JOURNAL_FILE, cfg.DEDUP_FILE
        cfg.JOURNAL_FILE = journal
        cfg.DEDUP_FILE = dedup
        router_mod.JOURNAL_FILE = journal

        try:
            r = ActivityRouter(
                lang="en",
                telegram_token="",
                telegram_chat_id="",
                dry_run=True,
                enabled=True,
                use_local_brain=False,
            )
            act = from_intel_prepump(
                {
                    "score": 72,
                    "chain": "ethereum",
                    "address": "0x123",
                    "short": "0x12…3",
                    "tokens": ["tea", "idos"],
                    "token_n": 2,
                    "touches": 5,
                    "key": "ethereum:0x123",
                }
            )
            a = r.route(act)
            assert a.level in {"ACT", "CRITICAL"}
            assert "PRE-PUMP" in a.text or "PRE" in a.text
            b = r.route(act)
            assert b.reason == "dedup"
            assert journal.exists()
            lines = journal.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) >= 1
            json.loads(lines[0])
        finally:
            cfg.JOURNAL_FILE = old_j
            cfg.DEDUP_FILE = old_d
            router_mod.JOURNAL_FILE = old_j
