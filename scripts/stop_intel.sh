#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="${ROOT}/intel.pid"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
PY="${ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3

if [[ -f "$PID_FILE" ]]; then
  pid=$(cat "$PID_FILE")
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" || true
    sleep 1
    kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" || true
    echo "Stopped intel pid=$pid"
  fi
  rm -f "$PID_FILE"
else
  echo "No intel.pid"
fi
# Reap orphans (pid file can lag behind a second collect process)
if pgrep -f '[Pp]ython.*-m intel collect' >/dev/null 2>&1; then
  pkill -TERM -f '[Pp]ython.*-m intel collect' || true
  sleep 1
  pkill -KILL -f '[Pp]ython.*-m intel collect' 2>/dev/null || true
  echo "reaped extra intel collect processes"
fi
# Mark interrupted so next start resumes
"$PY" -c "from intel.cycles import mark_interrupted; mark_interrupted(); print('checkpoint: interrupted')" 2>/dev/null || true
