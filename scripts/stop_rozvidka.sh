#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/rozvidka.pid"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
PY="${ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" || true)"
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" || true
    sleep 1
    kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" || true
    echo "stopped rozvidka pid=$pid"
  else
    echo "rozvidka not running (stale pid file)"
  fi
  rm -f "$PID_FILE"
else
  echo "rozvidka not running"
fi
"$PY" -c "
from rozvidka.runtime import load_state, save_state
from datetime import datetime
st = load_state()
st['loop_interrupted'] = True
st['loop_stopped_at'] = datetime.now().astimezone().isoformat()
st['heartbeat_at'] = st['loop_stopped_at']
save_state(st)
print('checkpoint: rozvidka interrupted, turn=', st.get('turn'))
" 2>/dev/null || true
