#!/usr/bin/env bash
# Resumable continuous graph scanner (survives restart via data/graph/)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs data/graph

PID_FILE="$ROOT/scanner.pid"
LOG_FILE="$ROOT/logs/scanner.out"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Scanner already running pid=$(cat "$PID_FILE")"
  exit 0
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

nohup env PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" -m pump_prep continuous \
  >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
echo "Continuous scanner started pid=$(cat "$PID_FILE")"
echo "state: $ROOT/data/graph/  logs: $LOG_FILE"
echo "HTML:  $ROOT/pump_prep/out/graph_live.html (обновляется по ходу)"
