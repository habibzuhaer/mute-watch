from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from mute.amount_filter import passes_min_usdt
from mute.burst import record_and_boost
from mute.config import Settings, load_wallets, resource_estimate, solana_rpc_usable
from mute.pace import Pace
from mute.pollers.evm import fetch_evm_inbounds
from mute.pollers.solana import fetch_solana_inbounds
from mute.pollers.tron import fetch_tron_inbounds
from mute.prep_filter import annotate_prep, is_prep_signal
from mute.store import SeenStore
from mute.telegram import format_inbound_alert, format_prep_alert, send_telegram

try:
    from alerts.normalize import from_dwf_inbound, from_live_prep
    from alerts.router import ActivityRouter

    _ALERTS_OK = True
except Exception:  # pragma: no cover
    ActivityRouter = None  # type: ignore
    from_live_prep = None  # type: ignore
    from_dwf_inbound = None  # type: ignore
    _ALERTS_OK = False

try:
    from pump_prep import graph_store as gs
except Exception:  # pragma: no cover
    gs = None  # type: ignore

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.wallets = load_wallets(settings.addresses_file)
        self.store = SeenStore(settings.data_dir / "seen.sqlite")
        self.pace = Pace(settings.request_delay_sec)
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": "MUTE-DWF-Monitor/0.1"})
        self._alert_router: ActivityRouter | None = None
        self._sol_skip_logged = False
        if _ALERTS_OK and ActivityRouter is not None:
            try:
                self._alert_router = ActivityRouter.from_settings(settings)
            except Exception:
                logger.debug("ActivityRouter init failed", exc_info=True)

    def _route_alert(self, event: dict[str, Any], *, prep: bool) -> tuple[str, bool]:
        if self._alert_router and self._alert_router.enabled and from_live_prep and from_dwf_inbound:
            activity = from_live_prep(event) if prep else from_dwf_inbound(event)
            result = self._alert_router.route(activity)
            consumed = bool(result.sent) or (result.reason or "") != "send_failed"
            if not result.sent and consumed:
                logger.info("Alert not pushed (%s)", result.reason)
            return result.text, consumed
        text = format_prep_alert(event) if prep else format_inbound_alert(event)
        ok = send_telegram(
            self.settings.telegram_bot_token,
            self.settings.telegram_chat_id,
            text,
            dry_run=self.settings.dry_run,
        )
        score = int(event.get("score") or 0)
        if prep:
            level = "ACT" if score >= 55 else ("WATCH" if score >= 40 else "INFO")
        else:
            level = "WATCH"
        self._bus_mute(event, level, prep=prep)
        return text, ok

    @staticmethod
    def _bus_mute(event: dict[str, Any], level: str, *, prep: bool) -> None:
        if (level or "").upper() not in {"ACT", "CRITICAL", "WATCH"}:
            return
        try:
            from agents.hooks import on_signal

            on_signal(
                "mute",
                "prep_act" if prep else "dwf_inbound",
                level=level,
                score=int(event.get("score") or 0),
                ref=str(event.get("symbol") or event.get("tx_hash") or "")[:80],
                extra={"chain": event.get("chain"), "tier": event.get("tier")},
            )
        except Exception:
            logger.debug("agents bus mute skipped", exc_info=True)

    def estimate(self) -> dict:
        est = resource_estimate(self.settings, self.wallets)
        est["parallel_workers"] = self.settings.parallel_workers
        est["mode"] = "parallel" if self.settings.parallel else "sequential"
        return est

    def bootstrap_if_needed(self) -> None:
        if self.store.get_meta("bootstrapped") == "1":
            return
        logger.info("First run: seeding seen keys (no Telegram spam)…")
        events = self._collect_all()
        keys = [e["dedupe_key"] for e in events if e.get("dedupe_key")]
        self.store.add_many(keys)
        self.store.set_meta("bootstrapped", "1")
        logger.info("Bootstrapped %d existing transfers as seen", len(keys))

    def poll_once(self) -> int:
        events = self._collect_all()
        if self.settings.alert_mode == "prep":
            events = [annotate_prep(e) for e in events if is_prep_signal(e)]
        events.sort(key=lambda e: e.get("timestamp") or 0)
        sent = 0
        skipped_low = 0
        skipped_amount = 0
        for event in events:
            key = event.get("dedupe_key")
            if not key or self.store.has(key):
                continue
            if not passes_min_usdt(event, self.settings.min_usdt):
                self.store.add(key)
                skipped_amount += 1
                continue
            if self.settings.alert_mode == "prep":
                # Cluster of small txs can boost score without lowering global floor
                try:
                    event = record_and_boost(event)
                except Exception:
                    logger.debug("burst boost skipped", exc_info=True)
                score = int(event.get("score") or 0)
                if score < self.settings.signal_min_score:
                    # Still mark seen so we don't re-evaluate forever; journal only
                    self.store.add(key)
                    skipped_low += 1
                    if gs is not None:
                        try:
                            gs.add_signal(
                                source="live_prep_skipped",
                                symbol=event.get("symbol"),
                                direction="out" if "OUT" in (event.get("kind") or "") else "in",
                                match_entity=event.get("cex") or event.get("wallet_label"),
                                match_role="live",
                                timestamp=event.get("timestamp"),
                                hash=event.get("tx_hash"),
                                score=event.get("score"),
                                tier=event.get("tier"),
                                reasons=event.get("reasons"),
                                signal_kind=event.get("signal_kind"),
                                summary=event.get("summary"),
                                telegram_worthy=False,
                                min_score_rule=self.settings.signal_min_score,
                            )
                        except Exception:
                            logger.debug("signal journal skip failed", exc_info=True)
                    continue
                text, ok = self._route_alert(event, prep=True)
            else:
                text, ok = self._route_alert(event, prep=False)
            if ok:
                self.store.add(key)
                sent += 1
                if self.settings.alert_mode == "prep" and gs is not None:
                    try:
                        gs.add_signal(
                            source="live_prep",
                            symbol=event.get("symbol"),
                            direction="out" if "OUT" in (event.get("kind") or "") else "in",
                            match_entity=event.get("cex") or event.get("wallet_label"),
                            match_role="live",
                            timestamp=event.get("timestamp"),
                            hash=event.get("tx_hash"),
                            score=event.get("score"),
                            tier=event.get("tier"),
                            reasons=event.get("reasons"),
                            signal_kind=event.get("signal_kind"),
                            summary=event.get("summary"),
                            telegram_worthy=True,
                            min_score_rule=self.settings.signal_min_score,
                        )
                    except Exception:
                        logger.debug("signal journal write failed", exc_info=True)
                time.sleep(0.35)
            else:
                logger.error("Alert not sent, will retry next cycle: %s", key)
        if skipped_low:
            logger.info(
                "Prep: skipped %s below SIGNAL_MIN_SCORE=%s",
                skipped_low,
                self.settings.signal_min_score,
            )
        if skipped_amount:
            logger.info(
                "Skipped %s below MIN_USDT=%s (stables only)",
                skipped_amount,
                self.settings.min_usdt,
            )
        return sent

    def run_forever(self) -> None:
        est = self.estimate()
        logger.info(
            "MUTE start mode=%s workers=%s alert_mode=%s profile=%s chains=%s calls/cycle≈%s interval=%ss",
            est["mode"],
            est["parallel_workers"],
            self.settings.alert_mode,
            est["profile"],
            est["evm_chains"],
            est["api_calls_per_cycle"],
            est["poll_interval_sec"],
        )
        self.bootstrap_if_needed()
        send_telegram(
            self.settings.telegram_bot_token,
            self.settings.telegram_chat_id,
            (
                "<b>MUTE online</b>\n"
                f"mode: <code>{est['mode']}</code> · workers: {est['parallel_workers']}\n"
                f"alert: <code>{self.settings.alert_mode}</code>"
                + (
                    f" · min_score={self.settings.signal_min_score}"
                    if self.settings.alert_mode == "prep"
                    else ""
                )
                + (
                    f" · min_usdt={self.settings.min_usdt:g}"
                    if self.settings.min_usdt and self.settings.min_usdt > 0
                    else ""
                )
                + "\n"
                f"profile: <code>{est['profile']}</code>\n"
                f"EVM chains: {est['evm_chains']} · wallets: "
                f"{est['evm_addresses']} EVM / {est['sol_addresses']} SOL / {est['tron_addresses']} TRON\n"
                f"≈{est['api_calls_per_cycle']} API calls/cycle · every {est['poll_interval_sec']}s"
            ),
            dry_run=self.settings.dry_run,
        )
        while True:
            try:
                t0 = time.monotonic()
                n = self.poll_once()
                dt = time.monotonic() - t0
                logger.info("Cycle done in %.1fs, alerts=%d", dt, n)
                try:
                    from agents.hooks import on_action

                    on_action("mute", "цикл", f"alerts={n}", detail=f"{dt:.1f}s")
                except Exception:
                    pass
            except Exception:
                logger.exception("Poll cycle failed")
                try:
                    from agents.hooks import on_net_fail

                    on_net_fail("mute", "poll cycle failed", hint="net_rpc")
                except Exception:
                    pass
            try:
                from agents.hooks import beat

                beat("mute")
            except Exception:
                pass
            time.sleep(max(15, self.settings.poll_interval_sec))

    def _collect_all(self) -> list[dict[str, Any]]:
        wallets = [w for w in self.wallets if w.get("address")]
        if not wallets:
            return []

        if not self.settings.parallel or self.settings.parallel_workers <= 1:
            out: list[dict[str, Any]] = []
            for w in wallets:
                out.extend(self._fetch_wallet(w))
            return out

        workers = min(self.settings.parallel_workers, len(wallets))
        out = []
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="mute-wallet"
        ) as pool:
            futs = {pool.submit(self._fetch_wallet, w): w for w in wallets}
            for fut in as_completed(futs):
                w = futs[fut]
                try:
                    out.extend(fut.result())
                except Exception:
                    logger.exception(
                        "Parallel wallet failed %s",
                        w.get("address"),
                    )
                    try:
                        from agents.hooks import on_net_fail

                        on_net_fail("mute", f"wallet {w.get('address')}", hint="net_rpc")
                    except Exception:
                        pass
        return out

    def _fetch_wallet(self, w: dict) -> list[dict[str, Any]]:
        s = self.settings
        family = (w.get("family") or "").lower()
        address = w.get("address") or ""
        label = w.get("label") or "DWF Labs"
        try:
            if family == "evm":
                return fetch_evm_inbounds(
                    address=address,
                    wallet_label=label,
                    chains=s.chains,
                    api_key=s.etherscan_api_key,
                    alert_tokens=s.alert_tokens,
                    alert_native=s.alert_native if s.alert_mode != "prep" else False,
                    request_delay_sec=s.request_delay_sec,
                    workers=s.parallel_workers if s.parallel else 1,
                    pace=self.pace,
                    include_token_out=(s.alert_mode == "prep"),
                )
            if family == "solana":
                if not solana_rpc_usable(s.helius_api_key, s.solana_rpc_url):
                    if not self._sol_skip_logged:
                        logger.info("Solana skip — public RPC (set HELIUS_API_KEY)")
                        self._sol_skip_logged = True
                    return []
                self.pace.wait()
                sess = requests.Session()
                sess.trust_env = False
                return fetch_solana_inbounds(
                    address=address,
                    wallet_label=label,
                    rpc_url=s.solana_rpc_url,
                    helius_api_key=s.helius_api_key,
                    session=sess,
                )
            if family == "tron":
                self.pace.wait()
                sess = requests.Session()
                sess.trust_env = False
                return fetch_tron_inbounds(
                    address=address,
                    wallet_label=label,
                    api_key=s.trongrid_api_key,
                    session=sess,
                )
            logger.warning("Unknown family %s for %s", family, address)
            return []
        except Exception:
            logger.exception("Failed wallet %s (%s)", address, family)
            try:
                from agents.hooks import on_net_fail

                on_net_fail("mute", f"{family} {address}", hint="net_rpc")
            except Exception:
                pass
            return []
