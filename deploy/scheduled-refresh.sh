#!/usr/bin/env bash
# Scheduled Spell Tag refreshes (host crontab on the VPS):
#   prices     TCGplayer prices (weekly)
#   decklists  Limitless decklist flags for is:competitive (monthly)
#
#   0 9 * * 1  bash /opt/spelltag/deploy/scheduled-refresh.sh prices    >> /var/log/spelltag-prices.log 2>&1
#   30 9 1 * * bash /opt/spelltag/deploy/scheduled-refresh.sh decklists >> /var/log/spelltag-prices.log 2>&1
set -uo pipefail

job="${1:-}"
case "$job" in
  prices) script=pipeline/refresh_pokemon_prices.py ;;
  decklists) script=pipeline/refresh_limitless_decklists.py ;;
  *) echo "usage: $0 prices|decklists" >&2; exit 2 ;;
esac

# Space-separated YYYY-MM-DD dates to skip (override in the crontab environment if needed).
SKIP_DATES="${SPELLTAG_PRICE_SKIP_DATES:-2026-10-01}"
today="$(date +%F)"
for skip in $SKIP_DATES; do
  if [ "$skip" = "$today" ]; then
    echo "$(date -Is) skipping $job refresh ($today is in SKIP_DATES)"
    exit 0
  fi
done

cd "${SPELLTAG_DIR:-/opt/spelltag}" || exit 1
echo "$(date -Is) starting $job refresh"
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual \
  run --rm -T star-piece-pipeline python "$script"
status=$?
echo "$(date -Is) $job refresh done (status $status)"
exit "$status"
