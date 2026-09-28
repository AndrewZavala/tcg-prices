#!/usr/bin/env bash
# Monthly TCGplayer price refresh for Spell Tag (host crontab on the VPS):
#   0 9 1 * * bash /opt/spelltag/deploy/monthly-prices.sh >> /var/log/spelltag-prices.log 2>&1
set -euo pipefail

# Space-separated YYYY-MM-DD dates to skip (override in the crontab environment if needed).
SKIP_DATES="${SPELLTAG_PRICE_SKIP_DATES:-2026-10-01}"
today="$(date +%F)"
for skip in $SKIP_DATES; do
  if [ "$skip" = "$today" ]; then
    echo "$(date -Is) skipping price refresh ($today is in SKIP_DATES)"
    exit 0
  fi
done

cd "${SPELLTAG_DIR:-/opt/spelltag}"
echo "$(date -Is) starting price refresh"
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual \
  run --rm -T star-piece-pipeline python pipeline/refresh_pokemon_prices.py
echo "$(date -Is) price refresh done"
