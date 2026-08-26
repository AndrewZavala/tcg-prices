#!/usr/bin/env python3
"""Post-ingest enrichment for the Pokémon catalog (Star Piece).

Runs after refresh_tcgdex.py:
  1. Apply pokemon migrations (025–028)
  2. Subtypes from pokemontcg.io (per set)
  3. Species metadata from PokeAPI (missing dex ids only, or full refresh)
  4. Oracle + illustration groupings

Examples:
  python enrich_pokemon.py
  python enrich_pokemon.py --set sv1 --set sv2
  python enrich_pokemon.py --skip-subtypes --species-full
  refresh_tcgdex.py --set sv1 --enrich
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from config import DATABASE_URL, MIGRATIONS_DIR

PIPELINE_DIR = Path(__file__).resolve().parent
POKEMON_MIGRATIONS = (
    "025_pokemon_catalog.sql",
    "026_pokemon_oracle.sql",
    "027_pokemon_subtypes.sql",
    "028_pokemon_species.sql",
    "029_pokemon_tcgplayer.sql",
    "030_pokemon_species_groups.sql",
)


def apply_pokemon_migrations(engine) -> None:
    for name in POKEMON_MIGRATIONS:
        mig = MIGRATIONS_DIR / name
        if not mig.exists():
            raise FileNotFoundError(mig)
        with engine.begin() as conn:
            conn.execute(text(mig.read_text(encoding="utf-8")))


def _run_step(label: str, script: str, args: list[str]) -> None:
    cmd = [sys.executable, str(PIPELINE_DIR / script), *args]
    print(f"\n=== {label} ===")
    print(" ", " ".join(cmd))
    subprocess.run(cmd, check=True)


def run_enrich(
    *,
    set_ids: list[str] | None = None,
    skip_migration: bool = False,
    skip_subtypes: bool = False,
    skip_species: bool = False,
    species_full: bool = False,
    skip_oracle: bool = False,
) -> int:
    engine = create_engine(DATABASE_URL, future=True)
    if not skip_migration:
        print("Applying pokemon migrations (025–028)...")
        apply_pokemon_migrations(engine)

    common = ["--skip-migration"]

    if not skip_subtypes:
        subtype_args = [*common]
        if set_ids:
            for sid in set_ids:
                subtype_args.extend(["--set", sid])
        _run_step("Subtypes (pokemontcg.io)", "enrich_pokemon_subtypes.py", subtype_args)
    else:
        print("\n=== Subtypes — skipped ===")

    if not skip_species:
        if species_full:
            _run_step("Species (PokeAPI full refresh)", "build_pokemon_species.py", [*common])
        else:
            _run_step("Species (PokeAPI missing dex ids)", "build_pokemon_species.py", [*common, "--missing-only"])
    else:
        print("\n=== Species — skipped ===")

    if skip_oracle:
        if set_ids:
            oracle_args = [*common]
            for sid in set_ids:
                oracle_args.extend(["--set", sid])
            _run_step("Oracle (incremental)", "build_pokemon_oracle.py", oracle_args)
        else:
            print("\n=== Oracle — skipped ===")
    elif set_ids:
        oracle_args = [*common]
        for sid in set_ids:
            oracle_args.extend(["--set", sid])
        _run_step("Oracle (incremental)", "build_pokemon_oracle.py", oracle_args)
    else:
        _run_step("Oracle groupings", "build_pokemon_oracle.py", common)

    print("\nPokémon enrichment complete.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich Pokémon catalog after TCGdex ingest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--set", action="append", dest="sets", metavar="ID", help="Limit subtype enrich to set(s)")
    parser.add_argument("--skip-migration", action="store_true", help="Skip applying 025–028 migrations")
    parser.add_argument("--skip-subtypes", action="store_true")
    parser.add_argument("--skip-species", action="store_true")
    parser.add_argument(
        "--species-full",
        action="store_true",
        help="Reload all species from PokeAPI (slow; use after cache update or quarterly)",
    )
    parser.add_argument("--skip-oracle", action="store_true")
    args = parser.parse_args()

    set_ids: list[str] | None = None
    if args.sets:
        seen: set[str] = set()
        set_ids = []
        for sid in args.sets:
            key = sid.lower()
            if key not in seen:
                seen.add(key)
                set_ids.append(key)

    return run_enrich(
        set_ids=set_ids,
        skip_migration=args.skip_migration,
        skip_subtypes=args.skip_subtypes,
        skip_species=args.skip_species,
        species_full=args.species_full,
        skip_oracle=args.skip_oracle,
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Enrichment step failed (exit {exc.returncode})", file=sys.stderr)
        sys.exit(exc.returncode)
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
