#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TCG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export TCG_ROOT
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

cd "$TCG_ROOT"
echo "[$(date -Iseconds)] Refreshing Scryfall bulk lookup"
python3 "$SCRIPT_DIR/refresh_scryfall.py"
echo "[$(date -Iseconds)] Scryfall refresh done"
