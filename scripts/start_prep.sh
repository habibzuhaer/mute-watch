#!/usr/bin/env bash
# MUTE pump-prep mode: watchlist seeds, obscure token IN + CEX deposit OUT
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export ADDRESSES_FILE="${ADDRESSES_FILE:-$ROOT/addresses/pump_prep_watchlist.json}"
export ALERT_MODE="${ALERT_MODE:-prep}"
export CHAIN_PROFILE="${CHAIN_PROFILE:-core}"
export ALERT_NATIVE="${ALERT_NATIVE:-0}"
export DATA_DIR="${DATA_DIR:-$ROOT/data/prep}"
export LOG_DIR="${LOG_DIR:-$ROOT/logs}"

mkdir -p "$DATA_DIR" "$LOG_DIR" logs data

if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Missing .env — copy .env.example and fill keys"
  exit 1
fi

PID_FILE="$ROOT/mute_prep.pid"
LOG_FILE="$ROOT/logs/mute_prep.out"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "MUTE prep already running pid=$(cat "$PID_FILE")"
  exit 0
fi

nohup env \
  ADDRESSES_FILE="$ADDRESSES_FILE" \
  ALERT_MODE="$ALERT_MODE" \
  CHAIN_PROFILE="$CHAIN_PROFILE" \
  ALERT_NATIVE="$ALERT_NATIVE" \
  DATA_DIR="$DATA_DIR" \
  LOG_DIR="$LOG_DIR" \
  "$ROOT/.venv/bin/python" -m mute run >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
echo "MUTE prep started pid=$(cat "$PID_FILE")"
echo "addresses: $ADDRESSES_FILE"
echo "alert_mode: $ALERT_MODE"
echo "logs: $LOG_FILE"
echo "stop: kill \$(cat mute_prep.pid)"
