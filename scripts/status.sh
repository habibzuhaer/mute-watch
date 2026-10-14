#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/_common.sh"

PORT="${MUTE_DASH_PORT:-8765}"

_check() {
  local name="$1" file="$2"
  if mute_pid_alive "$file"; then
    echo "$name  running  pid=$(cat "$file")"
  else
    echo "$name  stopped"
  fi
}

echo "=== MUTE status ==="
_check "dwf      " "$ROOT/mute.pid"
_check "prep     " "$ROOT/mute_prep.pid"
_check "scanner  " "$ROOT/scanner.pid"
_check "intel    " "$ROOT/intel.pid"
_check "rozvidka " "$ROOT/rozvidka.pid"
_check "orch     " "$ROOT/orch.pid"

# Dashboard: require LISTEN+HTTP ping
if mute_pid_alive "$ROOT/dashboard.pid" && mute_port_listening "$PORT" && mute_http_ok "http://127.0.0.1:${PORT}/api/ping"; then
  echo "dashboard  healthy  pid=$(cat "$ROOT/dashboard.pid")  :${PORT}"
elif mute_pid_alive "$ROOT/dashboard.pid"; then
  echo "dashboard  ZOMBIE   pid=$(cat "$ROOT/dashboard.pid")  (no answer on :${PORT}) → ./scripts/start_dashboard.sh"
else
  echo "dashboard  stopped"
fi

if [[ -d "$ROOT/.venv" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  "$ROOT/.venv/bin/python" - <<'PY' 2>/dev/null || true
from pump_prep import graph_store as gs
p = gs.progress_snapshot()
print(f"scan       {p.get('pct')}%  {p.get('done')}/{p.get('total')}  last={p.get('last_token')}")
t = p.get('signals_by_tier') or {}
print(f"signals    act={t.get('actionable',0)} watch={t.get('watch',0)} noise={t.get('noise',0)}")
PY
  "$ROOT/.venv/bin/python" -m mute estimate 2>/dev/null || true
fi

echo
echo "=== last DWF log ==="
tail -n 8 "$ROOT/logs/mute.out" 2>/dev/null || echo "(no mute.out)"
echo
echo "=== last prep log ==="
tail -n 6 "$ROOT/logs/mute_prep.out" 2>/dev/null || echo "(no mute_prep.out)"
echo
echo "=== last scanner log ==="
tail -n 6 "$ROOT/logs/scanner.out" 2>/dev/null || echo "(no scanner.out)"
echo
echo "Dashboard: http://127.0.0.1:${PORT}/"
echo "Hub:       http://127.0.0.1:${PORT}/reports/signals_hub.html"
