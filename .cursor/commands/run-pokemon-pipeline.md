---
description: Run the Star Piece Pokémon catalog pipeline (TCGdex ingest + subtypes, species, oracle enrich).
---

# Run Pokémon / Star Piece pipeline

Run ingest + enrichment for the Pokémon TCG catalog. Do not wait for extra confirmation unless Docker is down.

## What it does

1. **Ingest** — `refresh_tcgdex.py` (TCGdex → Postgres)
2. **Enrich** — `enrich_pokemon.py`:
   - Subtypes from pokemontcg.io (per ingested set)
   - Species metadata from PokeAPI (missing dex ids only)
   - Oracle + illustration groupings

## Steps

1. Ensure Docker is running (`docker info`).

2. **Full block ingest + enrich** (example: Black & White):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "pipeline\run_pokemon_pipeline.ps1" -Series bw
```

3. **Single set with enrich inline**:

```powershell
docker compose run --rm pipeline python pipeline/refresh_tcgdex.py --set sv1 --enrich
```

4. **Re-enrich only** (no TCGdex fetch — e.g. after API key added):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "pipeline\run_pokemon_pipeline.ps1" -SkipIngest
```

5. **Environment**: optional `POKEMONTCG_API_KEY` in `.env` for subtype enrichment rate limits (dev.pokemontcg.io).

6. On success, report: sets ingested, subtype match counts, species upserts, oracle counts. Site: `http://localhost:8000/pokemon`

Do not change pipeline code unless the user asked.
