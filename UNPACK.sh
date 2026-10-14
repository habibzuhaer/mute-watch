#!/usr/bin/env bash
# MUTE — розпаковка для Termix / Termux / Linux
# Usage:
#   tar -xzf MUTE-termix.tar.gz
#   ./UNPACK.sh
#   # або зсередини: cd MUTE && ./UNPACK.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

# Find project root (MUTE/)
if [[ -f "$HERE/START.sh" && -d "$HERE/scripts" ]]; then
  ROOT="$HERE"
elif [[ -d "$HERE/MUTE" && -f "$HERE/MUTE/START.sh" ]]; then
  ROOT="$HERE/MUTE"
else
  # maybe we are next to the .tar.gz — try extract first
  ARCHIVE=""
  for cand in \
    "$HERE/MUTE-termix.tar.gz" \
    "$HERE"/MUTE-termix-*.tar.gz \
    "$HOME/storage/downloads/MUTE-termix.tar.gz" \
    "$HOME/storage/downloads"/MUTE-termix-*.tar.gz \
    "$HOME/downloads/MUTE-termix.tar.gz" \
    "$HOME/MUTE-termix.tar.gz"
  do
    # glob may stay literal if no match
    for f in $cand; do
      if [[ -f "$f" ]]; then
        ARCHIVE="$f"
        break 2
      fi
    done
  done
  if [[ -n "${ARCHIVE}" ]]; then
    echo "=== Found archive: $ARCHIVE ==="
    tar -xzf "$ARCHIVE" -C "$HERE"
    if [[ -d "$HERE/MUTE" ]]; then
      ROOT="$HERE/MUTE"
    else
      echo "ERROR: archive did not contain MUTE/"
      exit 1
    fi
  else
    echo "ERROR: MUTE project not found next to this script."
    echo "  1) Copy MUTE-termix.tar.gz here"
    echo "  2) tar -xzf MUTE-termix.tar.gz"
    echo "  3) ./UNPACK.sh"
    exit 1
  fi
fi

cd "$ROOT"
echo "=== MUTE root: $ROOT ==="

# Termux extras
if [[ -n "${TERMUX_VERSION:-}" ]] || [[ "$(uname -o 2>/dev/null || true)" == "Android" ]]; then
  echo "Detected Termux/Android"
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Installing python…"
    pkg update -y
    pkg install -y python
  fi
  command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock || true
fi

chmod +x START.sh scripts/*.sh UNPACK.sh 2>/dev/null || true
mkdir -p logs data/graph data/prep out pump_prep/out

# Secrets
if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo
    echo "Created .env from .env.example"
    echo "EDIT before start:"
    echo "  nano .env"
    echo "  # TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / ETHERSCAN_API_KEY"
    echo
  else
    echo "WARN: no .env and no .env.example"
  fi
else
  echo "Found .env (secrets OK)"
  chmod 600 .env || true
fi

# Show guides
echo
echo "Guides:  ЗАПУСК.txt  |  MIGRATE.txt  |  README.md"
echo

# Optional: bootstrap venv + deps without full START (START needs filled .env)
if [[ ! -d .venv ]]; then
  echo "=== Creating .venv ==="
  if python3 -m venv .venv 2>/dev/null; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    pip install -q --upgrade pip
    pip install -q -r requirements.txt
    echo "venv ready"
  else
    echo "venv failed — START.sh will retry / use system python"
  fi
else
  echo ".venv already exists"
fi

echo
echo "=== Next steps ==="
echo "  cd $ROOT"
if ! grep -qE '^TELEGRAM_BOT_TOKEN=.+' .env 2>/dev/null; then
  echo "  1) nano .env   # fill Telegram + Etherscan keys"
fi
echo "  2) ./scripts/start_dashboard.sh"
echo "  3) ./scripts/start_prep.sh"
echo "  4) ./scripts/start_scanner.sh"
echo "  5) ./scripts/status.sh"
echo
echo "  Panel: http://127.0.0.1:8765/   (not file://)"
echo "  Or:    ./START.sh   (DWF + dashboard, needs filled .env)"
echo
echo "OK — unpack done."
