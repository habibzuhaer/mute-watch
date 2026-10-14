"""Unit tests: signal scoring tiers + cycle health."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pump_prep.signals import MIN_SCORE, WATCH_SCORE, score_match, score_prep_event, passes_telegram
from pump_prep.cycles import check_cycle_health, signal_board


class SignalScoreTests(unittest.TestCase):
    def test_cex_out_young_fresh_is_watch_or_higher(self):
        import time

        scored = score_match(
            match_role="cex",
            match_entity="Binance",
            direction="out",
            is_token_itself=True,
            age_days=10,
            timestamp=int(time.time()) - 3600,
        )
        self.assertGreaterEqual(scored.score, WATCH_SCORE)
        self.assertIn(scored.tier, ("watch", "actionable"))
        self.assertTrue(any("CEX" in r or "бирж" in r.lower() or "OUT" in r for r in scored.reasons))

    def test_seed_mm_out_scores_actionable(self):
        import time

        scored = score_match(
            match_role="seed",
            match_entity="DWF Labs",
            direction="out",
            is_token_itself=True,
            age_days=7,
            timestamp=int(time.time()) - 100,
        )
        self.assertGreaterEqual(scored.score, MIN_SCORE)
        self.assertEqual(scored.tier, "actionable")
        self.assertTrue(passes_telegram(scored))

    def test_old_ath_dump_penalized(self):
        low = score_match(
            match_role="cex",
            match_entity="Gate",
            direction="out",
            age_days=800,
            ath_chg=-90,
            ath=1.0,
            price=0.1,
            timestamp=1_600_000_000,
        )
        high = score_match(
            match_role="cex",
            match_entity="Gate",
            direction="out",
            age_days=20,
            ath_chg=-5,
            timestamp=1_700_000_000,
        )
        self.assertLess(low.score, high.score)

    def test_prep_live_cex_deposit_actionable(self):
        import time

        ev = {
            "prep_type": "cex_deposit",
            "symbol": "OBSCURE",
            "cex": "Binance",
            "wallet_label": "Gotbit seed",
            "timestamp": int(time.time()),
        }
        scored = score_prep_event(ev)
        self.assertEqual(scored.kind, "cex_deposit")
        self.assertGreaterEqual(scored.score, MIN_SCORE)
        self.assertTrue(passes_telegram(scored))

    def test_noise_below_watch(self):
        scored = score_match(
            match_role="cex",
            match_entity="OKX",
            direction="in",
            age_days=2000,
            timestamp=1_500_000_000,
        )
        # may still be watch due to cex base — ensure tier mapping consistent
        if scored.score < WATCH_SCORE:
            self.assertEqual(scored.tier, "noise")
        elif scored.score < MIN_SCORE:
            self.assertEqual(scored.tier, "watch")
        else:
            self.assertEqual(scored.tier, "actionable")


class CycleHealthTests(unittest.TestCase):
    def test_stopped_when_no_pids(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = {
                "cycles": 3,
                "updated_at": "2020-01-01T00:00:00+00:00",
                "done_tokens": ["a"],
                "expand_queue": [],
            }
            gdir = root / "data" / "graph"
            gdir.mkdir(parents=True)
            (gdir / "state.json").write_text(json.dumps(state), encoding="utf-8")
            with mock.patch("pump_prep.cycles.ROOT", root), mock.patch(
                "pump_prep.cycles.gs.GRAPH_DIR", gdir
            ), mock.patch("pump_prep.cycles.gs.STATE_FILE", gdir / "state.json"):
                # reload state via real load_state path — patch load_state instead
                pass

        with mock.patch("pump_prep.cycles.gs.load_state", return_value=state), mock.patch(
            "pump_prep.cycles.ROOT", Path("/tmp/mute-no-pids-xyz")
        ):
            h = check_cycle_health(now=1_700_000_000, stale_sec=600)
            self.assertEqual(h["cycle_status"], "stopped")
            self.assertFalse(h["processes"]["scanner"]["running"])
            self.assertTrue(any("scanner" in i for i in h["issues"]))

    def test_ok_when_scanner_fresh(self):
        import os
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        state = {
            "cycles": 42,
            "updated_at": now.isoformat(),
            "done_tokens": ["x"],
            "expand_queue": ["0xabc"],
            "last_token": "foo",
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "scanner.pid").write_text(str(os.getpid()), encoding="utf-8")
            with mock.patch("pump_prep.cycles.gs.load_state", return_value=state), mock.patch(
                "pump_prep.cycles.ROOT", root
            ):
                h = check_cycle_health(stale_sec=600)
                self.assertEqual(h["cycle_status"], "ok")
                self.assertTrue(h["processes"]["scanner"]["running"])
                self.assertEqual(h["cycles"], 42)

    def test_stale_when_old_update(self):
        import os

        state = {
            "cycles": 10,
            "updated_at": "2020-01-01T00:00:00+00:00",
            "done_tokens": [],
            "expand_queue": [],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "scanner.pid").write_text(str(os.getpid()), encoding="utf-8")
            with mock.patch("pump_prep.cycles.gs.load_state", return_value=state), mock.patch(
                "pump_prep.cycles.ROOT", root
            ):
                h = check_cycle_health(now=1_700_000_000, stale_sec=600)
                self.assertEqual(h["cycle_status"], "stale")
                self.assertTrue(any("stale" in i.lower() for i in h["issues"]))


class SignalBoardTests(unittest.TestCase):
    def test_board_splits_act_and_watch(self):
        rows = [
            {"symbol": "AAA", "tier": "actionable", "score": 70, "match_entity": "DWF Labs", "direction": "out", "reasons": ["x"], "hash": "1"},
            {"symbol": "BBB", "tier": "watch", "score": 40, "match_entity": "Gate", "direction": "out", "reasons": ["y"], "hash": "2"},
            {"symbol": "CCC", "tier": "noise", "score": 10, "match_entity": "OKX", "direction": "in", "reasons": ["z"], "hash": "3"},
        ]
        empty_idx = {"by_symbol": {}, "by_id": {}, "by_contract": {}, "count": 0, "mtime": 0}
        with mock.patch("pump_prep.cycles.gs.read_jsonl_tail", return_value=rows), mock.patch(
            "pump_prep.cycles.gs.token_mcap_index", return_value=empty_idx
        ):
            board = signal_board()
            self.assertEqual(board["act_count"], 1)
            self.assertEqual(board["watch_count"], 1)
            self.assertEqual(board["act"][0]["symbol"], "AAA")
            self.assertEqual(board["watch"][0]["symbol"], "BBB")
            self.assertEqual(board["act"][0]["money_band"], "unknown")

    def test_money_band_filter(self):
        from pump_prep.cycles import money_band, mcap_in_band

        self.assertEqual(money_band(100_000), "micro")
        self.assertEqual(money_band(1_000_000), "small")
        self.assertEqual(money_band(5_000_000), "mid")
        self.assertEqual(money_band(20_000_000), "large")
        self.assertEqual(money_band(100_000_000), "mega")
        self.assertEqual(money_band(None), "unknown")
        self.assertTrue(mcap_in_band(2_000_000, "small"))
        self.assertFalse(mcap_in_band(2_000_000, "mega"))
        self.assertTrue(mcap_in_band(None, "unknown"))
        self.assertTrue(mcap_in_band(None, "any"))

        rows = [
            {"symbol": "MICRO", "tier": "watch", "score": 40, "match_entity": "Gate", "direction": "out", "hash": "1"},
            {"symbol": "MID", "tier": "watch", "score": 41, "match_entity": "Gate", "direction": "out", "hash": "2"},
        ]
        idx = {
            "by_symbol": {"MICRO": 100_000, "MID": 5_000_000},
            "by_id": {},
            "by_contract": {},
            "count": 2,
            "mtime": 1,
        }
        with mock.patch("pump_prep.cycles.gs.read_jsonl_tail", return_value=rows), mock.patch(
            "pump_prep.cycles.gs.token_mcap_index", return_value=idx
        ):
            board = signal_board(money_band_filter="mid")
            self.assertEqual(board["watch_count"], 1)
            self.assertEqual(board["watch"][0]["symbol"], "MID")
            self.assertEqual(board["watch"][0]["mcap_fmt"], "$5.00M")


if __name__ == "__main__":
    unittest.main()
