#!/usr/bin/env bash
# Termix-friendly launcher: runs in background, survives SSH disconnect.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p logs data
PID_FILE="$ROOT/mute.pid"
LOG_FILE="$ROOT/logs/mute.out"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "MUTE already running pid=$(cat "$PID_FILE")"
  exit 0
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
fi

# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Missing .env — copy .env.example and fill keys"
  exit 1
fi

nohup "$ROOT/.venv/bin/python" -m mute run >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
echo "MUTE started pid=$(cat "$PID_FILE")"
echo "logs: $LOG_FILE"
echo "status: ./scripts/status.sh"
