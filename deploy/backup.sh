#!/usr/bin/env bash
# Dump Postgres to deploy/backups/ (run on VPS via cron).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TCG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$TCG_ROOT"

COMPOSE="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml"
BACKUP_DIR="$SCRIPT_DIR/backups"
mkdir -p "$BACKUP_DIR"

# shellcheck disable=SC1091
set -a && source .env && set +a

stamp="$(date +%Y%m%d_%H%M%S)"
out="$BACKUP_DIR/tcg_buylist_${stamp}.sql.gz"

$COMPOSE exec -T postgres pg_dump -U "${POSTGRES_USER:-tcg}" "${POSTGRES_DB:-tcg_buylist}" | gzip > "$out"
echo "Wrote $out"

# Keep last 14 dumps
find "$BACKUP_DIR" -name 'tcg_buylist_*.sql.gz' -type f | sort | head -n -14 | xargs -r rm -f
