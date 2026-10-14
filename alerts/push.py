"""Push helpers — wire detectors to ActivityRouter."""

from __future__ import annotations

import logging
from typing import Any

from alerts.config import ENABLED, MIN_SCORE_INTEL_PREPUMP, MIN_SCORE_INTEL_SPIKE, MIN_SCORE_ROZVIDKA, MONEY_MODE, MONEY_MIN_SCORE
from alerts.normalize import from_graph_signal, from_intel_prepump, from_intel_spike, from_rozvidka_finding
from alerts.router import ActivityRouter

logger = logging.getLogger(__name__)

_router: ActivityRouter | None = None


def reset_router() -> None:
    global _router
    _router = None


def get_router(**kwargs: Any) -> ActivityRouter:
    """Singleton router with Telegram creds from mute Settings / .env."""
    global _router
    if _router is None:
        if not kwargs.get("telegram_token"):
            try:
                from mute.config import load_settings

                s = load_settings()
                kwargs.setdefault("telegram_token", s.telegram_bot_token)
                kwargs.setdefault("telegram_chat_id", s.telegram_chat_id)
                kwargs.setdefault("dry_run", s.dry_run)
            except Exception:
                import os

                from dotenv import load_dotenv

                load_dotenv()
                kwargs.setdefault("telegram_token", os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
                kwargs.setdefault("telegram_chat_id", os.getenv("TELEGRAM_CHAT_ID", "").strip())
                kwargs.setdefault("dry_run", os.getenv("DRY_RUN", "0").strip() in {"1", "true", "yes"})
        _router = ActivityRouter(**kwargs)
    return _router


def push_intel_detection(det: dict[str, Any], *, router: ActivityRouter | None = None) -> int:
    if not ENABLED:
        return 0
    r = router or get_router()
    n = 0
    # Money mode: skip activity spikes (noise for trade); keep prepump only.
    if not MONEY_MODE:
        for row in (det.get("spikes") or [])[:8]:
            score = int(row.get("score") or 50)
            if score < MIN_SCORE_INTEL_SPIKE:
                continue
            if r.route(from_intel_spike(row)).sent:
                n += 1
    floor = max(MIN_SCORE_INTEL_PREPUMP, MONEY_MIN_SCORE) if MONEY_MODE else MIN_SCORE_INTEL_PREPUMP
    for row in (det.get("prepump") or [])[:12]:
        score = int(row.get("score") or 0)
        if score < floor:
            continue
        if r.route(from_intel_prepump(row)).sent:
            n += 1
    return n


def push_rozvidka_findings(findings: list[dict[str, Any]], *, router: ActivityRouter | None = None) -> int:
    if not ENABLED or MONEY_MODE:
        # Money mode: rozvidka stays in wiki/UI, not Telegram spam.
        return 0
    r = router or get_router()
    n = 0
    for f in findings[:10]:
        score = int(f.get("score") or 0)
        if score < MIN_SCORE_ROZVIDKA:
            continue
        if r.route(from_rozvidka_finding(f)).sent:
            n += 1
    return n


def push_graph_signal(sig: dict[str, Any], *, router: ActivityRouter | None = None) -> bool:
    """Push graph match if money-worthy (graph_act, score floor)."""
    if not ENABLED:
        return False
    r = router or get_router()
    activity = from_graph_signal(sig)
    if MONEY_MODE and activity.get("activity_type") != "graph_act":
        return False
    if MONEY_MODE and int(activity.get("score") or 0) < MONEY_MIN_SCORE:
        return False
    return bool(r.route(activity).sent)
