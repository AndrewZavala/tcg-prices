#!/usr/bin/env python3
"""Load evolution chain metadata for type-based card sorting.

Uses PokeAPI evolution chains + card print types for highest-stage typing.
Run after build_pokemon_species.py (needs pokemon_species rows).

Examples:
  python build_pokemon_evolution.py
  python build_pokemon_evolution.py --from-cache
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import requests
from sqlalchemy import create_engine, text

from config import DATABASE_URL, HELPER_DIR, MIGRATIONS_DIR
from pokemon_evolution_sort import (
    assignments_for_paths,
    map_pokeapi_type,
    paths_from_evolution_chain,
)

POKEAPI_BASE = "https://pokeapi.co/api/v2"
USER_AGENT = "TCGPokemonCatalog/1.0"
REQUEST_DELAY_SEC = 0.08
CHAIN_CACHE = HELPER_DIR / "pokemon_evolution_chains.json"


def apply_migration(engine) -> None:
    mig = MIGRATIONS_DIR / "040_pokemon_evolution_sort.sql"
    if not mig.exists():
        raise FileNotFoundError(mig)
    with engine.begin() as conn:
        conn.execute(text(mig.read_text(encoding="utf-8")))


def fetch_json(session: requests.Session, url: str) -> dict[str, Any]:
    resp = session.get(url, timeout=60)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY_SEC)
    return resp.json()


def card_type_for_dex(conn, dex_id: int) -> str | None:
    row = conn.execute(
        text(
            """
            SELECT c.types[1] AS primary_type
            FROM pokemon_cards c
            WHERE c.category = 'Pokemon'
              AND c.dex_ids IS NOT NULL
              AND cardinality(c.dex_ids) > 0
              AND c.dex_ids[1] = :dex_id
              AND c.types IS NOT NULL
              AND cardinality(c.types) > 0
              AND c.name !~* '[δΔ]| delta'
            ORDER BY
              CASE c.stage
                WHEN 'Stage2' THEN 3
                WHEN 'Stage1' THEN 2
                WHEN 'Basic' THEN 1
                ELSE 0
              END DESC,
              c.id
            LIMIT 1
            """
        ),
        {"dex_id": dex_id},
    ).mappings().first()
    if row and row.get("primary_type"):
        return str(row["primary_type"])
    return None


def pokeapi_type_for_dex(session: requests.Session, dex_id: int) -> str | None:
    try:
        detail = fetch_json(session, f"{POKEAPI_BASE}/pokemon-species/{dex_id}")
        pokemon_url = (detail.get("varieties") or [{}])[0].get("pokemon", {}).get("url")
        if not pokemon_url:
            return None
        pokemon = fetch_json(session, pokemon_url)
        types = pokemon.get("types") or []
        if not types:
            return None
        slot1 = next((t for t in types if t.get("slot") == 1), types[0])
        return map_pokeapi_type((slot1.get("type") or {}).get("name"))
    except Exception:
        return None


def resolve_leaf_types(
    conn,
    session: requests.Session,
    leaf_dexes: set[int],
    *,
    use_api: bool,
) -> dict[int, str | None]:
    out: dict[int, str | None] = {}
    for dex_id in sorted(leaf_dexes):
        t = card_type_for_dex(conn, dex_id)
        if not t and use_api:
            t = pokeapi_type_for_dex(session, dex_id)
        out[dex_id] = t
    return out


def species_chain_urls(session: requests.Session, dex_ids: list[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for dex_id in dex_ids:
        detail = fetch_json(session, f"{POKEAPI_BASE}/pokemon-species/{dex_id}")
        url = (detail.get("evolution_chain") or {}).get("url")
        if url:
            out[dex_id] = url
    return out


def load_chain_cache() -> dict[str, dict[str, Any]]:
    if not CHAIN_CACHE.exists():
        return {}
    return json.loads(CHAIN_CACHE.read_text(encoding="utf-8"))


def save_chain_cache(cache: dict[str, dict[str, Any]]) -> None:
    HELPER_DIR.mkdir(parents=True, exist_ok=True)
    CHAIN_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def upsert_assignments(engine, rows: dict[int, dict[str, Any]]) -> int:
    if not rows:
        return 0
    sql = text(
        """
        UPDATE pokemon_species
        SET evolution_chain_id = :evolution_chain_id,
            chain_root_dex_id = :chain_root_dex_id,
            chain_stage_order = :chain_stage_order,
            chain_sort_type = :chain_sort_type,
            synced_at = NOW()
        WHERE dex_id = :dex_id
        """
    )
    with engine.begin() as conn:
        for dex_id, meta in rows.items():
            conn.execute(
                sql,
                {
                    "dex_id": dex_id,
                    **meta,
                },
            )
    return len(rows)


def build_assignments(
    engine,
    session: requests.Session,
    *,
    from_cache: bool,
    use_api: bool,
) -> dict[int, dict[str, Any]]:
    with engine.connect() as conn:
        dex_ids = [
            int(r[0])
            for r in conn.execute(text("SELECT dex_id FROM pokemon_species ORDER BY dex_id"))
        ]
    if not dex_ids:
        print("No pokemon_species rows — run build_pokemon_species.py first.")
        return {}

    cache = load_chain_cache() if from_cache else {}
    chain_urls: set[str] = set()

    if from_cache and cache:
        chain_urls = set(cache.keys())
    else:
        print(f"Resolving evolution chain URLs for {len(dex_ids)} species…")
        mapping = species_chain_urls(session, dex_ids)
        chain_urls = set(mapping.values())
        print(f"Found {len(chain_urls)} unique evolution chains.")

    all_assignments: dict[int, dict[str, Any]] = {}
    leaf_dexes: set[int] = set()

    for idx, chain_url in enumerate(sorted(chain_urls), start=1):
        chain_json = cache.get(chain_url)
        if chain_json is None:
            chain_json = fetch_json(session, chain_url)
            cache[chain_url] = chain_json
            if idx % 25 == 0:
                save_chain_cache(cache)
        chain_id = int(chain_json.get("id") or 0)
        paths = paths_from_evolution_chain(chain_json)
        for path in paths:
            if path:
                leaf_dexes.add(path[-1])

    if not from_cache or not CHAIN_CACHE.exists():
        save_chain_cache(cache)

    with engine.connect() as conn:
        leaf_types = resolve_leaf_types(conn, session, leaf_dexes, use_api=use_api)

    for chain_url in sorted(chain_urls):
        chain_json = cache[chain_url]
        chain_id = int(chain_json.get("id") or 0)
        paths = paths_from_evolution_chain(chain_json)
        merged = assignments_for_paths(paths, chain_id, leaf_types)
        all_assignments.update(merged)

    return all_assignments


def main() -> int:
    parser = argparse.ArgumentParser(description="Build evolution chain sort metadata")
    parser.add_argument("--skip-migration", action="store_true")
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="Use helper/pokemon_evolution_chains.json only (no chain HTTP)",
    )
    parser.add_argument(
        "--no-pokeapi-types",
        action="store_true",
        help="Do not fetch PokeAPI types when no card printing exists",
    )
    args = parser.parse_args()

    engine = create_engine(DATABASE_URL, future=True)
    if not args.skip_migration:
        print("Applying migration 040_pokemon_evolution_sort.sql…")
        apply_migration(engine)

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    assignments = build_assignments(
        engine,
        session,
        from_cache=args.from_cache,
        use_api=not args.no_pokeapi_types,
    )
    count = upsert_assignments(engine, assignments)
    print(f"Done — updated evolution sort metadata on {count} species.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
