"""Alert system config — thresholds, lang, LocalBrain, paths."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DATA_DIR = Path(os.getenv("ALERTS_DATA_DIR", str(ROOT / "data" / "alerts")))
JOURNAL_FILE = DATA_DIR / "alerts.jsonl"
DEDUP_FILE = DATA_DIR / "dedup.json"

LANG = os.getenv("ALERTS_LANG", os.getenv("MUTE_LANG", os.getenv("MUTE_UI_LANG", "uk"))).strip().lower()
if LANG in {"ua", "ukr"}:
    LANG = "uk"
if LANG not in {"uk", "en"}:
    LANG = "uk"

ENABLED = os.getenv("ALERTS_ENABLED", "1").strip() not in {"0", "false", "no"}
USE_LOCAL_BRAIN = os.getenv("ALERTS_USE_LOCAL_BRAIN", "0").strip() in {"1", "true", "yes"}
LOCAL_BRAIN_MODEL = os.getenv("ALERTS_MODEL", "deepseek-r1:14b-alert")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_TIMEOUT = float(os.getenv("ALERTS_OLLAMA_TIMEOUT", "45"))

# Per-source minimum scores for auto-push (see levels.py for level mapping)
MIN_SCORE_PREP = int(os.getenv("ALERTS_MIN_SCORE_PREP", os.getenv("SIGNAL_MIN_SCORE", "55")))
MIN_SCORE_GRAPH = int(os.getenv("ALERTS_MIN_SCORE_GRAPH", "55"))
MIN_SCORE_INTEL_SPIKE = int(os.getenv("ALERTS_MIN_SCORE_INTEL_SPIKE", "50"))
MIN_SCORE_INTEL_PREPUMP = int(os.getenv("ALERTS_MIN_SCORE_INTEL_PREPUMP", "36"))
MIN_SCORE_ROZVIDKA = int(os.getenv("ALERTS_MIN_SCORE_ROZVIDKA", "55"))

DEDUP_TTL_SEC = int(os.getenv("ALERTS_DEDUP_TTL_SEC", str(6 * 3600)))
# Money mode: Telegram only for setups that help trade; rest stays journal-only.
MONEY_MODE = os.getenv("ALERTS_MONEY_MODE", "1").strip() not in {"0", "false", "no"}
# In money mode default: do NOT push WATCH (only ACT/CRITICAL).
_PUSH_WATCH_DEFAULT = "0" if MONEY_MODE else "1"
PUSH_WATCH = os.getenv("ALERTS_PUSH_WATCH", _PUSH_WATCH_DEFAULT).strip() not in {"0", "false", "no"}
DRY_RUN = os.getenv("DRY_RUN", "0").strip() in {"1", "true", "yes"}

# Types allowed to Telegram when MONEY_MODE=1 (comma-separated override)
_MONEY_DEFAULT = "prep_live,prep_new_token_in,prep_cex_deposit,intel_prepump,graph_act"
MONEY_TYPES = {
    x.strip()
    for x in os.getenv("ALERTS_MONEY_TYPES", _MONEY_DEFAULT).split(",")
    if x.strip()
}
# Hard floor for money Telegram (ACT-class)
MONEY_MIN_SCORE = int(os.getenv("ALERTS_MONEY_MIN_SCORE", "60"))
