"""ActivityRouter — normalize → level → template → optional LocalBrain → push."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alerts.config import (
    DATA_DIR,
    DEDUP_TTL_SEC,
    DRY_RUN,
    ENABLED,
    JOURNAL_FILE,
    LANG,
    MIN_SCORE_GRAPH,
    MIN_SCORE_INTEL_PREPUMP,
    MIN_SCORE_INTEL_SPIKE,
    MIN_SCORE_PREP,
    MIN_SCORE_ROZVIDKA,
    MONEY_MIN_SCORE,
    MONEY_MODE,
    MONEY_TYPES,
    PUSH_WATCH,
    USE_LOCAL_BRAIN,
)
from alerts.dedup import AlertDedup
from alerts.levels import LEVELS, resolve_level, should_push
from alerts.local_brain import LocalBrain
from alerts.template_engine import TemplateEngine

logger = logging.getLogger(__name__)


@dataclass
class RouteResult:
    sent: bool
    level: str
    template_id: str
    text: str
    activity: dict[str, Any]
    reason: str
    enriched: dict[str, Any] | None = None


class ActivityRouter:
    def __init__(
        self,
        *,
        lang: str | None = None,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        dry_run: bool = False,
        enabled: bool = True,
        use_local_brain: bool | None = None,
        min_scores: dict[str, int] | None = None,
    ) -> None:
        self.lang = lang or LANG
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.dry_run = dry_run or DRY_RUN
        self.enabled = enabled and ENABLED
        self.engine = TemplateEngine(lang=self.lang)
        self.dedup = AlertDedup(ttl_sec=DEDUP_TTL_SEC)
        self.brain = LocalBrain() if (use_local_brain if use_local_brain is not None else USE_LOCAL_BRAIN) else None
        floor = max(MIN_SCORE_PREP, MONEY_MIN_SCORE) if MONEY_MODE else MIN_SCORE_PREP
        graph_floor = max(MIN_SCORE_GRAPH, MONEY_MIN_SCORE) if MONEY_MODE else MIN_SCORE_GRAPH
        prepump_floor = max(MIN_SCORE_INTEL_PREPUMP, MONEY_MIN_SCORE) if MONEY_MODE else MIN_SCORE_INTEL_PREPUMP
        self.min_scores = min_scores or {
            "prep_live": floor,
            "prep_new_token_in": floor,
            "prep_cex_deposit": floor,
            "graph_act": graph_floor,
            "graph_watch": graph_floor + 999 if MONEY_MODE else MIN_SCORE_GRAPH - 15,
            "intel_spike": 999 if MONEY_MODE else MIN_SCORE_INTEL_SPIKE,
            "intel_prepump": prepump_floor,
            "rozvidka_critical": 999 if MONEY_MODE else MIN_SCORE_ROZVIDKA,
            "rozvidka_watch": 999 if MONEY_MODE else MIN_SCORE_ROZVIDKA,
            "dwf_inbound": 999 if MONEY_MODE else 0,
            "system_stale": 999 if MONEY_MODE else 40,
        }
        self.money_mode = MONEY_MODE
        self.money_types = set(MONEY_TYPES)
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_settings(cls, settings: Any) -> ActivityRouter:
        floor = max(int(getattr(settings, "signal_min_score", MIN_SCORE_PREP) or MIN_SCORE_PREP), MONEY_MIN_SCORE if MONEY_MODE else 0)
        return cls(
            telegram_token=getattr(settings, "telegram_bot_token", ""),
            telegram_chat_id=getattr(settings, "telegram_chat_id", ""),
            dry_run=getattr(settings, "dry_run", False),
            min_scores={
                "prep_live": floor,
                "prep_new_token_in": floor,
                "prep_cex_deposit": floor,
                "graph_act": max(MIN_SCORE_GRAPH, MONEY_MIN_SCORE if MONEY_MODE else 0),
                "intel_prepump": max(MIN_SCORE_INTEL_PREPUMP, MONEY_MIN_SCORE if MONEY_MODE else 0),
            },
        )

    def _tg_allowed(self, activity: dict[str, Any], level: str) -> bool:
        """Money mode: only ACT/CRITICAL money types reach Telegram."""
        if not self.money_mode:
            return True
        atype = activity.get("activity_type") or activity.get("type") or ""
        if atype not in self.money_types:
            return False
        if level not in {"ACT", "CRITICAL"}:
            return False
        if int(activity.get("score") or 0) < MONEY_MIN_SCORE:
            return False
        return True

    def route(
        self,
        activity: dict[str, Any],
        *,
        channel: str = "telegram",
        force: bool = False,
    ) -> RouteResult:
        if not self.enabled and not force:
            return RouteResult(False, "NOISE", "", "", activity, "disabled")

        atype = activity.get("activity_type") or activity.get("type") or "generic"
        score = int(activity.get("score") or 0)
        min_sc = self.min_scores.get(atype, 0)
        if score < min_sc and not force:
            return RouteResult(False, "NOISE", "", "", activity, f"score<{min_sc}")

        level = resolve_level(activity)
        if level == "NOISE" and not force:
            return RouteResult(False, level, "", "", activity, "noise level")

        dedupe_key = self.dedup.key_for(activity)
        if self.dedup.seen(dedupe_key) and not force:
            return RouteResult(False, level, "", "", activity, "dedup")

        enriched = None
        if self.brain:
            try:
                enriched = self.brain.activity_enrich(activity, lang=self.lang, level=level)
                if enriched.get("noise"):
                    self.dedup.mark(dedupe_key)
                    self._journal(activity, level, "", "brain_noise", enriched)
                    return RouteResult(False, "NOISE", "", "", activity, "brain_noise", enriched)
                if enriched.get("level_override"):
                    level = enriched["level_override"]
                if enriched.get("action_hint"):
                    activity = {**activity, "brain_action": enriched["action_hint"]}
                if enriched.get("summary"):
                    activity = {**activity, "brain_summary": enriched["summary"]}
            except Exception as exc:
                logger.debug("LocalBrain enrich failed", exc_info=True)
                try:
                    from agents.hooks import on_net_fail

                    on_net_fail(str(activity.get("source") or "mute"), exc, hint="net_llm")
                except Exception:
                    pass

        template_id = self.engine.pick_template_id(activity, level)
        text = self.engine.render(activity, level=level, template_id=template_id)

        push = (should_push(level, push_watch=PUSH_WATCH) and self._tg_allowed(activity, level)) or force
        sent = False
        reason = "journal_only"
        if not force and self.money_mode and not self._tg_allowed(activity, level):
            reason = "money_filter"
            self.dedup.mark(dedupe_key)
            self._journal(activity, level, text, reason, enriched)
            self._bus(activity, level, reason)
            return RouteResult(False, level, template_id, text, activity, reason, enriched)
        if push and channel == "telegram":
            if not self.telegram_token or not self.telegram_chat_id:
                reason = "send_failed"
                logger.warning("Telegram token/chat_id missing — money alert journaled only")
            else:
                sent = self._send_telegram(text)
                reason = "sent" if sent else "send_failed"
        elif not push:
            reason = "level_no_push"

        if sent or reason in {"journal_only", "level_no_push"}:
            self.dedup.mark(dedupe_key)

        self._journal(activity, level, text, reason, enriched)
        self._bus(activity, level, reason)
        return RouteResult(sent, level, template_id, text, activity, reason, enriched)

    def _bus(self, activity: dict[str, Any], level: str, reason: str) -> None:
        if self.dry_run or level not in {"ACT", "CRITICAL", "WATCH"}:
            return
        try:
            from agents.hooks import on_activity

            on_activity(activity, level, reason=reason)
        except Exception:
            logger.debug("agents bus route skipped", exc_info=True)

    def _send_telegram(self, text: str) -> bool:
        from mute.telegram import send_telegram

        return send_telegram(
            self.telegram_token,
            self.telegram_chat_id,
            text,
            dry_run=self.dry_run,
        )

    def _journal(
        self,
        activity: dict[str, Any],
        level: str,
        text: str,
        reason: str,
        enriched: dict[str, Any] | None,
    ) -> None:
        row = {
            "ts": time.time(),
            "level": level,
            "reason": reason,
            "activity_type": activity.get("activity_type"),
            "source": activity.get("source"),
            "score": activity.get("score"),
            "symbol": activity.get("symbol"),
            "text_preview": (text or "")[:400],
            "enriched": enriched,
        }
        try:
            with JOURNAL_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            logger.debug("alert journal write failed", exc_info=True)

    def preview(self, activity: dict[str, Any]) -> str:
        level = resolve_level(activity)
        return self.engine.render(activity, level=level)
