# Manifest Bread

**Turn bulk into bread.** Daily Card Kingdom buylist pipeline with Scryfall enrichment, Postgres storage, and a public UI — production at [manifestbread.aizo.solutions](https://manifestbread.aizo.solutions).

GitHub: [AndrewZavala/tcg-prices](https://github.com/AndrewZavala/tcg-prices)

## Project layout

```
TCG/
  pipeline/          scrape, merge, enrich, load, cron scripts
  helper/            scryfall_set_lookup.csv, scryfall_cards_lookup.csv (generated)
  data/buylist/      raw, master, enriched CSVs
  Buylist/           legacy segment CSVs (still supported for merge)
  migrations/        Postgres schema
  web/               FastAPI + static UI
  docs/PHASE2.md     inventory / sell-list extension notes
```

## Quick start (Docker on VPS)

1. Copy `.env.example` to `.env` and adjust secrets.
2. **First-time:** refresh Scryfall lookup (large download, ~10+ minutes):

   ```bash
   docker compose run --rm pipeline python3 pipeline/refresh_scryfall.py
   ```

3. Start Postgres + web + scheduler:

   ```bash
   docker compose up -d postgres web scheduler
   ```

4. Run pipeline once manually:

   ```bash
   docker compose run --rm pipeline /app/pipeline/run_daily.sh
   ```

5. Open http://localhost:8000

## Production deploy (manifestbread.aizo.solutions)

See **[deploy/README.md](deploy/README.md)** for full VPS setup.

Quick summary:

1. DNS: **A record** `manifestbread` → your VPS IP (on `aizo.solutions`).
2. Clone repo to `/opt/tcg`, copy `deploy/.env.production.example` → `.env`.
3. Run `bash deploy/deploy.sh` (twice — first creates secrets, second deploys).
4. Site goes live at **https://manifestbread.aizo.solutions** (Caddy auto-HTTPS).

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d
```

## Web features

| Page | URL | Description |
|------|-----|-------------|
| Buylist search | `/` | Browse current CK buylist |
| Opportunities | `/opportunities` | TCG→CK arbitrage candidates |
| Inventory | `/inventory` | TCG flip lots + CK fulfillments |
| CK returns | `/returns` | Flip P&L / open book |
| Sell list | `/sell-list` | Stacks collection × current CK buylist (by batch); export CK CSV + mark sold |
| Match collection | `/match` | One-off CSV upload match (not saved) |
| Price history | `/charts` | Line chart: CK cash/credit vs TCGplayer market/low/mid (tcgcsv) over time |

Import Stacks `Batch*_export.csv` via Sell list → **All cards** → Import, or:

```powershell
docker compose run --rm pipeline python3 /app/pipeline/import_stacks.py
```

(Requires a `Stacks/` folder under the repo root.)

Price history needs **multiple daily pipeline runs** — each run stores a dated snapshot in Postgres.

## Daily pipeline

`pipeline/run_daily.sh` runs:

1. `scrape_ck.py` — CK public pricelist JSON (`api.cardkingdom.com`) → `data/buylist/raw/{date}/`
2. `merge_buylist.py` — uses API CSV only when present (skips legacy `Buylist/` segments)
3. `fetch_tcg_listings.sh` / `browser_tcg_listings.py` — live TCGplayer mp-search API listings → `helper/tcg_listings_lookup.csv`
4. `enrich_buylist.py` — Scryfall IDs + live listing prices + condition-adjusted CK/TCG spread
5. `load_postgres.py` — upsert snapshot into Postgres

### Browser-backed TCGplayer listings

If Docker/server requests to `mp-search-api.tcgplayer.com` are blocked, run the browser-backed API fetcher on your Windows host. It opens a real Edge/Chrome session, calls the same JSON listing API from inside the TCGplayer page context, and writes `helper/tcg_listings_lookup.csv` for the normal enrich/load steps.

```powershell
pip install -r requirements.txt
python -m playwright install chromium
python pipeline/browser_tcg_listings.py
```

Useful env vars:

- `TCG_LISTINGS_MAX_PRODUCTS` — limit product/finish pairs, prioritized by CK cash; default `5000`.
- `TCG_BROWSER_CHANNEL` — browser channel, default `msedge`.
- `TCG_BROWSER_HEADLESS` — keep `0` for a visible real browser.
- `TCG_BROWSER_LISTING_PAGE_SIZE` — listing rows per API call, default `10` to match TCGplayer's page request.
- `TCG_BROWSER_PROFILE_DIR` — persistent browser profile/cookie directory.

If Python is only available inside Docker, start Edge on Windows with remote debugging and connect from the pipeline container via CDP:

```powershell
Start-Process "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" `
  -ArgumentList "--remote-debugging-port=9222", "--remote-debugging-address=0.0.0.0", "https://www.tcgplayer.com"

$ip = docker compose run --rm pipeline python3 -c "import socket; print(socket.gethostbyname('host.docker.internal'))" | Select-Object -Last 1
$ws = (curl.exe -sS "http://127.0.0.1:9222/json/version" | ConvertFrom-Json).webSocketDebuggerUrl -replace 'ws://(127\.0\.0\.1|localhost):9222', "ws://$ip`:9222"
docker compose run --rm -e TCG_BROWSER_CDP_URL=$ws pipeline sh -lc "python3 -m pip install -q playwright && python3 /app/pipeline/browser_tcg_listings.py"
```

### Set name normalization

CK edition strings are mapped to Scryfall via [`helper/ck_set_aliases.csv`](helper/ck_set_aliases.csv) and rules in [`pipeline/set_normalize.py`](pipeline/set_normalize.py) (Universes Beyond prefix, Secret Lair → Secret Lair Drop, numbered editions, commander deck names, etc.). Add rows to the alias CSV when you find new CK naming quirks.

Scheduler container uses cron (`PIPELINE_CRON`, default `0 5 * * *` in `TZ`).

## Local / R workflow

From repo root with R installed:

```r
source("pipeline/refresh_scryfall.R")  # weekly
source("pipeline/merge_buylist.R")     # or tcg_scraper.R
source("pipeline/enrich_ck.R")
```

Set `TCG_ROOT` if not running from the repo directory.

## Environment variables

See [.env.example](.env.example). Key values:

| Variable | Purpose |
|----------|---------|
| `TCG_ROOT` | Repo root path |
| `DATABASE_URL` | Postgres connection |
| `TZ` | Timezone for cron (e.g. `America/New_York`) |
| `PIPELINE_CRON` | Daily job schedule |
| `SCRYFALL_CRON` | Weekly Scryfall refresh |

## VPS cron without Docker scheduler

```cron
0 5 * * * cd /opt/tcg && ./pipeline/run_daily.sh >> /var/log/tcg-pipeline.log 2>&1
0 3 * * 0 cd /opt/tcg && ./pipeline/refresh_scryfall.sh >> /var/log/tcg-scryfall.log 2>&1
```

Install deps: `pip install -r requirements.txt`

## Star Piece (Pokémon catalog)

Separate from the MTG buylist pipeline and from **Manifest Bread** as a product.
Ingests TCGdex card data into Postgres and enriches for the Star Piece UI.

**Local Star Piece** (own Postgres on `:5433` + app on `:8001`):

```bash
docker compose up -d star-piece-db star-piece
```

One-shot copy of existing catalog from Manifest Bread DB:

```powershell
.\pipeline\migrate_pokemon_to_star_piece.ps1
```

See [docs/STAR_PIECE.md](docs/STAR_PIECE.md).

### Pipeline flow

| Step | Script | Source |
|------|--------|--------|
| Ingest | `refresh_tcgdex.py` | [TCGdex](https://tcgdex.dev) |
| Subtypes | `enrich_pokemon_subtypes.py` | [pokemontcg.io](https://dev.pokemontcg.io) (free API key) |
| Species | `build_pokemon_species.py` | [PokeAPI](https://pokeapi.co) (generation, legendary/mythical) |
| Oracles | `build_pokemon_oracle.py` | local grouping |

**One command** (ingest + enrich):

```powershell
.\pipeline\run_pokemon_pipeline.ps1 -Series bw
.\pipeline\run_pokemon_pipeline.ps1 -Series me   # Mega Evolution → Pitch Black
```

Or a single set with enrich chained:

```powershell
docker compose run --rm pipeline python pipeline/refresh_tcgdex.py --set sv1 --enrich
```

Re-enrich without re-fetching TCGdex (e.g. after adding `POKEMONTCG_API_KEY`):

```powershell
.\pipeline\run_pokemon_pipeline.ps1 -SkipIngest
.\pipeline\run_pokemon_pipeline.ps1 -SkipIngest -Set sv1   # subtypes for one set only
```

Species metadata uses `--missing-only` by default (fast when adding sets). Full PokeAPI refresh:

```powershell
docker compose run --rm pipeline python pipeline/build_pokemon_species.py --skip-migration
```

Cursor command: **run-pokemon-pipeline** (`.cursor/commands/run-pokemon-pipeline.md`).

### Search syntax (Star Piece UI → Advanced → Search syntax)

pkmncards-style filters in the search box:

| Syntax | Example | Meaning |
|--------|---------|---------|
| `t:` | `t:trainer` | Category: Pokémon, Trainer, or Energy |
| `t:` | `t:supporter` | Trainer subtype (also `t:item`, `t:stadium`, `t:tool`) |
| `is:` | `is:team-plasma` | Pokémon subtype tag |
| `is:` | `is:gen5`, `is:legendary` | Generation or legendary/mythical |
| `is:` | `is:starter`, `is:baby`, `is:paradox` | Species groups (`eeveelution`, `fossil`, `ultra-beast`, `pseudo-legendary`, `regional`) |
| `is:` | `is:multicolor` | Two or more energy colors (printed type + attack costs + “Fire Energy” / `{R}` in rules text). Colorless is ignored unless the Pokémon is Colorless-type |
| `has:` | `has:ability`, `has:ability-any` | Ability-like text: `ability` (modern only), `ability-any` (all eras), also `poke-power`, `poke-body`, `pokemon-power`, `omega-trait` |
| `c:` / `color:` | `c:grass`, `c:r` | Pokémon energy color (letters: `g r w l p f d m y n c`) |
| `weakness:` / `weak:` | `weakness:l`, `weakness:fighting` | Weakness type |
| `resistance:` / `resist:` / `res:` | `resistance:f` | Resistance type |
| `retreat:` | `retreat:0`, `retreat:2` | Retreat cost (`0` = free / unset) |
| `set:` / `series:` | `set:me01`, `series:me` | Set or TCG block |
| `r:` | `r:ultra` | Rarity |
| `dex:` | `dex:591` | National Dex # |
| `stage:` | `stage:basic` | Evolution stage |
| `prize:` | `prize:2` | KO prize count (`1` / `2` / `3`; Radiant = 1, Mega Evolution Mega ex = 3) |

Combine with names: `t:trainer t:supporter Iono`. Advanced panel filters use the same fields.

## Credit price note

The CK API exposes `price_buy` (cash). Credit is computed as cash × 1.3, matching Card Kingdom’s standard store credit ratio used in your existing CSVs.
