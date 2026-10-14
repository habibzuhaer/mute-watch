#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/orch.pid"

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" || true
    echo "stopped orch pid=$pid"
  else
    echo "orch not running (stale pid file)"
  fi
  rm -f "$PID_FILE"
else
  echo "orch not running"
fi
