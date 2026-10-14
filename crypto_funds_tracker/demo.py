#!/usr/bin/env python3
"""Synthetic preview — no API keys / network required for table UI."""

from __future__ import annotations

from pathlib import Path

from aggregate import enrich_with_portfolio_pct, merge_market_stats
from config import OUT_DIR
from report import write_report

DEMO_ROWS = [
    {
        "fund_name": "Strategy",
        "fund_type": "public_company_dat",
        "website": "https://www.strategy.com",
        "ticker": "MSTR.US",
        "token": "BTC",
        "amount": 843775.0,
        "entry_price_usd": 75480.0,
        "current_value_usd": 53_800_000_000,
        "held_since": "н/д",
        "source": "demo",
    },
    {
        "fund_name": "Strategy",
        "fund_type": "public_company_dat",
        "website": "https://www.strategy.com",
        "ticker": "MSTR.US",
        "token": "ETH",
        "amount": 0.0,
        "entry_price_usd": None,
        "current_value_usd": 0,
        "held_since": "н/д",
        "source": "demo",
    },
    {
        "fund_name": "BitMine Immersion",
        "fund_type": "public_company_dat",
        "website": "https://bitminetech.io",
        "ticker": "BMNR.US",
        "token": "ETH",
        "amount": 5_787_414.0,
        "entry_price_usd": None,
        "current_value_usd": 11_000_000_000,
        "held_since": "н/д",
        "source": "demo",
    },
    {
        "fund_name": "MARA Holdings",
        "fund_type": "public_company_dat",
        "website": "https://www.mara.com",
        "ticker": "MARA.US",
        "token": "BTC",
        "amount": 35303.0,
        "entry_price_usd": None,
        "current_value_usd": 2_250_000_000,
        "held_since": "н/д",
        "source": "demo",
    },
    {
        "fund_name": "Metaplanet",
        "fund_type": "public_company_dat",
        "website": "https://metaplanet.jp",
        "ticker": "3350.T",
        "token": "BTC",
        "amount": 43000.0,
        "entry_price_usd": 88622.0,
        "current_value_usd": 2_740_000_000,
        "held_since": "н/д",
        "source": "demo",
    },
]

DEMO_MARKET = {
    "BTC": {
        "prices": {"binance": 63800.0, "bybit": 63810.0, "okx": 63790.0, "bingx": 63805.0},
        "vol_3m": 42.1,
        "vol_6m": 48.5,
        "vol_9m": 51.2,
        "chg_3m": 12.4,
        "chg_6m": -3.2,
        "chg_9m": 28.7,
    },
    "ETH": {
        "prices": {"binance": 1905.0, "bybit": 1906.2, "okx": 1904.5, "bingx": 1905.8},
        "vol_3m": 55.0,
        "vol_6m": 61.3,
        "vol_9m": 64.8,
        "chg_3m": 8.1,
        "chg_6m": -11.4,
        "chg_9m": 15.2,
    },
}


def main() -> None:
    rows = enrich_with_portfolio_pct(DEMO_ROWS)
    # drop zero-amount demo noise
    rows = [r for r in rows if (r.get("amount") or 0) > 0]
    rows = merge_market_stats(rows, DEMO_MARKET)
    out = write_report(rows, OUT_DIR / "crypto_funds_report.html", title="Crypto Funds — DEMO")
    print(f"Wrote {out}")
    print(f"Open: file://{out.resolve()}")


if __name__ == "__main__":
    main()
