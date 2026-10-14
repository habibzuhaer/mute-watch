#!/usr/bin/env bash
# Start MUTE control dashboard (HTML + API) on http://127.0.0.1:8765/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/scripts/_common.sh"
mkdir -p logs out

PID_FILE="$ROOT/dashboard.pid"
LOG_FILE="$ROOT/logs/dashboard.out"
PORT="${MUTE_DASH_PORT:-8765}"
URL="http://127.0.0.1:${PORT}/"
PING="http://127.0.0.1:${PORT}/api/ping"

# Healthy = pid alive AND port listening AND HTTP ping
if mute_pid_alive "$PID_FILE" && mute_port_listening "$PORT" && mute_http_ok "$PING"; then
  echo "Dashboard healthy pid=$(cat "$PID_FILE")"
  echo "Open: $URL"
  exit 0
fi

# Stale / zombie: pid exists but no listen → kill and restart
if mute_pid_alive "$PID_FILE"; then
  echo "Dashboard pid alive but port ${PORT} not healthy — restarting"
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  sleep 0.4
  rm -f "$PID_FILE"
elif [[ -f "$PID_FILE" ]]; then
  echo "Stale dashboard.pid — removing"
  rm -f "$PID_FILE"
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

nohup "$ROOT/.venv/bin/python" "$ROOT/scripts/control_server.py" >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

ok=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  sleep 0.35
  if mute_port_listening "$PORT" && mute_http_ok "$PING"; then
    ok=1
    break
  fi
done

if [[ "$ok" -ne 1 ]]; then
  echo "FAIL: dashboard started pid=$(cat "$PID_FILE") but ${PING} not answering"
  echo "See $LOG_FILE"
  exit 1
fi

echo "Dashboard started pid=$(cat "$PID_FILE")"
echo "Open: $URL"
xdg-open "$URL" >/dev/null 2>&1 || true

# Background watchdog (skip if nested restart from watchdog itself)
if [[ "${MUTE_NO_WATCHDOG:-0}" != "1" ]]; then
  WATCH_PID_FILE="$ROOT/dashboard_watch.pid"
  if ! mute_pid_alive "$WATCH_PID_FILE"; then
    nohup bash -c "
      while true; do
        sleep 20
        if ! curl -s -m 2 -o /dev/null 'http://127.0.0.1:${PORT}/api/ping'; then
          echo \"[\$(date -Iseconds)] watchdog: ping failed — restart\" >>'$LOG_FILE'
          kill \$(cat '$PID_FILE' 2>/dev/null) 2>/dev/null || true
          rm -f '$PID_FILE'
          cd '$ROOT' && MUTE_NO_WATCHDOG=1 ./scripts/start_dashboard.sh >/dev/null 2>&1 || true
        fi
      done
    " >>"$LOG_FILE" 2>&1 &
    echo $! >"$WATCH_PID_FILE"
    echo "Watchdog pid=$(cat "$WATCH_PID_FILE")"
  fi
fi
