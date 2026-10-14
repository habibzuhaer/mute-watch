"""Template engine — load JSON templates (uk/en) and render Telegram HTML."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from alerts.config import LANG, TEMPLATES_DIR
from alerts.levels import LEVELS, action_text
from alerts.normalize import short_addr

logger = logging.getLogger(__name__)

LABELS = {
    "en": {
        "why": "why",
        "action": "ACTION",
        "tier_act": "ACT",
        "tier_watch": "WATCH",
        "tier_noise": "noise",
        "from": "from",
        "to_cex": "→",
    },
    "uk": {
        "why": "чому",
        "action": "ДІЯ",
        "tier_act": "ДІЯ",
        "tier_watch": "СТЕЖИТИ",
        "tier_noise": "шум",
        "from": "від",
        "to_cex": "→",
    },
}


class TemplateEngine:
    def __init__(self, templates_dir: Path | None = None, lang: str | None = None) -> None:
        self.templates_dir = templates_dir or TEMPLATES_DIR
        self.lang = lang or LANG
        if self.lang not in {"uk", "en"}:
            self.lang = "uk"
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict[str, Any]:
        path = self.templates_dir / "manifest.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @lru_cache(maxsize=64)
    def _load_template(self, lang: str, template_id: str) -> dict[str, Any]:
        path = self.templates_dir / lang / f"{template_id}.json"
        if not path.exists():
            path = self.templates_dir / "en" / f"{template_id}.json"
        if not path.exists():
            raise FileNotFoundError(template_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def pick_template_id(self, activity: dict[str, Any], level: str) -> str:
        atype = activity.get("activity_type") or activity.get("type") or "generic"
        by_type = self.manifest.get("by_activity_type") or {}
        mapping = by_type.get(atype) or by_type.get(str(atype))
        if isinstance(mapping, dict):
            tid = mapping.get(level) or mapping.get("default")
            if tid:
                return tid
        defaults = self.manifest.get("defaults") or {}
        return defaults.get(level) or defaults.get("default") or "generic_info"

    def render(self, activity: dict[str, Any], *, level: str, template_id: str | None = None) -> str:
        tid = template_id or self.pick_template_id(activity, level)
        try:
            tpl = self._load_template(self.lang, tid)
        except FileNotFoundError:
            tpl = self._load_template("en", "generic_info")

        ctx = self._build_context(activity, level=level, template_id=tid)
        lines: list[str] = []
        title = tpl.get("title", "{emoji} {level} · {symbol}")
        lines.append(self._fmt(title, ctx))
        for line in tpl.get("body_lines") or []:
            if line == "":
                lines.append("")
                continue
            rendered = self._fmt(line, ctx)
            if rendered.strip():
                lines.append(rendered)
        action_line = tpl.get("action_line")
        if action_line:
            lines.append(self._fmt(action_line, ctx))
        else:
            act = ctx.get("action_text")
            if act:
                lines.append(f"<b>→ {ctx['action_label']}</b> {act}")
        return "\n".join(lines)

    def _build_context(self, activity: dict[str, Any], *, level: str, template_id: str) -> dict[str, Any]:
        lang = self.lang
        labels = LABELS.get(lang, LABELS["en"])
        lv = LEVELS.get(level, LEVELS["INFO"])
        tier = (activity.get("tier") or "").lower()
        if tier == "actionable":
            tier_label = labels["tier_act"]
        elif tier == "watch":
            tier_label = labels["tier_watch"]
        else:
            tier_label = labels.get("tier_noise", tier or level)

        reasons = activity.get("reasons_uk") if lang == "uk" else activity.get("reasons")
        if not reasons:
            reasons = activity.get("reasons") or []
        reasons_block = "\n".join(f"· {r}" for r in reasons[:8]) if reasons else "· —"

        symbol = activity.get("symbol") or activity.get("token_list") or activity.get("title") or "?"
        direction_line = ""
        if activity.get("activity_type") == "prep_cex_deposit" and activity.get("cex"):
            direction_line = f"{labels['to_cex']} <b>{activity['cex']}</b> <code>{activity.get('to_address_short', '?')}</code>"
        elif activity.get("from_address_short"):
            direction_line = f"{labels['from']} <code>{activity['from_address_short']}</code>"

        explorer = activity.get("explorer_tx")
        explorer_link = f'<a href="{explorer}">tx</a>' if explorer else ""

        ctx: dict[str, Any] = {
            **activity,
            "level": level,
            "emoji": lv.emoji,
            "tier_label": tier_label,
            "score": activity.get("score", "?"),
            "symbol": symbol,
            "address_short": activity.get("address_short") or short_addr(activity.get("address") or ""),
            "why_label": labels["why"],
            "action_label": labels["action"],
            "reasons_block": reasons_block,
            "direction_line": direction_line,
            "action_text": action_text(activity, level, lang),
            "explorer_link": explorer_link,
            "wallet_label": activity.get("wallet_label") or activity.get("match_entity") or "",
            "signal_kind": activity.get("signal_kind") or activity.get("finding_type") or "",
            "finding_type": activity.get("finding_type") or activity.get("type") or "",
            "process": activity.get("process") or "",
            "detail": activity.get("detail") or "",
            "title_line": activity.get("title") or symbol,
        }
        return ctx

    @staticmethod
    def _fmt(template: str, ctx: dict[str, Any]) -> str:
        class Safe(dict):
            def __missing__(self, key: str) -> str:
                v = ctx.get(key)
                return "" if v is None else str(v)

        try:
            return template.format_map(Safe(ctx))
        except Exception as exc:
            logger.debug("template fmt: %s", exc)
            return template
