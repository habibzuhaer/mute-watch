from __future__ import annotations

import html
import logging

import requests

logger = logging.getLogger(__name__)


def _h(value: object) -> str:
    return html.escape(str(value or ""), quote=False)


def send_telegram(
    token: str,
    chat_id: str,
    text: str,
    *,
    dry_run: bool = False,
) -> bool:
    if dry_run:
        logger.info("DRY_RUN telegram:\n%s", text)
        return True
    if not token or not chat_id:
        logger.warning("Telegram token/chat_id missing")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        # trust_env=False: ignore broken HTTP(S)_PROXY from the shell/sandbox
        sess = requests.Session()
        sess.trust_env = False
        resp = sess.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            return True
        logger.error("Telegram error: %s", resp.text[:500])
        try:
            from agents.hooks import on_net_fail

            on_net_fail("mute", resp.text[:200], hint="net_tg")
        except Exception:
            pass
        return False
    except Exception as exc:
        logger.exception("Telegram send failed")
        try:
            from agents.hooks import on_net_fail

            on_net_fail("mute", exc, hint="net_tg")
        except Exception:
            pass
        return False


def format_inbound_alert(event: dict) -> str:
    chain = _h(event.get("chain", "?"))
    label = _h(event.get("wallet_label", "DWF Labs"))
    addr = event.get("address", "")
    short = _short(addr)
    kind = _h(event.get("kind", "transfer"))
    symbol = _h(event.get("symbol", "?"))
    amount = _h(event.get("amount_fmt", "?"))
    usd = _h(event.get("usd_hint")) if event.get("usd_hint") else None
    tx = event.get("tx_hash", "")
    explorer = event.get("explorer_tx", "")
    from_addr = _short(event.get("from_address", ""))

    lines = [
        f"<b>DWF IN</b> · {chain}",
        f"{label}",
        f"<code>{short}</code>",
        f"{kind}: <b>{amount} {symbol}</b>",
    ]
    if usd:
        lines.append(f"≈ {usd}")
    lines.append(f"from <code>{from_addr}</code>")
    if explorer:
        lines.append(f'<a href="{explorer}">tx</a>')
    elif tx:
        lines.append(f"<code>{_short(tx)}</code>")
    return "\n".join(lines)


def format_prep_alert(event: dict) -> str:
    import os

    from pump_prep.i18n_ui import normalize_lang, t

    lang = normalize_lang(os.getenv("MUTE_LANG") or os.getenv("MUTE_UI_LANG") or "en")
    chain = _h(event.get("chain", "?"))
    label = _h(event.get("wallet_label", "seed"))
    prep = event.get("prep_type") or "prep"
    symbol = _h(event.get("symbol", "?"))
    amount = _h(event.get("amount_fmt", "?"))
    explorer = event.get("explorer_tx", "")
    score = event.get("score")
    tier = event.get("tier") or ""
    if tier == "actionable":
        tier_l = t(lang, "tier_act")
    elif tier == "watch":
        tier_l = t(lang, "tier_watch")
    elif tier == "noise":
        tier_l = t(lang, "tier_noise")
    else:
        tier_l = _h(tier)
    title = "PREP · new token IN" if prep == "new_token_in" else "PREP · CEX deposit"
    lines = [
        f"<b>{title}</b> · {chain}",
        f"<b>{tier_l}</b> · score <b>{score if score is not None else '?'}/100</b>",
        f"{label}",
        f"<code>{_short(event.get('address', ''))}</code>",
        f"{_h(event.get('kind', ''))}: <b>{amount} {symbol}</b>",
    ]
    if prep == "cex_deposit" and event.get("cex"):
        lines.append(f"→ <b>{_h(event['cex'])}</b> <code>{_short(event.get('to_address', ''))}</code>")
    else:
        lines.append(f"from <code>{_short(event.get('from_address', ''))}</code>")
    reasons = event.get("reasons_uk") if lang == "uk" else event.get("reasons")
    if not reasons:
        reasons = event.get("reasons") or []
    if reasons:
        why = "why:" if lang == "en" else "чому:"
        lines.append(f"<b>{why}</b>")
        for r in reasons[:6]:
            lines.append(f"· {_h(r)}")
    if explorer:
        lines.append(f'<a href="{explorer}">tx</a>')
    return "\n".join(lines)


def _short(value: str, n: int = 6) -> str:
    if not value:
        return "?"
    if len(value) <= n * 2 + 2:
        return value
    return f"{value[: n + 2]}…{value[-n:]}" if value.startswith("0x") else f"{value[:n]}…{value[-n:]}"
