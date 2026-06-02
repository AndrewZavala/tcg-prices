# Deploy TCG Prices to production

Public site: **https://tcgprices.aizo.solutions**

Stack: Docker Compose (Postgres + FastAPI + Caddy HTTPS + daily cron).

## 1. DNS (aizo.solutions)

At your DNS provider (Cloudflare, registrar, etc.) add:

| Type | Name | Value |
|------|------|-------|
| **A** | `tcgprices` | Your VPS public IPv4 |

Optional: if you use Cloudflare proxy (orange cloud), SSL mode should be **Full** — Caddy still obtains its own cert on the VPS.

Verify before deploy:

```bash
dig +short tcgprices.aizo.solutions
# should return your VPS IP
```

## 2. VPS setup

Ubuntu 24.04, 2 GB RAM minimum. Open firewall ports **22**, **80**, **443** only.

```bash
sudo apt update && sudo apt install -y git
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
# log out and back in
```

Clone the repo:

```bash
sudo mkdir -p /opt/tcg
sudo chown "$USER:$USER" /opt/tcg
git clone YOUR_REPO_URL /opt/tcg
cd /opt/tcg
```

## 3. Configure environment

```bash
cp deploy/.env.production.example .env
nano .env   # set ACME_EMAIL, confirm SITE_DOMAIN and POSTGRES_PASSWORD
```

Or run the bootstrap script (generates a password on first run):

```bash
bash deploy/deploy.sh   # first run creates .env — edit it, run again
bash deploy/deploy.sh   # second run deploys
```

## 4. Start production stack

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d
```

Services:

| Service | Role |
|---------|------|
| `postgres` | Buylist snapshots (not exposed to internet) |
| `web` | FastAPI + UI (internal only) |
| `caddy` | HTTPS reverse proxy on 443 |
| `scheduler` | Daily CK pipeline + weekly Scryfall refresh |

First data load:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml run --rm pipeline bash /app/pipeline/refresh_scryfall.sh
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml run --rm pipeline bash /app/pipeline/run_daily.sh
```

## 5. Updates

```bash
cd /opt/tcg
git pull
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml build web
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d
```

## 6. Backups

Nightly dump (add to root crontab on VPS):

```cron
0 4 * * * cd /opt/tcg && bash deploy/backup.sh >> /var/log/tcg-backup.log 2>&1
```

Backups land in `deploy/backups/`.

## 7. Logs

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml logs -f web caddy scheduler
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml exec scheduler tail -f /var/log/tcg-pipeline.log
```

## Subdomain / branding

Default subdomain is `tcgprices.aizo.solutions`. To change it, update in `.env`:

- `SITE_DOMAIN`
- `CORS_ORIGINS`

Then restart Caddy:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d caddy
```
