#!/usr/bin/env bash
# Unpack → run once. Works on Termux (Android) and Linux/Termix SSH.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "=== MUTE bootstrap ==="
mkdir -p logs data
chmod +x scripts/*.sh 2>/dev/null || true

# --- Termux: install python if missing ---
if [[ -n "${TERMUX_VERSION:-}" ]] || [[ "$(uname -o 2>/dev/null || true)" == "Android" ]]; then
  echo "Detected Termux/Android"
  export PARALLEL_WORKERS="${PARALLEL_WORKERS:-3}"
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Installing python…"
    pkg update -y
    pkg install -y python
  fi
  # Keep CPU awake while monitor runs (optional; ignore if unavailable)
  command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock || true
fi

if [[ ! -f "$ROOT/.env" ]]; then
  if [[ -f "$ROOT/.env.example" ]]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "Created .env from .env.example — fill TELEGRAM_* and ETHERSCAN_API_KEY, then re-run ./START.sh"
    exit 1
  fi
  echo "Missing .env"
  exit 1
fi

if ! grep -qE '^TELEGRAM_BOT_TOKEN=.+' "$ROOT/.env"; then
  echo "Set TELEGRAM_BOT_TOKEN in .env"
  exit 1
fi
if ! grep -qE '^TELEGRAM_CHAT_ID=.+' "$ROOT/.env"; then
  echo "Set TELEGRAM_CHAT_ID in .env"
  exit 1
fi

PYTHON=python3
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "python3 not found. Install: pkg install python   (Termux)  or  python3-venv (Linux)"
  exit 1
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "Creating venv…"
  if ! "$PYTHON" -m venv "$ROOT/.venv" 2>/dev/null; then
    # Some Termux builds: use --without-pip then get-pip, or plain pip --user
    echo "venv failed — installing deps into user/site"
    pip3 install -q --upgrade pip || "$PYTHON" -m pip install -q --upgrade pip
    pip3 install -q -r "$ROOT/requirements.txt" || "$PYTHON" -m pip install -q -r "$ROOT/requirements.txt"
    PYRUN="$PYTHON"
  else
    # shellcheck disable=SC1091
    source "$ROOT/.venv/bin/activate"
    pip install -q --upgrade pip
    pip install -q -r "$ROOT/requirements.txt"
    PYRUN="$ROOT/.venv/bin/python"
  fi
else
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  pip install -q -r "$ROOT/requirements.txt"
  PYRUN="$ROOT/.venv/bin/python"
fi

# If venv exists use it; else system python
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYRUN="$ROOT/.venv/bin/python"
else
  PYRUN="$PYTHON"
fi

echo "Telegram test…"
if ! "$PYRUN" -m mute test-telegram; then
  echo "Telegram test failed — check token/chat_id and network"
  exit 1
fi

echo "Resource estimate:"
"$PYRUN" -m mute estimate

# Prefer scripts/start.sh when venv exists; else nohup directly
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  ./scripts/start.sh
else
  PID_FILE="$ROOT/mute.pid"
  LOG_FILE="$ROOT/logs/mute.out"
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "MUTE already running pid=$(cat "$PID_FILE")"
  else
    nohup "$PYRUN" -m mute run >>"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
    echo "MUTE started pid=$(cat "$PID_FILE")"
  fi
fi

./scripts/status.sh 2>/dev/null || true
echo
echo "Done. Alerts → Telegram."
echo "  ./scripts/status.sh"
echo "  ./scripts/stop.sh"
echo "  ./scripts/start.sh"
echo
echo "HTML control panel:"
echo "  ./scripts/start_dashboard.sh"
echo "  → http://127.0.0.1:8765/"
# Auto-start dashboard if not running
if [[ "${START_DASHBOARD:-1}" == "1" ]]; then
  ./scripts/start_dashboard.sh || true
fi
