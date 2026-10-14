"""Shared paths and env for the MUTE swarm supervisor."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

DATA_DIR = Path(os.getenv("AGENTS_DATA_DIR", str(ROOT / "data" / "agents")))
BUS_FILE = DATA_DIR / "bus.jsonl"
REPORTS_FILE = DATA_DIR / "reports.jsonl"
VOICES_FILE = DATA_DIR / "voices.jsonl"
BOARD_FILE = DATA_DIR / "board.jsonl"
KANBAN_FILE = DATA_DIR / "kanban.json"
HANDS_FILE = DATA_DIR / "hands.json"
STATE_FILE = DATA_DIR / "state.json"
NUDGE_FILE = DATA_DIR / "nudge_speak.json"
TOKENS_FILE = DATA_DIR / "tokens.json"
PID_FILE = ROOT / "orch.pid"

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
MODEL = os.getenv("ROZVIDKA_MODEL", "deepseek-r1:14b")
OLLAMA_TIMEOUT = float(os.getenv("AGENTS_OLLAMA_TIMEOUT", os.getenv("ROZVIDKA_OLLAMA_TIMEOUT", "600")))
NUDGE_COOLDOWN_SEC = float(os.getenv("AGENTS_NUDGE_COOLDOWN", "20"))
NET_FAILS_BEFORE_RESTART = int(os.getenv("AGENTS_NET_FAILS", "3"))
STALE_SEC = float(os.getenv("AGENTS_STALE_SEC", "180"))
POLL_SEC = float(os.getenv("AGENTS_POLL_SEC", "1"))
VOICE_MIN_SCORE = int(os.getenv("AGENTS_VOICE_MIN_SCORE", "40"))
BACKOFF_START_SEC = float(os.getenv("AGENTS_BACKOFF_START", "5"))
BACKOFF_CAP_SEC = float(os.getenv("AGENTS_BACKOFF_CAP", "300"))
LANG = os.getenv("MUTE_LANG", os.getenv("ROZVIDKA_LANG", "uk")).strip().lower() or "uk"
