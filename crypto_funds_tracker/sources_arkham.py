from __future__ import annotations

from typing import Any

from config import ARKHAM_API_KEY, ARKHAM_ENTITIES


def fetch_arkham_portfolios() -> list[dict[str, Any]]:
    """
    Optional VC/hedge portfolios via Arkham Intelligence.

    Without ARKHAM_API_KEY returns [] (block skipped). Full entity portfolio
    endpoints require a paid Arkham API key — see https://intel.arkm.com
    """
    if not ARKHAM_API_KEY:
        print("[arkham] skipped — ARKHAM_API_KEY empty")
        return []

    # Placeholder for paid integration. Keep shape compatible with aggregate.
    # When key is present, caller expects real rows; without implementing the
    # proprietary client we return an explicit stub note row set.
    print(
        "[arkham] key set, but live Arkham client is not bundled — "
        "add API calls in sources_arkham.py for your plan"
    )
    rows: list[dict[str, Any]] = []
    for ent in ARKHAM_ENTITIES:
        rows.append(
            {
                "fund_name": ent["name"],
                "fund_type": "vc_hedge",
                "website": ent.get("website") or "",
                "ticker": "",
                "country": "",
                "token": "н/д",
                "token_id": "",
                "amount": None,
                "entry_price_usd": None,
                "entry_value_usd": None,
                "current_value_usd": None,
                "pct_of_token_supply": None,
                "held_since": None,
                "portfolio_pct": None,
                "source": "arkham_pending_integration",
                "note": "Set up Arkham entity holdings API for this plan",
            }
        )
    return rows
