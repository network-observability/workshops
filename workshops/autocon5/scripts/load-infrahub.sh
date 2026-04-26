#!/usr/bin/env bash
# load-infrahub.sh — wait for Infrahub to be reachable, then run the
# Typer-based loader. The actual schema apply + data load happen inside
# `autocon5 load-infrahub` (which itself delegates to `nobs schema load`
# for the schema step).
set -euo pipefail

HERE="$(cd "$(dirname "$0")"/.. && pwd)"
cd "$HERE"

# shellcheck disable=SC1091
if [ -f .env ]; then
  set -o allexport
  . ./.env
  set +o allexport
fi

ADDRESS="${INFRAHUB_ADDRESS:-http://localhost:8000}"
case "$ADDRESS" in
  *infrahub-server*) ADDRESS="http://localhost:8000" ;;
esac

if [ -z "${INFRAHUB_API_TOKEN:-}" ]; then
  echo "ERROR: INFRAHUB_API_TOKEN is unset. Edit .env first." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<'EOF'
ERROR: 'uv' is not on PATH. Install it from https://docs.astral.sh/uv/

  curl -LsSf https://astral.sh/uv/install.sh | sh
EOF
  exit 1
fi

# Wait for Infrahub. First boot takes ~60s.
echo "Waiting for Infrahub at $ADDRESS ..."
for _ in $(seq 1 60); do
  if curl -sf "$ADDRESS/api/healthcheck" >/dev/null 2>&1 || \
     curl -sf "$ADDRESS/health" >/dev/null 2>&1; then
    echo "  Infrahub is reachable."
    break
  fi
  sleep 2
done

INFRAHUB_ADDRESS="$ADDRESS" \
INFRAHUB_API_TOKEN="$INFRAHUB_API_TOKEN" \
  uv run --project ../.. --package autocon5-workshop autocon5 load-infrahub
