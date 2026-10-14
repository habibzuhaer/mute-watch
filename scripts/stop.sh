#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

stop_one() {
  local file="$1" label="$2"
  if [[ ! -f "$file" ]]; then
    echo "$label not running"
    return 0
  fi
  local pid
  pid="$(cat "$file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "Stopped $label pid=$pid"
  else
    echo "Stale $label pid file"
  fi
  rm -f "$file"
}

stop_one "$ROOT/mute.pid" "dwf"
# also stop prep if --all
if [[ "${1:-}" == "--all" ]]; then
  stop_one "$ROOT/mute_prep.pid" "prep"
  stop_one "$ROOT/scanner.pid" "scanner"
  stop_one "$ROOT/dashboard.pid" "dashboard"
fi
