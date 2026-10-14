"""LocalBrain — Ollama deepseek enrichment for alerts (optional)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from alerts.config import LOCAL_BRAIN_MODEL, OLLAMA_HOST, OLLAMA_TIMEOUT

logger = logging.getLogger(__name__)

SYSTEM_EN = """You are MUTE LocalBrain — alert analyst for crypto pump-prep monitoring.
Input: JSON activity (source, type, score, symbol, reasons).
Output ONLY valid JSON (no markdown):
{{"summary":"one line","action_hint":"concrete next step","urgency":"low|medium|high|critical","noise":false,"level_override":null}}
Rules:
- noise=true only for obvious spam/scam airdrops with no MM link
- action_hint must be actionable (open hub, intel queue, watch wallet)
- match operator language: en
- never invent addresses
"""

SYSTEM_UK = """Ти — MUTE LocalBrain — аналітик алертів для pump-prep моніторингу.
Вхід: JSON активності (source, type, score, symbol, reasons).
Вихід ТІЛЬКИ валідний JSON (без markdown):
{{"summary":"одним реченням","action_hint":"конкретний крок","urgency":"low|medium|high|critical","noise":false,"level_override":null}}
Правила:
- noise=true лише для явного spam/scam airdrop без MM звʼязку
- action_hint — дія (hub, intel queue, watch)
- мова оператора: uk
- не вигадуй адреси
"""


class LocalBrain:
    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        self.model = model or LOCAL_BRAIN_MODEL
        self.host = (host or OLLAMA_HOST).rstrip("/")

    def ping(self) -> dict[str, Any]:
        try:
            import urllib.request

            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as resp:  # noqa: S310
                ok = resp.status == 200
            return {"ok": ok, "host": self.host, "model": self.model}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def build_prompt(self, activity: dict[str, Any], *, lang: str, level: str) -> str:
        payload = {
            "level": level,
            "activity": {
                k: activity.get(k)
                for k in (
                    "source",
                    "activity_type",
                    "score",
                    "tier",
                    "symbol",
                    "chain",
                    "signal_kind",
                    "finding_type",
                    "reasons",
                    "reasons_uk",
                    "match_entity",
                    "wallet_label",
                )
            },
        }
        lang = "uk" if lang in {"uk", "ua"} else "en"
        sys_t = SYSTEM_UK if lang == "uk" else SYSTEM_EN
        user = json.dumps(payload, ensure_ascii=False)
        return sys_t + "\n\nACTIVITY:\n" + user

    def activity_enrich(self, activity: dict[str, Any], *, lang: str, level: str) -> dict[str, Any]:
        prompt = self.build_prompt(activity, lang=lang, level=level)
        raw = self._chat(prompt)
        parsed = self._parse_json(raw)
        if not parsed:
            return {"summary": "", "action_hint": "", "urgency": "medium", "noise": False}
        return parsed

    def _chat(self, prompt: str) -> str:
        from agents.inference import ask, strip_think

        raw = ask(
            [{"role": "user", "content": prompt}],
            model=self.model,
            temperature=0.25,
            num_predict=256,
            timeout=OLLAMA_TIMEOUT,
            src="alerts",
        )
        return strip_think(raw)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    return None
        return None
