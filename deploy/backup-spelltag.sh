#!/usr/bin/env bash
# Nightly Spell Tag database dump (host crontab on the VPS):
#   0 10 * * * bash /opt/spelltag/deploy/backup-spelltag.sh >> /var/log/spelltag-backup.log 2>&1
# Restore: see deploy/README.md "Spell Tag backups".
set -euo pipefail
umask 077  # dumps contain user emails

cd "${SPELLTAG_DIR:-/opt/spelltag}"
BACKUP_DIR="deploy/backups"
KEEP="${SPELLTAG_BACKUP_KEEP:-14}"
mkdir -p "$BACKUP_DIR"

out="$BACKUP_DIR/spelltag_$(date +%Y%m%d_%H%M%S).dump"
tmp="$out.partial"
trap 'rm -f "$tmp"' EXIT

# Custom format is already compressed; credentials come from the container's own env.
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml exec -T star-piece-db \
  sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$tmp"

if [ ! -s "$tmp" ]; then
  echo "$(date -Is) backup FAILED: empty dump" >&2
  exit 1
fi
mv "$tmp" "$out"
echo "$(date -Is) wrote $out ($(du -h "$out" | cut -f1))"

find "$BACKUP_DIR" -name 'spelltag_*.dump' -type f | sort | head -n -"$KEEP" | xargs -r rm -f
