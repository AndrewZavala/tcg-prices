#!/usr/bin/env bash
# Fetch TCGplayer listing rows via mp-search API (browser session required).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAX_ATTEMPTS="${TCG_LISTINGS_FETCH_RETRIES:-8}"
RETRY_DELAY="${TCG_LISTINGS_FETCH_RETRY_SEC:-45}"

if [[ -z "${TCG_BROWSER_CDP_URL:-}" ]]; then
  echo "ERROR: TCG_BROWSER_CDP_URL is required for mp-search API listings." >&2
  exit 1
fi

for ((attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)); do
  echo "[$(date -Iseconds)] TCG listings fetch attempt ${attempt}/${MAX_ATTEMPTS}"
  if python3 "$SCRIPT_DIR/browser_tcg_listings.py"; then
    echo "[$(date -Iseconds)] TCG listings fetch succeeded"
    exit 0
  fi
  if (( attempt < MAX_ATTEMPTS )); then
    echo "Retrying in ${RETRY_DELAY}s..." >&2
    sleep "$RETRY_DELAY"
  fi
done

echo "ERROR: TCG listings fetch failed after ${MAX_ATTEMPTS} attempts." >&2
exit 1
