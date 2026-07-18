#!/usr/bin/env bash
# Bootstrap Manifest Bread on a fresh Ubuntu VPS with Docker installed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TCG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$TCG_ROOT"

COMPOSE="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml"

echo "==> Manifest Bread deploy (root: $TCG_ROOT)"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found. Install first: curl -fsSL https://get.docker.com | sh"
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "==> Creating .env from deploy/.env.production.example"
  cp deploy/.env.production.example .env
  pw="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
  sed -i "s/CHANGE_ME/${pw}/g" .env
  echo "    Generated POSTGRES_PASSWORD — saved in .env"
  echo "    Edit .env: set ACME_EMAIL and confirm SITE_DOMAIN before continuing."
  echo "    Re-run this script after editing .env."
  exit 0
fi

# shellcheck disable=SC1091
set -a && source .env && set +a

if [[ "${POSTGRES_PASSWORD:-}" == "CHANGE_ME" ]] || [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "Set POSTGRES_PASSWORD in .env before deploying."
  exit 1
fi

echo "==> Building images"
$COMPOSE build

echo "==> Starting postgres, web, scheduler, caddy"
$COMPOSE up -d postgres web scheduler caddy

echo "==> Waiting for Postgres"
for i in $(seq 1 30); do
  if $COMPOSE exec -T postgres pg_isready -U "${POSTGRES_USER:-tcg}" -d "${POSTGRES_DB:-tcg_buylist}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if [[ ! -f helper/scryfall_cards_lookup.csv ]]; then
  echo "==> Scryfall lookup missing — downloading (10+ minutes)"
  $COMPOSE run --rm pipeline bash /app/pipeline/refresh_scryfall.sh
else
  echo "==> Scryfall lookup present ($(wc -l < helper/scryfall_cards_lookup.csv) lines)"
fi

echo "==> Running daily pipeline (first load)"
$COMPOSE run --rm pipeline bash /app/pipeline/run_daily.sh

DOMAIN="${SITE_DOMAIN:-manifestbread.aizo.solutions}"
echo ""
echo "============================================"
echo " Deploy complete."
echo ""
echo " DNS (at your aizo.solutions registrar / Cloudflare):"
echo "   Type: A"
echo "   Name: manifestbread"
echo "   Value: YOUR_VPS_PUBLIC_IP"
echo ""
echo " Site (after DNS propagates):"
echo "   https://${DOMAIN}/"
echo ""
echo " Useful commands:"
echo "   $COMPOSE ps"
echo "   $COMPOSE logs -f web caddy scheduler"
echo "   $COMPOSE run --rm pipeline bash /app/pipeline/run_daily.sh"
echo "   bash deploy/backup.sh"
echo "============================================"
