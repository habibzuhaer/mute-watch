#!/usr/bin/env bash
# Swarm supervisor: restart dead workers, wake rozvidka on bus events.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs data/agents

PID_FILE="$ROOT/orch.pid"
LOG_FILE="$ROOT/logs/orch.out"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Orch already running pid=$(cat "$PID_FILE")"
  exit 0
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

nohup env PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" -m agents orch \
  >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
echo "Orch started pid=$(cat "$PID_FILE")"
echo "log: $LOG_FILE"
echo "status: PYTHONPATH=. .venv/bin/python -m agents status"
