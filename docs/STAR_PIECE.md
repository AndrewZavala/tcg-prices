# Star Piece — own Postgres + images; not Manifest Bread
#
# Local:
#   docker compose up -d star-piece-db star-piece
#   http://localhost:8001
#
# Migrate existing catalog from Manifest Bread DB (one-shot):
#   .\pipeline\migrate_pokemon_to_star_piece.ps1
#
# Ingest / enrich (writes to star-piece-db only):
#   .\pipeline\run_pokemon_pipeline.ps1 -Series bw

## Services

| Service | Role |
|---------|------|
| `star-piece-db` | Postgres 16, DB `star_piece`, host port **5433** |
| `star-piece` | FastAPI UI + `/api/pokemon/*` (`Dockerfile.star-piece`) |
| `star-piece-pipeline` | TCGdex/enrich jobs (`Dockerfile.star-piece-pipeline`, profile `manual`) |

Manifest Bread keeps `postgres` / `web` / `pipeline` / `scheduler` on the MTG buylist DB.

## Env (optional `.env`)

```
STAR_PIECE_PG_USER=starpiece
STAR_PIECE_PG_PASSWORD=starpiece_secret
STAR_PIECE_PG_DB=star_piece
STAR_PIECE_PG_PORT=5433
STAR_PIECE_CORS_ORIGINS=http://localhost:8001
```

## Owned code

| Area | Paths |
|------|--------|
| App | `web/star_piece_main.py`, `web/pokemon_api.py`, `web/tcgplayer_links.py` |
| UI | `web/static/pokemon.*`, `star-piece.*` |
| Pipeline | `pipeline/refresh_tcgdex.py`, `*pokemon*`, `run_pokemon_pipeline.ps1` |
| Schema | `migrations/025`–`030`, `migrations/star_piece_init/` |
| Images | `Dockerfile.star-piece`, `Dockerfile.star-piece-pipeline`, volume `card_images` |
| Local art | `pipeline/download_pokemon_images.py` → `/media/cards/{id}/{grid,high}.webp` |

## Card images (self-hosted)

```bash
docker compose --profile manual run --rm star-piece-pipeline \
  python pipeline/download_pokemon_images.py --set xy1 --limit 20
```

Files land in Docker volume `card_images` (`CARD_IMAGE_ROOT=/data/card-images`).
API returns `/media/cards/{id}/grid.webp` once `image_local` is true.

- **`grid.webp`** — ~512px wide (search grid; derived from high so Retina zoom stays sharp)
- **`high.webp`** — full art (card modal)
- **`low.webp`** — same bytes as grid (legacy path)

Rewrite grid tiles from existing full art (no re-download):

```bash
docker compose --profile manual run --rm star-piece-pipeline \
  python pipeline/download_pokemon_images.py --regen-grid
```

1. DNS at your registrar (Squarespace or wherever): **A/AAAA** for `spelltag.com` (and optional `www`) → your VPS public IP. DNS-only is fine.
2. On the server `.env` (see `deploy/.env.production.example`):
   - `SPELLTAG_DOMAIN=spelltag.com` (or `spelltag.com, www.spelltag.com` if you add www in Caddy)
   - `SPELLTAG_CORS_ORIGINS=https://spelltag.com,https://www.spelltag.com`
   - `ACME_EMAIL=you@example.com`
3. Deploy with prod overlay (starts `star-piece` + Caddy TLS):
   ```bash
   docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d star-piece-db star-piece caddy
   ```
4. Manifest Bread host stays basic-auth gated; Spell Tag has **no** basic auth.
5. Optional: scheduled `star-piece-pipeline` cron; drop leftover `pokemon_*` from `tcg_buylist` after you’re happy.
