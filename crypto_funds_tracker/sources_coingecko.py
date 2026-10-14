from __future__ import annotations

import statistics
import time
from typing import Any

import requests

from config import (
    COINGECKO_API_KEY,
    COINGECKO_BASE,
    EXCLUDE_IDS,
    EXCLUDE_SYMBOLS,
    FUND_WEBSITES,
    MCAP_MAX_USD,
    MCAP_MIN_USD,
    MIDCAP_LIMIT,
    REQUEST_DELAY,
    REQUEST_TIMEOUT,
    TREASURY_COINS,
    VOL_CHART_TOP_N,
    VOL_WINDOWS_DAYS,
)


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    s.headers.update({"User-Agent": "crypto-funds-tracker/1.0", "Accept": "application/json"})
    if COINGECKO_API_KEY:
        s.headers["x-cg-pro-api-key"] = COINGECKO_API_KEY
    return s


def fetch_public_treasuries(coins: list[str] | None = None) -> list[dict[str, Any]]:
    """Return one row per (company, coin) from CoinGecko public treasury."""
    coins = coins or TREASURY_COINS
    sess = _session()
    rows: list[dict[str, Any]] = []

    for coin_id in coins:
        time.sleep(REQUEST_DELAY)
        url = f"{COINGECKO_BASE}/companies/public_treasury/{coin_id}"
        try:
            resp = sess.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"[coingecko] {coin_id} failed: {exc}")
            continue

        symbol = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL"}.get(
            coin_id, coin_id.upper()
        )
        for c in data.get("companies") or []:
            name = c.get("name") or "Unknown"
            holdings = float(c.get("total_holdings") or 0)
            entry_usd = float(c.get("total_entry_value_usd") or 0)
            current_usd = float(c.get("total_current_value_usd") or 0)
            entry_price = (entry_usd / holdings) if holdings and entry_usd else None
            rows.append(
                {
                    "fund_name": name,
                    "fund_type": "public_company_dat",
                    "website": FUND_WEBSITES.get(name, ""),
                    "ticker": c.get("symbol") or "",
                    "country": c.get("country") or "",
                    "token": symbol,
                    "token_id": coin_id,
                    "amount": holdings,
                    "entry_price_usd": entry_price,
                    "entry_value_usd": entry_usd or None,
                    "current_value_usd": current_usd or None,
                    "pct_of_token_supply": c.get("percentage_of_total_supply"),
                    "market_cap": None,
                    "held_since": None,
                    "source": "coingecko_public_treasury",
                }
            )
    return rows


def fetch_midcap_markets(
    *,
    mcap_min: float = MCAP_MIN_USD,
    mcap_max: float = MCAP_MAX_USD,
    limit: int = MIDCAP_LIMIT,
) -> list[dict[str, Any]]:
    """
    Mid/small-mid cap token universe from CoinGecko markets.
    Fund holdings = н/д without Arkham; this fills prices / mcap / % change.
    """
    sess = _session()
    collected: list[dict[str, Any]] = []
    page = 1
    while page <= 6 and len(collected) < limit * 2:
        time.sleep(REQUEST_DELAY)
        try:
            resp = sess.get(
                f"{COINGECKO_BASE}/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": 250,
                    "page": page,
                    "sparkline": "false",
                    "price_change_percentage": "30d,90d,180d,365d",
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            batch = resp.json()
        except Exception as exc:
            print(f"[coingecko] markets page {page}: {exc}")
            break
        if not batch:
            break
        for c in batch:
            mcap = c.get("market_cap")
            if mcap is None:
                continue
            if mcap > mcap_max:
                continue
            if mcap < mcap_min:
                continue
            cid = (c.get("id") or "").lower()
            sym = (c.get("symbol") or "").upper()
            if cid in EXCLUDE_IDS or sym in EXCLUDE_SYMBOLS:
                continue
            collected.append(
                {
                    "fund_name": "— (нет данных по фондам без Arkham API)",
                    "fund_type": "midcap_watch",
                    "website": f"https://www.coingecko.com/en/coins/{c.get('id')}",
                    "ticker": "",
                    "country": "",
                    "token": sym,
                    "token_id": c.get("id"),
                    "amount": None,
                    "entry_price_usd": None,
                    "entry_value_usd": None,
                    "current_value_usd": None,
                    "portfolio_pct": None,
                    "pct_of_token_supply": None,
                    "market_cap": float(mcap),
                    "held_since": None,
                    "price_coingecko": c.get("current_price"),
                    "chg_30d": c.get("price_change_percentage_30d_in_currency"),
                    "chg_90d": c.get("price_change_percentage_90d_in_currency"),
                    "chg_180d": c.get("price_change_percentage_180d_in_currency"),
                    "chg_365d": c.get("price_change_percentage_365d_in_currency"),
                    "volume_24h": c.get("total_volume"),
                    "source": "coingecko_markets_midcap",
                }
            )
        last_mcap = batch[-1].get("market_cap") or 0
        if last_mcap < mcap_min:
            break
        page += 1

    collected.sort(key=lambda r: -(r.get("volume_24h") or 0))
    rows = collected[:limit]
    print(f"[coingecko] midcap rows in band: {len(collected)} → keep {len(rows)}")
    return rows


def attach_volatility_from_charts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annualized vol + period chg from daily market_chart for top-N by volume."""
    sess = _session()
    ranked = sorted(rows, key=lambda r: -(r.get("volume_24h") or 0))
    targets = {r["token_id"] for r in ranked[:VOL_CHART_TOP_N] if r.get("token_id")}

    cache: dict[str, dict[str, float | None]] = {}
    for tid in targets:
        time.sleep(REQUEST_DELAY)
        try:
            resp = sess.get(
                f"{COINGECKO_BASE}/coins/{tid}/market_chart",
                params={"vs_currency": "usd", "days": "270", "interval": "daily"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            prices = [p[1] for p in (resp.json().get("prices") or []) if p and p[1]]
        except Exception as exc:
            print(f"[coingecko] chart {tid}: {exc}")
            continue
        if len(prices) < 10:
            continue
        stats: dict[str, float | None] = {}
        for label, days in VOL_WINDOWS_DAYS.items():
            window = prices[-days:] if len(prices) >= days else prices
            rets = [
                (window[i] - window[i - 1]) / window[i - 1]
                for i in range(1, len(window))
                if window[i - 1]
            ]
            if len(rets) < 2:
                stats[f"vol_{label}"] = None
                stats[f"chg_{label}"] = None
            else:
                stats[f"vol_{label}"] = round(
                    statistics.pstdev(rets) * (365**0.5) * 100, 2
                )
                stats[f"chg_{label}"] = round((window[-1] / window[0] - 1) * 100, 2)
        cache[tid] = stats

    out = []
    for r in rows:
        r = dict(r)
        # Fill period changes from markets payload first (no extra API calls)
        if r.get("chg_3m") is None and r.get("chg_90d") is not None:
            r["chg_3m"] = round(float(r["chg_90d"]), 2)
        if r.get("chg_6m") is None and r.get("chg_180d") is not None:
            r["chg_6m"] = round(float(r["chg_180d"]), 2)
        if r.get("chg_9m") is None and r.get("chg_365d") is not None:
            r["chg_9m"] = round(float(r["chg_365d"]), 2)
        s = cache.get(r.get("token_id") or "", {})
        for k, v in s.items():
            if v is not None:
                r[k] = v
        out.append(r)
    return out


def filter_by_mcap(
    rows: list[dict[str, Any]],
    *,
    mcap_min: float = MCAP_MIN_USD,
    mcap_max: float = MCAP_MAX_USD,
) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        sym = (r.get("token") or "").upper()
        tid = (r.get("token_id") or "").lower()
        if sym in EXCLUDE_SYMBOLS or tid in EXCLUDE_IDS:
            continue
        mcap = r.get("market_cap")
        if mcap is None:
            continue
        if mcap_min <= float(mcap) <= mcap_max:
            out.append(r)
    return out
