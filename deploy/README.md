# Deploy Manifest Bread to production

Public site: **https://manifestbread.aizo.solutions**

Stack: Docker Compose (Postgres + FastAPI + Caddy HTTPS + daily cron).

**Local vs cloud:** Your laptop (`http://localhost:8000`) and the VPS are **separate** databases. Deploying to aizo does **not** remove or break local. Keep taking local backups so you can recover if the VPS dies (or the other way around).

## 0. Local backup (laptop — before / during cloud use)

From the repo root on Windows, with local Docker Postgres running:

```powershell
powershell -File deploy/backup-local.ps1
```

Dumps land in `deploy/backups/tcg_buylist_YYYYMMDD_HHMMSS.sql.gz` (last 14 kept; not committed to git).

Restore only if you need that snapshot back (replaces local DB):

```powershell
powershell -File deploy/restore-local.ps1 -BackupFile deploy\backups\tcg_buylist_YYYYMMDD_HHMMSS.sql.gz
```

Copy a dump off-machine (OneDrive, USB, etc.) if you want protection against laptop disk failure too.

VPS backups use `deploy/backup.sh` (see §6 below).

## 1. DNS (aizo.solutions)

At your DNS provider (Cloudflare, registrar, etc.) add:

| Type | Name | Value |
|------|------|-------|
| **A** | `manifestbread` | Your VPS public IPv4 |

Optional: if you use Cloudflare proxy (orange cloud), SSL mode should be **Full** — Caddy still obtains its own cert on the VPS.

Verify before deploy:

```bash
dig +short manifestbread.aizo.solutions
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
git clone https://github.com/AndrewZavala/tcg-prices.git /opt/tcg
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

## 3b. Site password (Caddy basic auth)

Inventory must not be public. On the VPS, generate a bcrypt hash:

```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'YOUR_SITE_PASSWORD'
```

Put the hash in `.env`:

```bash
BASIC_AUTH_USER=andre
BASIC_AUTH_HASH='$2a$14$....'   # paste hash from above; keep single quotes
```

See `deploy/Caddyfile` — Caddy prompts for this user/password before serving the GUI.

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

## 6. Backups (VPS)

Nightly dump (add to root crontab on VPS):

```cron
0 4 * * * cd /opt/tcg && bash deploy/backup.sh >> /var/log/tcg-backup.log 2>&1
```

Backups land in `deploy/backups/`. Periodically `scp` a dump to your laptop or object storage so a VPS wipe is recoverable.

## 7. Logs

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml logs -f web caddy scheduler
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml exec scheduler tail -f /var/log/tcg-pipeline.log
```

## Subdomain / branding

Default Manifest Bread host is `manifestbread.aizo.solutions`. To change it, update in `.env`:

- `SITE_DOMAIN`
- `CORS_ORIGINS`

Then restart Caddy:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d caddy
```

## Spell Tag (spelltag.com)

Public Pokémon catalog — **no** basic auth. This production overlay (`deploy/docker-compose.prod.yml` + `deploy/Caddyfile`) is for Spell Tag only.

1. Point DNS **A/AAAA** for `spelltag.com` at the VPS.
2. Copy env and set passwords / ACME email:

```bash
cp deploy/.env.production.example .env
nano .env   # STAR_PIECE_PG_PASSWORD, ACME_EMAIL, SPELLTAG_*
```

3. Bring up the stack:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d star-piece-db star-piece caddy
```

4. Load catalog data (example):

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual run --rm star-piece-pipeline \
  python pipeline/refresh_tcgdex.py --series sv --enrich
```

### Self-hosted card images

Card art is mirrored onto the VPS (`card_images` Docker volume) and served at
`https://spelltag.com/media/cards/{id}/grid.webp` (search, ~512px) and `.../high.webp` (detail).
Remote TCGdex / pokemontcg URLs stay in `pokemon_cards.image_url` for re-download only.

After deploy (rebuild pipeline image for Pillow + new scripts):

```bash
cd /opt/spelltag
git pull --ff-only origin spell-tag
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build star-piece caddy
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual build star-piece-pipeline
# Migrations run on web startup. If a pull only adds migrations/*.sql, the container is not
# recreated or reloaded, so restart it:
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml restart star-piece

# Re-ingest SWSH Black Star Promos (picks up cards TCGdex added without art, e.g. SWSH303–305)
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual run --rm star-piece-pipeline \
  python pipeline/refresh_tcgdex.py --set swshp

# Mirror missing art (uses pokemontcg.io + official pokemon.com fallbacks for promo gaps like SWSH301)
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual run --rm star-piece-pipeline \
  python pipeline/download_pokemon_images.py --set swshp

# Celebrations Classic Collection (CC### maps to original reprint #s on pokemontcg.io)
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual run --rm star-piece-pipeline \
  python pipeline/download_pokemon_images.py --set cel25cc --force
```

# Full mirror (~19k cards, polite delay — run in screen/tmux)
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual run --rm star-piece-pipeline \
  python pipeline/download_pokemon_images.py

# Or smoke-test one set first:
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual run --rm star-piece-pipeline \
  python pipeline/download_pokemon_images.py --set xy1 --limit 20
```

Upgrade existing thumbs to 512px grid (local resize from `high.webp`, no CDN traffic — a few minutes):

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual run --rm star-piece-pipeline \
  python pipeline/download_pokemon_images.py --regen-grid
```

Confirm in DevTools Network that grid images are same-origin `/media/cards/...` (not `assets.tcgdex.net`).
Watch disk: `df -h`.

### Monthly TCGplayer prices

`pipeline/refresh_pokemon_prices.py` pulls English Pokémon TCGplayer prices (USD) from
[tcgcsv.com](https://tcgcsv.com) — ~441 requests, ~2 minutes. It fills missing
`tcgplayer_product_id`s by set + number + name, replaces `pokemon_card_prices` (latest only),
and caches the cheapest variant in `pokemon_cards.price_usd`. It refuses to write if fewer than
5,000 printings come back priced. No site downtime (short row updates, no table locks).

Run once by hand:

```bash
cd /opt/spelltag
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual run --rm star-piece-pipeline \
  python pipeline/refresh_pokemon_prices.py
```

### Limitless decklist flags (`is:competitive`)

`pipeline/refresh_limitless_decklists.py` checks Standard-legal cards only (same rule as
`f:standard`). It loads one Limitless card page per oracle (Limitless shares decklists across
reprints), looks for "does not appear in any decklist", and copies the result to every printing
(`pokemon_cards.limitless_decklists`). One request per second. Progress is saved per card, so it
can be stopped and re-run.

First run (~2k pages, ~45 minutes — run in `tmux`):

```bash
cd /opt/spelltag
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile manual run --rm star-piece-pipeline \
  python pipeline/refresh_limitless_decklists.py
```

Later runs recheck Standard cards not yet known to have decklists (`--all` also rechecks the ones
that do).

### Standard rotation

Standard legality comes from `pokemon_standard_rotations` (migration 049). When the next rotation
is announced, add a row ahead of time — it takes effect on its start date:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml exec star-piece-db \
  psql -U starpiece -d star_piece -c "INSERT INTO pokemon_standard_rotations VALUES ('2027-04-09', 'I');"
```

### Monthly schedule

Schedule both on the host (1st of each month, 09:00 server time). `deploy/monthly-prices.sh`
runs prices, then decklist flags, and skips dates listed in `SPELLTAG_PRICE_SKIP_DATES`
(default `2026-10-01`):

```bash
crontab -e
# add:
0 9 1 * * bash /opt/spelltag/deploy/monthly-prices.sh >> /var/log/spelltag-prices.log 2>&1
```

### Google sign-in

1. In [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services** → **Credentials**, create an **OAuth 2.0 Client ID** (application type: Web application).
2. Under **Authorized redirect URIs**, add:
   - `https://spelltag.com/auth/google/callback`
   - `http://localhost:8001/auth/google/callback` (local dev)
3. OAuth consent screen: External, app name **Spell Tag**. While in Testing, add your Google account as a test user.
4. Put values in `/opt/spelltag/.env`:

```bash
SPELLTAG_PUBLIC_URL=https://spelltag.com
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=....
SPELLTAG_SESSION_SECRET=$(openssl rand -hex 32)
```

5. Rebuild the app:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build star-piece
```

6. Confirm: `https://spelltag.com/auth/status` should show `"google_configured": true`. Use **Sign in** in the top bar.
