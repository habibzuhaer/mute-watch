#!/usr/bin/env bash
# Розвідка autonomous cycle (DeepSeek via Ollama)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs data/rozvidka

PID_FILE="$ROOT/rozvidka.pid"
LOG_FILE="$ROOT/logs/rozvidka.out"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Rozvidka already running pid=$(cat "$PID_FILE")"
  exit 0
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

# Default model if unset
export ROZVIDKA_MODEL="${ROZVIDKA_MODEL:-deepseek-r1:14b}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"

nohup env PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" -m rozvidka loop --no-expand \
  >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
echo "Розвідка started pid=$(cat "$PID_FILE") model=$ROZVIDKA_MODEL"
echo "UI:  http://127.0.0.1:8765/rozvidka.html"
echo "log: $LOG_FILE"
