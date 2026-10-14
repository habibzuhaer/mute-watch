#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/scanner.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "Scanner not running"
  exit 0
fi
PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "Stopped scanner pid=$PID (progress kept in data/graph/)"
else
  echo "Stale scanner pid file"
fi
rm -f "$PID_FILE"
