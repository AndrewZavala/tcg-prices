#!/usr/bin/env python3
"""Load sealed opportunity rows into Postgres."""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text

from config import DATABASE_URL, MIGRATIONS_DIR

SEALED_COLUMNS = [
    "snapshot_date",
    "product_id",
    "ck_product_id",
    "name",
    "set_name",
    "tcg_name",
    "match_score",
    "ck_cash",
    "ck_max_qty",
    "lowest_price",
    "seller_price",
    "shipping_price",
    "seller",
    "seller_key",
    "order_qty",
    "profit_per_copy",
    "order_profit",
    "order_roi",
    "order_cost",
    "roi",
    "ck_url",
    "tcg_url",
]


def apply_migration(engine) -> None:
    migration = MIGRATIONS_DIR / "024_sealed_opportunities.sql"
    if migration.exists():
        with engine.begin() as conn:
            conn.execute(text(migration.read_text(encoding="utf-8")))


def _row_to_record(row: dict[str, Any], snapshot_date: date) -> dict[str, Any]:
    ck_max = row.get("ck_max_qty")
    return {
        "snapshot_date": snapshot_date,
        "product_id": str(row.get("product_id") or ""),
        "ck_product_id": str(row.get("ck_product_id") or ""),
        "name": str(row.get("name") or ""),
        "set_name": row.get("set_name") or "",
        "tcg_name": row.get("tcg_name") or "",
        "match_score": row.get("match_score"),
        "ck_cash": row.get("ck_cash"),
        "ck_max_qty": None if ck_max is None or pd.isna(ck_max) else int(float(ck_max)),
        "lowest_price": row.get("lowest_price"),
        "seller_price": row.get("seller_price"),
        "shipping_price": row.get("shipping_price"),
        "seller": row.get("seller") or "",
        "seller_key": row.get("seller_key") or "",
        "order_qty": row.get("order_qty"),
        "profit_per_copy": row.get("profit_per_copy"),
        "order_profit": row.get("order_profit"),
        "order_roi": row.get("order_roi"),
        "order_cost": row.get("order_cost"),
        "roi": row.get("roi"),
        "ck_url": row.get("ck_url") or "",
        "tcg_url": row.get("tcg_url") or "",
    }


def load_sealed_opportunities(
    rows: list[dict[str, Any]],
    *,
    snapshot_date: date | None = None,
    matched_count: int = 0,
    ck_buy_count: int = 0,
    database_url: str | None = None,
) -> int:
    """Replace sealed_opportunities for snapshot_date."""
    snap = snapshot_date or date.today()
    engine = create_engine(database_url or DATABASE_URL, pool_pre_ping=True)
    apply_migration(engine)

    records = [_row_to_record(r, snap) for r in rows]
    df = pd.DataFrame(records, columns=SEALED_COLUMNS) if records else pd.DataFrame(columns=SEALED_COLUMNS)

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM sealed_opportunities WHERE snapshot_date = :d"),
            {"d": snap},
        )
        conn.execute(
            text("DELETE FROM sealed_opportunities_snapshots WHERE snapshot_date = :d"),
            {"d": snap},
        )
        conn.execute(
            text(
                """
                INSERT INTO sealed_opportunities_snapshots
                    (snapshot_date, row_count, matched_count, ck_buy_count)
                VALUES (:d, :rows, :matched, :ck_buy)
                """
            ),
            {
                "d": snap,
                "rows": len(records),
                "matched": matched_count,
                "ck_buy": ck_buy_count,
            },
        )

    if not df.empty:
        df.to_sql("sealed_opportunities", engine, if_exists="append", index=False, method="multi")

    return len(records)


def main() -> int:
    print("Use export_sealed_opportunities.py to build and load sealed opportunities.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
