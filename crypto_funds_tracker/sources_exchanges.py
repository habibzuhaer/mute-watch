from __future__ import annotations

import statistics
import time
from typing import Any

from config import EXCHANGES, REQUEST_DELAY, VOL_WINDOWS_DAYS


def _safe_import_ccxt():
    try:
        import ccxt  # type: ignore

        return ccxt
    except ImportError:
        print("[exchanges] ccxt not installed — prices/vol skipped")
        return None


def fetch_token_market_stats(token_symbols: list[str]) -> dict[str, dict[str, Any]]:
    """
    For each token (BTC, ETH, …) return:
      prices: {exchange: price}
      vol_3m / vol_6m / vol_9m  (annualized stdev of daily returns, %)
      chg_3m / chg_6m / chg_9m  (simple % change)
    Tries several exchanges for both tickers and OHLCV.
    """
    ccxt = _safe_import_ccxt()
    if not ccxt:
        return {}

    out: dict[str, dict[str, Any]] = {}
    candle_exchanges = ["bybit", "okx", "binance", "bingx"]

    for sym in sorted(set(token_symbols)):
        if not sym or sym == "н/д":
            continue
        market = f"{sym}/USDT"
        prices: dict[str, float | None] = {}
        for ex_id in EXCHANGES:
            time.sleep(REQUEST_DELAY / 2)
            try:
                klass = getattr(ccxt, ex_id)
                ex = klass({"enableRateLimit": True})
                t = ex.fetch_ticker(market)
                prices[ex_id] = float(t.get("last") or t.get("close") or 0) or None
            except Exception as exc:
                print(f"[exchanges] ticker {ex_id} {market}: {exc}")
                prices[ex_id] = None

        stats: dict[str, Any] = {"prices": prices}
        closes: list[float] = []
        for ex_id in candle_exchanges:
            try:
                klass = getattr(ccxt, ex_id)
                ex = klass({"enableRateLimit": True})
                ohlcv = ex.fetch_ohlcv(market, timeframe="1d", limit=280)
                closes = [c[4] for c in ohlcv if c and c[4]]
                if len(closes) >= 5:
                    print(f"[exchanges] OHLCV {market} via {ex_id} ({len(closes)} days)")
                    break
            except Exception as exc:
                print(f"[exchanges] OHLCV {ex_id} {market}: {exc}")
                closes = []

        for label, days in VOL_WINDOWS_DAYS.items():
            if len(closes) < 5:
                stats[f"vol_{label}"] = None
                stats[f"chg_{label}"] = None
                continue
            window = closes[-days:] if len(closes) >= days else closes
            rets = [
                (window[i] - window[i - 1]) / window[i - 1]
                for i in range(1, len(window))
                if window[i - 1]
            ]
            if len(rets) < 2:
                stats[f"vol_{label}"] = None
            else:
                daily_std = statistics.pstdev(rets)
                stats[f"vol_{label}"] = round(daily_std * (365**0.5) * 100, 2)
            stats[f"chg_{label}"] = round((window[-1] / window[0] - 1) * 100, 2)

        out[sym] = stats
        time.sleep(REQUEST_DELAY)

    return out
