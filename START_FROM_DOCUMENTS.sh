#!/usr/bin/env bash
# MUTE — запуск з папки Documents (Termix / Termux / Linux)
#
# Поклади в Documents:
#   MUTE-termix.tar.gz   (або вже розпаковану MUTE/)
#   START_FROM_DOCUMENTS.sh  (цей файл — є в архіві)
#
# Потім:
#   cd ~/Documents          # або ~/storage/shared/Documents
#   bash START_FROM_DOCUMENTS.sh
#
set -euo pipefail

find_documents() {
  local c
  for c in \
    "$HOME/Documents" \
    "$HOME/storage/shared/Documents" \
    "$HOME/storage/documents" \
    "$HOME/storage/shared/documents" \
    "/sdcard/Documents" \
    "/storage/emulated/0/Documents"
  do
    if [[ -d "$c" ]]; then
      echo "$c"
      return 0
    fi
  done
  # fallback: folder where this script lives
  echo "$(cd "$(dirname "$0")" && pwd)"
}

DOC="$(find_documents)"
cd "$DOC"
echo "=== Documents: $DOC ==="

# Prefer already unpacked MUTE/
ROOT=""
if [[ -f "$DOC/MUTE/START.sh" ]]; then
  ROOT="$DOC/MUTE"
elif [[ -f "$DOC/START.sh" && -d "$DOC/scripts" ]]; then
  ROOT="$DOC"
fi

# Else unpack archive from Documents
if [[ -z "$ROOT" ]]; then
  ARCHIVE=""
  for f in \
    "$DOC/MUTE-termix.tar.gz" \
    "$DOC"/MUTE-termix-*.tar.gz \
    "$DOC/MUTE-migrate-"*.tar.gz
  do
    for g in $f; do
      if [[ -f "$g" ]]; then
        ARCHIVE="$g"
        break 2
      fi
    done
  done
  if [[ -z "$ARCHIVE" ]]; then
    echo "ERROR: у Documents немає MUTE/ і немає MUTE-termix.tar.gz"
    echo "  Скопіюй архів у: $DOC"
    echo "  Потім знову: bash START_FROM_DOCUMENTS.sh"
    exit 1
  fi
  echo "=== Розпаковка: $ARCHIVE ==="
  tar -xzf "$ARCHIVE" -C "$DOC"
  if [[ -f "$DOC/MUTE/START.sh" ]]; then
    ROOT="$DOC/MUTE"
  elif [[ -f "$DOC/START.sh" ]]; then
    ROOT="$DOC"
  else
    echo "ERROR: після tar немає MUTE/"
    exit 1
  fi
  # copy launcher next to MUTE for next runs
  if [[ -f "$DOC/UNPACK.sh" ]]; then
    chmod +x "$DOC/UNPACK.sh" 2>/dev/null || true
  fi
fi

cd "$ROOT"
echo "=== MUTE: $ROOT ==="
chmod +x START.sh scripts/*.sh UNPACK.sh START_FROM_DOCUMENTS.sh 2>/dev/null || true

# Unpack helpers (venv, .env template)
if [[ -x ./UNPACK.sh ]]; then
  ./UNPACK.sh || true
fi

if [[ ! -f .env ]]; then
  echo "ERROR: немає .env — скопіюй з .env.example і заповни ключі:"
  echo "  cp .env.example .env && nano .env"
  exit 1
fi
if ! grep -qE '^TELEGRAM_BOT_TOKEN=.+' .env 2>/dev/null; then
  echo "WARN: TELEGRAM_BOT_TOKEN порожній у .env — Telegram не працюватиме"
fi
if ! grep -qE '^ETHERSCAN_API_KEY=.+' .env 2>/dev/null; then
  echo "WARN: ETHERSCAN_API_KEY порожній — EVM-скан/монітор обмежені"
fi

echo "=== Старт dashboard + prep + scanner ==="
./scripts/start_dashboard.sh
./scripts/start_prep.sh
./scripts/start_scanner.sh
./scripts/status.sh || true

echo
echo "OK"
echo "  Панель: http://127.0.0.1:8765/"
echo "  Launch: http://127.0.0.1:8765/launch.html"
echo "  Стоп:   cd $ROOT && ./scripts/stop_scanner.sh && ./scripts/stop_dashboard.sh && kill \$(cat mute_prep.pid) 2>/dev/null"
