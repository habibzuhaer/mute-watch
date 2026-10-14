from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

SOLSCAN_TX = "https://solscan.io/tx/"
_RATE_LIMITED = object()
_PUBLIC_TX_CAP = 12


def fetch_solana_inbounds(
    *,
    address: str,
    wallet_label: str,
    rpc_url: str,
    helius_api_key: str = "",
    limit: int = 50,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    sess = session or requests.Session()
    url = rpc_url
    if helius_api_key and "helius" not in rpc_url:
        url = f"https://mainnet.helius-rpc.com/?api-key={helius_api_key}"

    sigs = _rpc(
        sess,
        url,
        "getSignaturesForAddress",
        [address, {"limit": limit}],
    )
    if not isinstance(sigs, list):
        return []
    if "helius" not in url:
        sigs = sigs[: min(len(sigs), _PUBLIC_TX_CAP)]

    events: list[dict[str, Any]] = []
    for item in sigs:
        sig = item.get("signature")
        if not sig:
            continue
        if item.get("err"):
            continue
        parsed = _rpc(
            sess,
            url,
            "getTransaction",
            [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        )
        if parsed is _RATE_LIMITED:
            logger.warning("Solana 429 — stop remaining txs for %s this cycle", address[:12])
            break
        if not parsed:
            continue
        meta = parsed.get("meta") or {}
        if meta.get("err"):
            continue
        block_time = parsed.get("blockTime") or 0

        # Native SOL balance increase for this account
        account_keys = _account_keys(parsed)
        try:
            idx = account_keys.index(address)
        except ValueError:
            idx = None

        if idx is not None:
            pre = (meta.get("preBalances") or [0])[idx]
            post = (meta.get("postBalances") or [0])[idx]
            delta = post - pre
            if delta > 0:
                events.append(
                    {
                        "dedupe_key": f"sol:nat:{sig}:{address}",
                        "chain": "Solana",
                        "address": address,
                        "wallet_label": wallet_label,
                        "kind": "SOL IN",
                        "symbol": "SOL",
                        "amount_fmt": f"{delta / 1_000_000_000:.9f}".rstrip("0").rstrip("."),
                        "from_address": "?",
                        "tx_hash": sig,
                        "explorer_tx": f"{SOLSCAN_TX}{sig}",
                        "timestamp": int(block_time),
                    }
                )

        # SPL token balance increases
        pre_tok = {
            _tok_owner_mint(x): _tok_amount(x)
            for x in (meta.get("preTokenBalances") or [])
            if _tok_owner(x) == address
        }
        for post_bal in meta.get("postTokenBalances") or []:
            if _tok_owner(post_bal) != address:
                continue
            key = _tok_owner_mint(post_bal)
            before = pre_tok.get(key, 0.0)
            after = _tok_amount(post_bal)
            delta = after - before
            if delta <= 0:
                continue
            mint = (post_bal.get("mint") or "")[:12]
            ui = post_bal.get("uiTokenAmount") or {}
            symbol = ui.get("uiAmountString") and (mint or "SPL") or "SPL"
            # Prefer mint short as symbol when unknown
            events.append(
                {
                    "dedupe_key": f"sol:tok:{sig}:{key}",
                    "chain": "Solana",
                    "address": address,
                    "wallet_label": wallet_label,
                    "kind": "SPL IN",
                    "symbol": mint or "SPL",
                    "amount_fmt": f"{delta:.8f}".rstrip("0").rstrip("."),
                    "from_address": "?",
                    "tx_hash": sig,
                    "explorer_tx": f"{SOLSCAN_TX}{sig}",
                    "timestamp": int(block_time),
                }
            )

    return events


def _account_keys(parsed: dict) -> list[str]:
    msg = (parsed.get("transaction") or {}).get("message") or {}
    keys = msg.get("accountKeys") or []
    out: list[str] = []
    for k in keys:
        if isinstance(k, str):
            out.append(k)
        elif isinstance(k, dict):
            out.append(k.get("pubkey", ""))
    return out


def _tok_owner(bal: dict) -> str:
    return bal.get("owner") or ""


def _tok_owner_mint(bal: dict) -> str:
    return f"{_tok_owner(bal)}:{(bal.get('mint') or '')}"


def _tok_amount(bal: dict) -> float:
    ui = bal.get("uiTokenAmount") or {}
    try:
        if ui.get("uiAmount") is not None:
            return float(ui["uiAmount"])
        return float(ui.get("uiAmountString") or 0)
    except Exception:
        return 0.0


def _rpc(sess: requests.Session, url: str, method: str, params: list) -> Any:
    for attempt in range(3):
        try:
            resp = sess.post(
                url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                timeout=40,
            )
            if resp.status_code == 429:
                wait = 1.5 * (attempt + 1)
                logger.warning("Solana RPC 429 method=%s — sleep %.1fs", method, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                err = data["error"]
                msg = str(err)
                if "429" in msg or "rate" in msg.lower():
                    wait = 1.5 * (attempt + 1)
                    logger.warning("Solana RPC rate method=%s — sleep %.1fs", method, wait)
                    time.sleep(wait)
                    continue
                logger.warning("Solana RPC error %s: %s", method, err)
                return None
            return data.get("result")
        except requests.HTTPError as exc:
            code = getattr(exc.response, "status_code", None)
            if code == 429:
                wait = 1.5 * (attempt + 1)
                logger.warning("Solana RPC 429 method=%s — sleep %.1fs", method, wait)
                time.sleep(wait)
                continue
            logger.warning("Solana RPC failed method=%s: %s", method, exc)
            return None
        except Exception as exc:
            logger.warning("Solana RPC failed method=%s: %s", method, exc)
            return None
    logger.warning("Solana RPC still 429 method=%s — skip", method)
    return _RATE_LIMITED
