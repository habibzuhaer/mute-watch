#!/usr/bin/env bash
# Long collect with resume after kill/disconnect (default 12h).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/_common.sh" 2>/dev/null || true

HOURS="${INTEL_COLLECT_HOURS:-12}"
PID_FILE="${ROOT}/intel.pid"
LOG="${ROOT}/logs/intel_collect.log"
mkdir -p "${ROOT}/logs"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Intel collect already running pid=$(cat "$PID_FILE")"
  exit 0
fi
if pgrep -f '[Pp]ython.*-m intel collect' >/dev/null 2>&1; then
  echo "Intel collect already running (orphan process, no pid file)"
  exit 0
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
PY="${ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3

# Always resume queue + session window unless INTEL_FRESH=1
EXTRA=()
if [[ "${INTEL_FRESH:-0}" == "1" ]]; then
  EXTRA+=(--fresh)
fi

nohup "$PY" -m intel collect --hours "$HOURS" "${EXTRA[@]}" >>"$LOG" 2>&1 &
echo $! >"$PID_FILE"
echo "Intel collect started pid=$(cat "$PID_FILE") hours=$HOURS resume=${INTEL_FRESH:-0}"
echo "Log: $LOG"
echo "UI:  http://127.0.0.1:8765/intel.html"
