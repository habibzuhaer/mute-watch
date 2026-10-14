"""Rozvidka config — separate cycle from scanner/prep."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("ROZVIDKA_DATA_DIR", str(ROOT / "data" / "rozvidka")))
WIKI_DIR = DATA_DIR / "wiki"
STATE_FILE = DATA_DIR / "state.json"
TURNS_FILE = DATA_DIR / "turns.jsonl"
ACTIONS_FILE = DATA_DIR / "actions.jsonl"
OUT_HTML = ROOT / "out" / "rozvidka.html"
PID_FILE = ROOT / "rozvidka.pid"

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
# Prefer 14b for turn latency; override with ROZVIDKA_MODEL=deepseek-r1:32b
MODEL = os.getenv("ROZVIDKA_MODEL", "deepseek-r1:14b")
TURN_SLEEP_SEC = float(os.getenv("ROZVIDKA_TURN_SLEEP", "90"))
MAX_CTX_CHARS = int(os.getenv("ROZVIDKA_MAX_CTX", "8000"))
OLLAMA_TIMEOUT = float(os.getenv("ROZVIDKA_OLLAMA_TIMEOUT", "600"))
LANG = os.getenv("ROZVIDKA_LANG", "uk").strip().lower() or "uk"
# Loop default: do not hit Etherscan. Intel collects; розвідка reads families.
EXPAND_DEFAULT = os.getenv("ROZVIDKA_EXPAND", "0").strip() in {"1", "true", "yes"}
