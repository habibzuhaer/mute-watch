#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/dashboard.pid"
WATCH_PID_FILE="$ROOT/dashboard_watch.pid"

stop_one() {
  local file="$1" name="$2"
  if [[ ! -f "$file" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    echo "Stopped $name pid=$pid"
  else
    echo "Stale $name pid file"
  fi
  rm -f "$file"
}

stop_one "$WATCH_PID_FILE" "dashboard-watchdog"
stop_one "$PID_FILE" "dashboard"
