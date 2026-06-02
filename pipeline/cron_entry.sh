#!/usr/bin/env bash
set -euo pipefail

TCG_ROOT="${TCG_ROOT:-/app}"
PIPELINE_CRON="${PIPELINE_CRON:-0 5 * * *}"
SCRYFALL_CRON="${SCRYFALL_CRON:-0 3 * * 0}"

echo "${PIPELINE_CRON} root cd ${TCG_ROOT} && /app/pipeline/run_daily.sh >> /var/log/tcg-pipeline.log 2>&1" > /etc/cron.d/tcg-jobs
echo "${SCRYFALL_CRON} root cd ${TCG_ROOT} && /app/pipeline/refresh_scryfall.sh >> /var/log/tcg-scryfall.log 2>&1" >> /etc/cron.d/tcg-jobs
chmod 0644 /etc/cron.d/tcg-jobs
crontab /etc/cron.d/tcg-jobs

touch /var/log/tcg-pipeline.log /var/log/tcg-scryfall.log
echo "Scheduler started (TZ=${TZ:-UTC}, pipeline='${PIPELINE_CRON}', scryfall='${SCRYFALL_CRON}')"
cron -f
