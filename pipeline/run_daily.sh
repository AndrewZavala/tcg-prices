#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TCG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export TCG_ROOT
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

cd "$TCG_ROOT"

echo "[$(date -Iseconds)] Starting daily CK buylist pipeline"

python3 "$SCRIPT_DIR/scrape_ck.py"
python3 "$SCRIPT_DIR/merge_buylist.py"
python3 "$SCRIPT_DIR/enrich_buylist.py"
python3 "$SCRIPT_DIR/load_postgres.py"

echo "[$(date -Iseconds)] Pipeline completed successfully"
