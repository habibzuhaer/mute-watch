#!/usr/bin/env python3
"""Live build focused on mid-cap tokens ($50M–$600M). Arkham optional."""

from __future__ import annotations

import json

from aggregate import enrich_with_portfolio_pct, merge_market_stats
from config import (
    EXCHANGE_TOP_N,
    FETCH_EXCHANGE_PRICES,
    INCLUDE_DAT_TREASURIES,
    MCAP_MAX_USD,
    MCAP_MIN_USD,
    OUT_DIR,
)
from report import write_report
from sources_arkham import fetch_arkham_portfolios
from sources_coingecko import (
    attach_volatility_from_charts,
    fetch_midcap_markets,
    fetch_public_treasuries,
    filter_by_mcap,
)
from sources_exchanges import fetch_token_market_stats


def main() -> None:
    rows: list = []

    print(
        f"Mid-cap band: ${MCAP_MIN_USD/1e6:.0f}M – ${MCAP_MAX_USD/1e6:.0f}M "
        f"(BTC/ETH excluded)"
    )
    print("Fetching CoinGecko mid-cap markets…")
    rows.extend(fetch_midcap_markets())
    print(f"  midcap rows: {len(rows)}")

    if INCLUDE_DAT_TREASURIES:
        print("Fetching public company treasuries (mostly BTC/ETH — usually filtered out)…")
        dat = fetch_public_treasuries()
        rows.extend(dat)
        print(f"  DAT rows added: {len(dat)}")

    print("Fetching optional Arkham VC block…")
    ark = fetch_arkham_portfolios()
    print(f"  Arkham rows: {len(ark)}")
    rows.extend(ark)

    rows = filter_by_mcap(rows)
    print(f"After mcap filter: {len(rows)}")

    print("Attaching vol/chg from CoinGecko charts (top by volume)…")
    rows = attach_volatility_from_charts(rows)

    # Prefer CoinGecko spot; optional CEX fan-out
    if FETCH_EXCHANGE_PRICES:
        top_syms = []
        seen = set()
        for r in sorted(rows, key=lambda x: -(x.get("volume_24h") or 0)):
            t = r["token"]
            if t not in seen:
                seen.add(t)
                top_syms.append(t)
            if len(top_syms) >= EXCHANGE_TOP_N:
                break
        print(f"Fetching exchange prices for top {len(top_syms)} by volume…")
        market = fetch_token_market_stats(top_syms)
        rows = merge_market_stats(rows, market)

    rows = enrich_with_portfolio_pct(rows)

    for r in rows:
        if r.get("price_binance") is None and r.get("price_coingecko") is not None:
            r["price_binance"] = r["price_coingecko"]

    json_path = OUT_DIR / "crypto_funds_data.json"
    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    html_path = write_report(
        rows,
        OUT_DIR / "crypto_funds_report.html",
        title=f"Mid-cap tokens ${MCAP_MIN_USD/1e6:.0f}M–${MCAP_MAX_USD/1e6:.0f}M",
    )
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")
    print(f"Open: file://{html_path.resolve()}")
    print(
        "Note: without Arkham API, fund holdings for these tokens = н/д. "
        "Table shows mid-cap market + vol/chg."
    )


if __name__ == "__main__":
    main()
