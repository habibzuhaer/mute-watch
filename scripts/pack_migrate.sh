#!/usr/bin/env bash
# Pack MUTE for migration to another machine.
# Usage:
#   ./scripts/pack_migrate.sh              # without .env
#   ./scripts/pack_migrate.sh --with-secrets  # includes .env (private transfer only)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

WITH_SECRETS=0
for a in "$@"; do
  case "$a" in
    --with-secrets|-s) WITH_SECRETS=1 ;;
    -h|--help)
      echo "Usage: $0 [--with-secrets]"
      exit 0
      ;;
  esac
done

STAMP="$(date +%Y%m%d-%H%M)"
OUT_DIR="$ROOT/dist"
NAME="MUTE-migrate-${STAMP}"
STAGE="$OUT_DIR/_stage_${NAME}"
ARCHIVE="$OUT_DIR/${NAME}.tar.gz"

mkdir -p "$OUT_DIR"
rm -rf "$STAGE"
mkdir -p "$STAGE/MUTE"

echo "=== Regenerating panel/hub snapshot (best effort) ==="
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" -m pump_prep panel >/dev/null 2>&1 || true
  PYTHONPATH="$ROOT" "$ROOT/.venv/bin/python" -c "from pump_prep.hub import write_hub_html; write_hub_html()" >/dev/null 2>&1 || true
fi

echo "=== Copying tree ==="
# rsync preferred; fallback to tar pipe
copy_tree() {
  local src="$1" dst="$2"
  mkdir -p "$dst"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a \
      --exclude '.venv/' \
      --exclude '*/.venv/' \
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
      "$src" "$dst"
  else
    tar -C "$ROOT" \
      --exclude='.venv' \
      --exclude='*/.venv' \
      --exclude='__pycache__' \
      --exclude='*.pyc' \
      --exclude='.git' \
      --exclude='logs' \
      --exclude='*.pid' \
      --exclude='dist' \
      --exclude='.env' \
      -cf - . | tar -C "$dst" -xf -
  fi
}

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
    "$ROOT/" "$STAGE/MUTE/"
else
  copy_tree "$ROOT/" "$STAGE/MUTE/"
fi

# Ensure critical paths exist even if empty
mkdir -p \
  "$STAGE/MUTE/data/graph" \
  "$STAGE/MUTE/data/prep" \
  "$STAGE/MUTE/out" \
  "$STAGE/MUTE/pump_prep/out" \
  "$STAGE/MUTE/addresses" \
  "$STAGE/MUTE/logs"

cp -f "$ROOT/MIGRATE.txt" "$STAGE/MUTE/MIGRATE.txt"
cp -f "$ROOT/.env.example" "$STAGE/MUTE/.env.example" 2>/dev/null || true

if [[ "$WITH_SECRETS" -eq 1 ]]; then
  if [[ -f "$ROOT/.env" ]]; then
    cp -f "$ROOT/.env" "$STAGE/MUTE/.env"
    chmod 600 "$STAGE/MUTE/.env"
    echo "INCLUDED .env (secrets) — keep archive private"
  else
    echo "WARN: --with-secrets but .env missing"
  fi
else
  echo "NOTE: .env NOT included. Use --with-secrets for private transfer, or fill .env.example on the new machine."
fi

# Manifest
{
  echo "MUTE migrate pack"
  echo "created: $(date -Iseconds)"
  echo "host: $(hostname 2>/dev/null || echo unknown)"
  echo "with_secrets: $WITH_SECRETS"
  echo "python: $(command -v python3 && python3 --version 2>&1 || true)"
  echo
  echo "=== sizes ==="
  du -sh \
    "$STAGE/MUTE/mute" \
    "$STAGE/MUTE/pump_prep" \
    "$STAGE/MUTE/scripts" \
    "$STAGE/MUTE/addresses" \
    "$STAGE/MUTE/data" \
    "$STAGE/MUTE/out" \
    "$STAGE/MUTE/crypto_funds_tracker" \
    2>/dev/null || true
  echo
  echo "=== graph progress (if any) ==="
  if [[ -f "$STAGE/MUTE/data/graph/state.json" ]]; then
    python3 - "$STAGE/MUTE/data/graph/state.json" <<'PY' 2>/dev/null || true
import json,sys
p=sys.argv[1]
d=json.load(open(p))
print("cycles:", d.get("cycles"))
print("done_tokens:", d.get("done_tokens") or d.get("token_cursor"))
print("updated_at:", d.get("updated_at"))
print("expand_queue:", len(d.get("expand_queue") or []))
PY
  fi
} >"$STAGE/MUTE/PACK_MANIFEST.txt"

chmod +x "$STAGE/MUTE/START.sh" "$STAGE/MUTE/scripts/"*.sh 2>/dev/null || true

echo "=== Compressing ==="
tar -C "$STAGE" -czf "$ARCHIVE" MUTE
rm -rf "$STAGE"

# Companion checksum
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$ARCHIVE" >"${ARCHIVE}.sha256"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$ARCHIVE" >"${ARCHIVE}.sha256"
fi

echo
echo "OK: $ARCHIVE"
du -h "$ARCHIVE"
[[ -f "${ARCHIVE}.sha256" ]] && cat "${ARCHIVE}.sha256"
echo
echo "На новой машине:"
echo "  tar -xzf $(basename "$ARCHIVE") && cd MUTE && less MIGRATE.txt && ./START.sh"
echo "  ./scripts/start_dashboard.sh   # http://127.0.0.1:8765/"
