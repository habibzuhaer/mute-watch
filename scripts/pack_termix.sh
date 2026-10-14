#!/usr/bin/env bash
# Pack MUTE for Termix / Termux / another Linux box.
# Usage:
#   ./scripts/pack_termix.sh                 # without .env
#   ./scripts/pack_termix.sh --with-secrets  # includes .env (private only)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

WITH_SECRETS=0
for a in "$@"; do
  case "$a" in
    --with-secrets|-s) WITH_SECRETS=1 ;;
    -h|--help)
      echo "Usage: $0 [--with-secrets]"
      echo "  Builds dist/MUTE-termix-YYYYMMDD-HHMM.tar.gz + UNPACK.sh inside"
      exit 0
      ;;
  esac
done

STAMP="$(date +%Y%m%d-%H%M)"
OUT_DIR="$ROOT/dist"
NAME="MUTE-termix-${STAMP}"
STAGE="$OUT_DIR/_stage_${NAME}"
ARCHIVE="$OUT_DIR/${NAME}.tar.gz"
# Stable alias for Termux docs
ALIAS="$OUT_DIR/MUTE-termix.tar.gz"

mkdir -p "$OUT_DIR"
rm -rf "$STAGE"
mkdir -p "$STAGE/MUTE"

echo "=== Panel / hub snapshot (best effort) ==="
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" -m pump_prep panel >/dev/null 2>&1 || true
  PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" -c \
    "from pump_prep.hub import write_hub_html; write_hub_html()" >/dev/null 2>&1 || true
  PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" -c \
    "from pump_prep.i18n_ui import write_static_packs; write_static_packs()" >/dev/null 2>&1 || true
fi

echo "=== Copying tree ==="
if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude '.venv/' \
    --exclude 'crypto_funds_tracker/.venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.git/' \
    --exclude 'logs/' \
    --exclude '*.pid' \
    --exclude 'dist/' \
    --exclude '.env' \
    --exclude '*.egg-info/' \
    --exclude '.pytest_cache/' \
    --exclude '.mypy_cache/' \
    --exclude 'MUTE-termix.tar.gz' \
    --exclude 'MUTE-termix-*.tar.gz' \
    "$ROOT/" "$STAGE/MUTE/"
else
  tar -C "$ROOT" \
    --exclude='.venv' \
    --exclude='crypto_funds_tracker/.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='logs' \
    --exclude='*.pid' \
    --exclude='dist' \
    --exclude='.env' \
    -cf - . | tar -C "$STAGE/MUTE" -xf -
fi

mkdir -p \
  "$STAGE/MUTE/data/graph" \
  "$STAGE/MUTE/data/prep" \
  "$STAGE/MUTE/out" \
  "$STAGE/MUTE/pump_prep/out" \
  "$STAGE/MUTE/addresses" \
  "$STAGE/MUTE/logs" \
  "$STAGE/MUTE/crypto_funds_tracker/out"

# Launch guides + migrate notes
for f in ЗАПУСК.txt MIGRATE.txt UNPACK.txt README.md .env.example; do
  [[ -f "$ROOT/$f" ]] && cp -f "$ROOT/$f" "$STAGE/MUTE/$f"
done

# Unpack + Documents launcher at archive root AND inside MUTE/
for s in UNPACK.sh START_FROM_DOCUMENTS.sh; do
  if [[ -f "$ROOT/$s" ]]; then
    cp -f "$ROOT/$s" "$STAGE/MUTE/$s"
    cp -f "$ROOT/$s" "$STAGE/$s"
  fi
done

if [[ "$WITH_SECRETS" -eq 1 ]]; then
  if [[ -f "$ROOT/.env" ]]; then
    cp -f "$ROOT/.env" "$STAGE/MUTE/.env"
    chmod 600 "$STAGE/MUTE/.env"
    echo "INCLUDED .env — keep archive private"
  else
    echo "WARN: --with-secrets but .env missing"
  fi
else
  echo "NOTE: .env NOT included (use --with-secrets for private transfer)"
fi

{
  echo "MUTE Termix / Termux pack"
  echo "created: $(date -Iseconds)"
  echo "host: $(hostname 2>/dev/null || echo unknown)"
  echo "with_secrets: $WITH_SECRETS"
  echo "python: $(python3 --version 2>&1 || true)"
  echo
  du -sh \
    "$STAGE/MUTE/mute" \
    "$STAGE/MUTE/pump_prep" \
    "$STAGE/MUTE/scripts" \
    "$STAGE/MUTE/addresses" \
    "$STAGE/MUTE/data" \
    "$STAGE/MUTE/out" \
    "$STAGE/MUTE/crypto_funds_tracker" \
    2>/dev/null || true
} >"$STAGE/MUTE/PACK_MANIFEST.txt"

chmod +x "$STAGE/MUTE/START.sh" "$STAGE/MUTE/scripts/"*.sh \
  "$STAGE/MUTE/UNPACK.sh" "$STAGE/MUTE/START_FROM_DOCUMENTS.sh" 2>/dev/null || true
chmod +x "$STAGE/UNPACK.sh" "$STAGE/START_FROM_DOCUMENTS.sh" 2>/dev/null || true

echo "=== Compressing ==="
# Archive: MUTE/ + launchers at root (for Documents folder)
tar -C "$STAGE" -czf "$ARCHIVE" MUTE UNPACK.sh START_FROM_DOCUMENTS.sh
rm -rf "$STAGE"

# Stable name for Termux docs
cp -f "$ARCHIVE" "$ALIAS"

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$ARCHIVE" >"${ARCHIVE}.sha256"
  sha256sum "$ALIAS" >"${ALIAS}.sha256"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$ARCHIVE" >"${ARCHIVE}.sha256"
fi

echo
echo "OK: $ARCHIVE"
echo "    $ALIAS  (stable name)"
du -h "$ARCHIVE"
[[ -f "${ARCHIVE}.sha256" ]] && cat "${ARCHIVE}.sha256"
echo
echo "Documents (Termix / Termux / Linux):"
echo "  # скопіюй MUTE-termix.tar.gz у Documents"
echo "  cd ~/Documents   # або ~/storage/shared/Documents"
echo "  tar -xzf MUTE-termix.tar.gz"
echo "  bash START_FROM_DOCUMENTS.sh"
echo "  # панель: http://127.0.0.1:8765/"
echo
echo "Або: tar -xzf … && ./UNPACK.sh && cd MUTE && ./scripts/start_dashboard.sh"
