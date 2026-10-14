"""Tests for MIN_USDT / stable amount filter."""

from __future__ import annotations

import unittest

from mute.amount_filter import is_stable_symbol, parse_amount_human, passes_min_usdt


class AmountFilterTests(unittest.TestCase):
    def test_stable_symbols(self):
        self.assertTrue(is_stable_symbol("USDT"))
        self.assertTrue(is_stable_symbol("usdc"))
        self.assertTrue(is_stable_symbol("USD1"))
        self.assertFalse(is_stable_symbol("PEPE"))
        self.assertFalse(is_stable_symbol("ETH"))

    def test_passes_min_usdt_stables(self):
        big = {"symbol": "USDT", "amount_human": 50_000}
        small = {"symbol": "USDT", "amount_fmt": "12,000.5"}
        self.assertTrue(passes_min_usdt(big, 30_000))
        self.assertFalse(passes_min_usdt(small, 30_000))
        self.assertTrue(passes_min_usdt(small, 0))

    def test_non_stable_not_blocked(self):
        obscure = {"symbol": "OBSCURE", "amount_human": 1}
        self.assertTrue(passes_min_usdt(obscure, 30_000))

    def test_parse_from_raw(self):
        ev = {"amount_raw": 30_000_000_000, "decimals": 6}
        self.assertEqual(parse_amount_human(ev), 30_000.0)


if __name__ == "__main__":
    unittest.main()
