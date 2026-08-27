#!/usr/bin/env python3
"""Import Stacks inventory into collection_cards.

Prefers repo-root inventory.csv (includes sold status) when present.
Falls back to Stacks/Batch*_export.csv files (all active).
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from config import DATABASE_URL, TCG_ROOT, ensure_dirs

sys.path.insert(0, str(TCG_ROOT / "web"))
from stacks_io import (  # noqa: E402
    clear_collection,
    insert_collection_rows,
    parse_stacks_csv,
)

STACKS_DIR = TCG_ROOT / "Stacks"
INVENTORY_CSV = TCG_ROOT / "inventory.csv"


def _ensure_schema(conn) -> None:
    mig = TCG_ROOT / "migrations" / "021_collection_cards.sql"
    if mig.is_file():
        conn.execute(text(mig.read_text(encoding="utf-8")))


def import_inventory(conn) -> int:
    rows = parse_stacks_csv(INVENTORY_CSV.read_bytes(), "inventory.csv")
    if not rows:
        print("inventory.csv has no rows with Scryfall ID")
        return 0
    clear_collection(conn)
    n = insert_collection_rows(conn, rows, "inventory.csv")
    sold = sum(1 for r in rows if r["status"] == "sold")
    active = sum(1 for r in rows if r["status"] == "active")
    print(
        f"  replaced collection from inventory.csv: "
        f"{len(rows)} rows ({active} active, {sold} sold), {n} inserted"
    )
    return n


def import_batch_files(conn) -> int:
    if not STACKS_DIR.is_dir():
        print(f"No Stacks folder at {STACKS_DIR}")
        return 0
    files = sorted(STACKS_DIR.glob("*.csv"))
    if not files:
        print(f"No CSV files in {STACKS_DIR}")
        return 0

    imported = 0
    skipped = 0
    inserted_total = 0
    for path in files:
        batch_file = path.name
        already = conn.execute(
            text("SELECT 1 FROM collection_import_files WHERE file_name = :n"),
            {"n": batch_file},
        ).scalar()
        if already:
            print(f"  skip (already imported): {batch_file}")
            skipped += 1
            continue
        try:
            rows = parse_stacks_csv(path.read_bytes(), batch_file)
        except ValueError as e:
            print(f"  error {batch_file}: {e}")
            continue
        if not rows:
            print(f"  skip (empty): {batch_file}")
            continue
        n = insert_collection_rows(conn, rows, batch_file)
        print(f"  imported {batch_file}: {len(rows)} rows, {n} new")
        imported += 1
        inserted_total += n

    print(f"\nDone: {imported} files imported, {skipped} skipped, {inserted_total} new cards")
    return inserted_total


def main() -> int:
    ensure_dirs()
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    with engine.begin() as conn:
        _ensure_schema(conn)
        if INVENTORY_CSV.is_file():
            print(f"Using consolidated inventory: {INVENTORY_CSV}")
            import_inventory(conn)
            return 0

        print(f"No inventory.csv at {INVENTORY_CSV}; falling back to Stacks/*.csv")
        if import_batch_files(conn) == 0 and not STACKS_DIR.is_dir():
            print("Create inventory.csv or Stacks/Batch*_export.csv, or upload via Sell List UI.")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
