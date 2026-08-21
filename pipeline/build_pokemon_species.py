#!/usr/bin/env python3
"""Load Pokémon species metadata from PokeAPI (+ curated search groups).

Stores generation, legendary/mythical/baby, and species_groups such as
starter, fossil, paradox, ultra-beast, pseudo-legendary, eeveelution.

Examples:
  python build_pokemon_species.py
  python build_pokemon_species.py --skip-migration
  python build_pokemon_species.py --apply-groups
  python build_pokemon_species.py --missing-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from typing import Any

import requests
from sqlalchemy import create_engine, text

from config import DATABASE_URL, HELPER_DIR, MIGRATIONS_DIR

POKEAPI_BASE = "https://pokeapi.co/api/v2"
USER_AGENT = "TCGPokemonCatalog/1.0"
REQUEST_DELAY_SEC = 0.08
SPECIES_CACHE = HELPER_DIR / "pokemon_species.json"

_GEN_RE = re.compile(r"generation-([ivx]+)$")

# Curated national dex ids for TCG-relevant species groups.
# Regional forms are card-name based (Alolan/Galarian/…) — not stored here.
STARTER_DEX_IDS = frozenset(
    {
        *range(1, 10),
        *range(152, 161),
        *range(252, 261),
        *range(387, 396),
        *range(495, 504),
        *range(650, 659),
        *range(722, 731),
        *range(810, 819),
        *range(906, 915),
    }
)

FOSSIL_DEX_IDS = frozenset(
    {
        138,
        139,
        140,
        141,
        142,
        345,
        346,
        347,
        348,
        408,
        409,
        410,
        411,
        564,
        565,
        566,
        567,
        696,
        697,
        698,
        699,
        880,
        881,
        882,
        883,
    }
)

PSEUDO_LEGENDARY_DEX_IDS = frozenset(
    {
        *range(147, 150),
        *range(246, 249),
        *range(371, 374),
        *range(374, 377),
        *range(443, 446),
        *range(633, 636),
        *range(704, 707),
        *range(782, 785),
        *range(885, 888),
        *range(996, 999),
    }
)

ULTRA_BEAST_DEX_IDS = frozenset(
    {
        *range(793, 800),
        *range(803, 807),
    }
)

PARADOX_DEX_IDS = frozenset(
    {
        *range(984, 996),
        1005,
        1006,
        1007,
        1008,
        1009,
        1010,
        1020,
        1021,
        1022,
        1023,
    }
)

EEVEELUTION_DEX_IDS = frozenset({133, 134, 135, 136, 196, 197, 470, 471, 700})

# Fallback when PokeAPI is_baby is unavailable (cache migrate / apply-groups).
BABY_DEX_IDS = frozenset(
    {
        172,
        173,
        174,
        175,
        236,
        238,
        239,
        240,
        298,
        360,
        406,
        433,
        438,
        439,
        440,
        446,
        447,
        458,
        848,
    }
)

GROUP_SOURCES: tuple[tuple[str, frozenset[int]], ...] = (
    ("starter", STARTER_DEX_IDS),
    ("fossil", FOSSIL_DEX_IDS),
    ("pseudo-legendary", PSEUDO_LEGENDARY_DEX_IDS),
    ("ultra-beast", ULTRA_BEAST_DEX_IDS),
    ("paradox", PARADOX_DEX_IDS),
    ("eeveelution", EEVEELUTION_DEX_IDS),
)


def species_groups_for_dex(dex_id: int) -> list[str]:
    return [name for name, ids in GROUP_SOURCES if dex_id in ids]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def _generation_id(name: str) -> int:
    """generation-v -> 5, generation-ix -> 9."""
    m = _GEN_RE.search(name.lower())
    if not m:
        return 0
    roman = m.group(1)
    mapping = {
        "i": 1,
        "ii": 2,
        "iii": 3,
        "iv": 4,
        "v": 5,
        "vi": 6,
        "vii": 7,
        "viii": 8,
        "ix": 9,
    }
    return mapping.get(roman, 0)


def _generation_label(gen_id: int) -> str:
    labels = {
        1: "Generation I",
        2: "Generation II",
        3: "Generation III",
        4: "Generation IV",
        5: "Generation V",
        6: "Generation VI",
        7: "Generation VII",
        8: "Generation VIII",
        9: "Generation IX",
    }
    return labels.get(gen_id, f"Generation {gen_id}")


def apply_migration(engine) -> None:
    for name in ("028_pokemon_species.sql", "030_pokemon_species_groups.sql"):
        mig = MIGRATIONS_DIR / name
        if not mig.exists():
            raise FileNotFoundError(mig)
        with engine.begin() as conn:
            conn.execute(text(mig.read_text(encoding="utf-8")))


def fetch_all_species(session: requests.Session) -> list[dict[str, Any]]:
    url = f"{POKEAPI_BASE}/pokemon-species?limit=50"
    out: list[dict[str, Any]] = []
    while url:
        resp = session.get(url, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        out.extend(payload.get("results") or [])
        url = payload.get("next")
        time.sleep(REQUEST_DELAY_SEC)
    return out


def fetch_species_detail(session: requests.Session, url: str) -> dict[str, Any]:
    resp = session.get(url, timeout=60)
    resp.raise_for_status()
    return resp.json()


def annotate_species_row(row: dict[str, Any]) -> dict[str, Any]:
    """Ensure baby flag + curated groups on a species row."""
    dex_id = int(row["dex_id"])
    is_baby = bool(row.get("is_baby")) or dex_id in BABY_DEX_IDS
    out = dict(row)
    out["is_baby"] = is_baby
    out["species_groups"] = species_groups_for_dex(dex_id)
    return out


def normalize_species(detail: dict[str, Any]) -> dict[str, Any] | None:
    dex_id = detail.get("id")
    if not isinstance(dex_id, int) or dex_id <= 0:
        return None
    gen_name = (detail.get("generation") or {}).get("name") or ""
    gen_id = _generation_id(gen_name)
    if gen_id <= 0:
        return None
    english = next(
        (n["name"] for n in detail.get("names") or [] if n.get("language", {}).get("name") == "en"),
        detail.get("name"),
    )
    return annotate_species_row(
        {
            "dex_id": dex_id,
            "name": english or detail.get("name") or str(dex_id),
            "generation_id": gen_id,
            "generation_name": _generation_label(gen_id),
            "is_legendary": bool(detail.get("is_legendary")),
            "is_mythical": bool(detail.get("is_mythical")),
            "is_baby": bool(detail.get("is_baby")),
        }
    )


def upsert_species(engine, rows: list[dict[str, Any]]) -> int:
    sql = text(
        """
        INSERT INTO pokemon_species (
            dex_id, name, generation_id, generation_name,
            is_legendary, is_mythical, is_baby, species_groups, synced_at
        ) VALUES (
            :dex_id, :name, :generation_id, :generation_name,
            :is_legendary, :is_mythical, :is_baby, :species_groups, NOW()
        )
        ON CONFLICT (dex_id) DO UPDATE SET
            name = EXCLUDED.name,
            generation_id = EXCLUDED.generation_id,
            generation_name = EXCLUDED.generation_name,
            is_legendary = EXCLUDED.is_legendary,
            is_mythical = EXCLUDED.is_mythical,
            is_baby = EXCLUDED.is_baby,
            species_groups = EXCLUDED.species_groups,
            synced_at = NOW()
        """
    )
    with engine.begin() as conn:
        for row in rows:
            annotated = annotate_species_row(row)
            conn.execute(
                sql,
                {
                    **annotated,
                    "species_groups": annotated["species_groups"],
                },
            )
    return len(rows)


def apply_groups_to_existing(engine) -> int:
    """Recompute is_baby + species_groups for rows already in the DB (no API)."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT dex_id, name, generation_id, generation_name,
                       is_legendary, is_mythical, COALESCE(is_baby, FALSE) AS is_baby
                FROM pokemon_species
                ORDER BY dex_id
                """
            )
        ).mappings().all()
    if not rows:
        print("No species rows to update.")
        return 0
    return upsert_species(engine, [dict(r) for r in rows])


def missing_dex_ids(engine) -> list[int]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    """
                    SELECT DISTINCT c.dex_ids[1] AS dex_id
                    FROM pokemon_cards c
                    LEFT JOIN pokemon_species ps ON ps.dex_id = c.dex_ids[1]
                    WHERE c.dex_ids IS NOT NULL
                      AND cardinality(c.dex_ids) > 0
                      AND ps.dex_id IS NULL
                    ORDER BY dex_id
                    """
                )
            ).scalars()
        )


def merge_species_cache(rows: list[dict[str, Any]]) -> None:
    existing: dict[int, dict[str, Any]] = {}
    if SPECIES_CACHE.exists():
        for item in json.loads(SPECIES_CACHE.read_text(encoding="utf-8")):
            existing[item["dex_id"]] = item
    for row in rows:
        existing[row["dex_id"]] = annotate_species_row(row)
    merged = [existing[k] for k in sorted(existing)]
    HELPER_DIR.mkdir(parents=True, exist_ok=True)
    SPECIES_CACHE.write_text(json.dumps(merged, indent=2), encoding="utf-8")


def fetch_species_for_dex_ids(session: requests.Session, dex_ids: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, dex_id in enumerate(dex_ids, start=1):
        detail = fetch_species_detail(session, f"{POKEAPI_BASE}/pokemon-species/{dex_id}")
        row = normalize_species(detail)
        if row:
            rows.append(row)
        if i % 25 == 0 or i == len(dex_ids):
            print(f"  fetched {i}/{len(dex_ids)}")
        time.sleep(REQUEST_DELAY_SEC)
    return rows


def enrich_missing_species(engine, session: requests.Session) -> int:
    dex_ids = missing_dex_ids(engine)
    if not dex_ids:
        print("Species metadata already complete for loaded dex ids.")
        return 0
    print(f"Fetching {len(dex_ids)} missing species from PokeAPI...")
    rows = fetch_species_for_dex_ids(session, dex_ids)
    if rows:
        merge_species_cache(rows)
        print(f"Updated cache {SPECIES_CACHE}")
    return upsert_species(engine, rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Load Pokémon species metadata from PokeAPI")
    parser.add_argument("--skip-migration", action="store_true")
    parser.add_argument("--from-cache", action="store_true", help="Load helper/pokemon_species.json only")
    parser.add_argument(
        "--apply-groups",
        action="store_true",
        help="Recompute is_baby + species_groups on existing DB rows (no API)",
    )
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Fetch only dex ids present on cards but missing from pokemon_species",
    )
    args = parser.parse_args()

    engine = create_engine(DATABASE_URL, future=True)
    if not args.skip_migration:
        print("Applying pokemon species migrations...")
        apply_migration(engine)

    if args.apply_groups:
        count = apply_groups_to_existing(engine)
        print(f"Done — refreshed groups on {count} species.")
        return 0

    if args.missing_only:
        session = _session()
        count = enrich_missing_species(engine, session)
        # Always refresh groups on the full table so curated lists stay current.
        apply_groups_to_existing(engine)
        print(f"Done — upserted {count} missing species.")
        return 0

    if args.from_cache:
        if not SPECIES_CACHE.exists():
            print(f"Cache not found: {SPECIES_CACHE}", file=sys.stderr)
            return 1
        rows = [annotate_species_row(r) for r in json.loads(SPECIES_CACHE.read_text(encoding="utf-8"))]
        merge_species_cache(rows)
        upsert_species(engine, rows)
        print(f"Loaded {len(rows)} species from cache.")
        return 0

    session = _session()
    print("Listing species from PokeAPI...")
    listing = fetch_all_species(session)
    print(f"Fetching details for {len(listing)} species...")

    rows: list[dict[str, Any]] = []
    for i, item in enumerate(listing, start=1):
        detail = fetch_species_detail(session, item["url"])
        row = normalize_species(detail)
        if row:
            rows.append(row)
        if i % 100 == 0 or i == len(listing):
            print(f"  fetched {i}/{len(listing)}")
        time.sleep(REQUEST_DELAY_SEC)

    HELPER_DIR.mkdir(parents=True, exist_ok=True)
    SPECIES_CACHE.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote cache {SPECIES_CACHE}")

    count = upsert_species(engine, rows)
    legendaries = sum(1 for r in rows if r["is_legendary"])
    mythicals = sum(1 for r in rows if r["is_mythical"])
    babies = sum(1 for r in rows if r["is_baby"])
    print(
        f"Done — upserted {count} species "
        f"({legendaries} legendary, {mythicals} mythical, {babies} baby)."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
