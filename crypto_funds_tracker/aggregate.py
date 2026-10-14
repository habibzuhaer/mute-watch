from __future__ import annotations

from collections import defaultdict
from typing import Any


def enrich_with_portfolio_pct(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add portfolio_pct = position USD / fund total USD (when values exist)."""
    by_fund: dict[str, float] = defaultdict(float)
    for r in rows:
        v = r.get("current_value_usd")
        if v:
            by_fund[r["fund_name"]] += float(v)

    out = []
    for r in rows:
        r = dict(r)
        total = by_fund.get(r["fund_name"]) or 0
        cur = r.get("current_value_usd")
        if total and cur:
            r["portfolio_pct"] = round(float(cur) / total * 100, 2)
        elif r.get("portfolio_pct") is None:
            r["portfolio_pct"] = None
        out.append(r)
    return out


def merge_market_stats(
    rows: list[dict[str, Any]],
    market: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        r = dict(r)
        m = market.get(r.get("token") or "", {})
        prices = m.get("prices") or {}
        r["price_binance"] = prices.get("binance")
        r["price_bybit"] = prices.get("bybit")
        r["price_okx"] = prices.get("okx")
        r["price_bingx"] = prices.get("bingx")
        for w in ("3m", "6m", "9m"):
            r[f"vol_{w}"] = m.get(f"vol_{w}")
            r[f"chg_{w}"] = m.get(f"chg_{w}")
        out.append(r)
    return out


def sort_key_factory(col: str):
    def key(row: dict[str, Any]):
        v = row.get(col)
        if v is None:
            return (1, 0, "")
        if isinstance(v, (int, float)):
            return (0, float(v), "")
        return (0, 0, str(v).lower())

    return key
