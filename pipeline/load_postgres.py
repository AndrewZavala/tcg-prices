#!/usr/bin/env python3
"""Load enriched buylist CSV into Postgres."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from config import BUYLIST_ENRICHED_DIR, DATABASE_URL, MIGRATIONS_DIR, ensure_dirs

COLUMN_MAP = {
    "set": "set_name",
    "type": "card_type",
}


def apply_migrations(engine) -> None:
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        for name in (
            "001_schema.sql",
            "002_history_indexes.sql",
            "003_tcgcsv_prices.sql",
            "004_condition_prices.sql",
            "005_refresh_buylist_current_view.sql",
            "006_opportunities.sql",
        ):
            migration = MIGRATIONS_DIR / name
            if migration.exists():
                cur.execute(migration.read_text(encoding="utf-8"))
        raw.commit()
    finally:
        raw.close()


def _latest_enriched() -> Path:
    files = sorted(BUYLIST_ENRICHED_DIR.glob("full_ck_buylist_export_*.csv"))
    if not files:
        raise FileNotFoundError(f"No enriched exports in {BUYLIST_ENRICHED_DIR}")
    return files[-1]


def load_csv(path: Path, engine, source: str = "api") -> int:
    df = pd.read_csv(path, low_memory=False)
    snapshot_date = date.today()
    if "snapshot_date" in df.columns and df["snapshot_date"].notna().any():
        snapshot_date = pd.to_datetime(df["snapshot_date"].iloc[0]).date()

    df = df.rename(columns=COLUMN_MAP)
    db_cols = [
        "snapshot_date",
        "product_id",
        "name",
        "set_name",
        "collector_number",
        "finish",
        "cash_price",
        "credit_price",
        "max_qty",
        "slug",
        "rarity_bucket",
        "card_type",
        "source_file",
        "clean_set",
        "set_code",
        "scryfall_collector_number",
        "scryfall_id",
        "tcgplayer_id",
        "tcgplayer_etched_id",
        "usd",
        "usd_foil",
        "usd_etched",
        "tcg_market",
        "tcg_low",
        "tcg_mid",
        "tcg_buy_price",
        "tcg_listing_condition",
        "ck_cash_adjusted",
        "condition_multiplier",
        "sku",
        "variation",
    ]
    for col in db_cols:
        if col not in df.columns:
            df[col] = None

    df["snapshot_date"] = snapshot_date
    df["product_id"] = df["product_id"].astype(str)
    load_df = df[db_cols].copy()

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM buylist_cards WHERE snapshot_date = :d"),
            {"d": snapshot_date},
        )
        conn.execute(
            text("DELETE FROM buylist_snapshots WHERE snapshot_date = :d"),
            {"d": snapshot_date},
        )
        conn.execute(
            text(
                """
                INSERT INTO buylist_snapshots (snapshot_date, row_count, source)
                VALUES (:d, :n, :s)
                """
            ),
            {"d": snapshot_date, "n": len(load_df), "s": source},
        )

    load_df.to_sql(
        "buylist_cards",
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=5000,
    )
    return len(load_df)


def main() -> int:
    ensure_dirs()
    path = _latest_enriched()
    print(f"Loading {path} into Postgres...")
    engine = create_engine(DATABASE_URL)
    apply_migrations(engine)
    n = load_csv(path, engine)
    print(f"Loaded {n} rows for snapshot {date.today()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
