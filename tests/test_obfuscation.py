"""Unit tests: obfuscation heuristics + score bumps for hops/bridges."""

from __future__ import annotations

import time
import unittest

from pump_prep.bridge_labels import bridge_name
from pump_prep.obfuscation import (
    amounts_match,
    detect_same_amount_vs_edges,
    hop_from_via,
    human_amount,
    is_fresh_wallet,
    wallet_age_days,
)
from pump_prep.signals import score_match


class ObfuscationHelpersTests(unittest.TestCase):
    def test_human_amount(self):
        self.assertEqual(human_amount("1000000", 6), 1.0)
        self.assertIsNone(human_amount("x", 6))

    def test_amounts_match_tolerance(self):
        self.assertTrue(amounts_match(100_000.0, 100_400.0))  # 0.4%
        self.assertFalse(amounts_match(100_000.0, 102_000.0))  # 2%

    def test_fresh_wallet(self):
        now = time.time()
        self.assertTrue(is_fresh_wallet(now - 3 * 86400, now=now))
        self.assertFalse(is_fresh_wallet(now - 60 * 86400, now=now))
        self.assertAlmostEqual(wallet_age_days(now - 10 * 86400, now=now), 10.0, places=1)

    def test_hop_from_via(self):
        self.assertEqual(hop_from_via("deployer"), 0)
        self.assertEqual(hop_from_via("expand"), 1)
        self.assertEqual(hop_from_via("expand2"), 2)

    def test_detect_same_amount_vs_edges(self):
        now = int(time.time())
        edges = [
            {
                "from_addr": "0xaaa",
                "to_addr": "0xbbb",
                "amount_human": 50_000.0,
                "timestamp": now - 3600,
                "hash": "0x1",
            }
        ]
        hit = detect_same_amount_vs_edges(
            amount=50_100.0,
            counterparty="0xbbb",
            edges=edges,
            now_ts=now,
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["matched_amount"], 50_000.0)

    def test_bridge_label(self):
        # Stargate ethereum router from bridge_labels
        self.assertEqual(
            bridge_name("0x8731d54e9d02c286767d671aac4cd310a8bc4c1d"),
            "Stargate",
        )


class ObfuscationScoreTests(unittest.TestCase):
    def test_two_hop_bumps_score(self):
        base = score_match(
            match_role="cex",
            match_entity="Binance",
            direction="out",
            via="expand",
            hop=1,
            timestamp=int(time.time()),
        )
        hop2 = score_match(
            match_role="cex",
            match_entity="Binance",
            direction="out",
            via="expand2",
            hop=2,
            timestamp=int(time.time()),
        )
        self.assertGreater(hop2.score, base.score)
        self.assertEqual(hop2.kind, "hop_chain")

    def test_same_amount_and_fresh(self):
        scored = score_match(
            match_role="mm",
            match_entity="Gotbit",
            direction="out",
            via="expand2",
            hop=2,
            same_amount=True,
            same_amount_hint="≈50000",
            fresh_wallet=True,
            fresh_wallet_days=2.0,
            amount_human=50_000.0,
            timestamp=int(time.time()),
            age_days=20,
        )
        self.assertTrue(any("same-amount" in r for r in scored.reasons))
        self.assertTrue(any("fresh wallet" in r for r in scored.reasons))
        self.assertIn(scored.kind, ("hop_chain", "fresh_hop"))

    def test_bridge_role(self):
        scored = score_match(
            match_role="bridge",
            match_entity="Wormhole",
            direction="out",
            via="expand",
            hop=1,
            timestamp=int(time.time()),
        )
        self.assertEqual(scored.kind, "bridge_hop")
        self.assertTrue(any("bridge" in r.lower() for r in scored.reasons))


if __name__ == "__main__":
    unittest.main()
