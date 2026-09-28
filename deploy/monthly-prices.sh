#!/usr/bin/env bash
# Monthly Spell Tag refresh (host crontab on the VPS): TCGplayer prices, then Limitless decklist flags.
#   0 9 1 * * bash /opt/spelltag/deploy/monthly-prices.sh >> /var/log/spelltag-prices.log 2>&1
set -uo pipefail

# Space-separated YYYY-MM-DD dates to skip (override in the crontab environment if needed).
SKIP_DATES="${SPELLTAG_PRICE_SKIP_DATES:-2026-10-01}"
today="$(date +%F)"
for skip in $SKIP_DATES; do
  if [ "$skip" = "$today" ]; then
    echo "$(date -Is) skipping monthly refresh ($today is in SKIP_DATES)"
    exit 0
  fi
done

cd "${SPELLTAG_DIR:-/opt/spelltag}" || exit 1
compose=(docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual)
status=0

echo "$(date -Is) starting price refresh"
"${compose[@]}" run --rm -T star-piece-pipeline python pipeline/refresh_pokemon_prices.py || status=1

echo "$(date -Is) starting Limitless decklist refresh"
"${compose[@]}" run --rm -T star-piece-pipeline python pipeline/refresh_limitless_decklists.py || status=1

echo "$(date -Is) monthly refresh done (status $status)"
exit "$status"
