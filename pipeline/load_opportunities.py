#!/usr/bin/env python3
"""Load filtered opportunity rows into Postgres."""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text

from config import DATABASE_URL, MIGRATIONS_DIR

OPPORTUNITY_COLUMNS = [
    "snapshot_date",
    "product_id",
    "name",
    "set_name",
    "variant",
    "finish",
    "condition_display",
    "condition_raw",
    "ck_cash",
    "ck_adj",
    "ck_max_qty",
    "lowest_price",
    "seller_price",
    "shipping_price",
    "seller",
    "seller_key",
    "lowest_qty",
    "max_qty",
    "max_qty_price",
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
    migration = MIGRATIONS_DIR / "006_opportunities.sql"
    if migration.exists():
        with engine.begin() as conn:
            conn.execute(text(migration.read_text(encoding="utf-8")))


def _row_to_record(row: dict[str, Any], snapshot_date: date) -> dict[str, Any]:
    ck_max = row.get("ck_max_qty")
    return {
        "snapshot_date": snapshot_date,
        "product_id": str(row.get("product_id") or ""),
        "name": str(row.get("name") or ""),
        "set_name": row.get("set") or row.get("set_name") or "",
        "variant": row.get("variant") or "",
        "finish": row.get("finish") or "",
        "condition_display": row.get("condition") or "",
        "condition_raw": row.get("condition_raw") or "",
        "ck_cash": row.get("ck_cash"),
        "ck_adj": row.get("ck_adj"),
        "ck_max_qty": None if ck_max is None or pd.isna(ck_max) else int(float(ck_max)),
        "lowest_price": row.get("lowest_price"),
        "seller_price": row.get("seller_price"),
        "shipping_price": row.get("shipping_price"),
        "seller": row.get("seller") or "",
        "seller_key": row.get("seller_key") or "",
        "lowest_qty": row.get("lowest_qty"),
        "max_qty": row.get("max_qty"),
        "max_qty_price": row.get("max_qty_price"),
        "order_qty": row.get("order_qty"),
        "profit_per_copy": row.get("profit_per_copy"),
        "order_profit": row.get("order_profit"),
        "order_roi": row.get("order_roi"),
        "order_cost": row.get("order_cost"),
        "roi": row.get("roi"),
        "ck_url": row.get("ck_url") or "",
        "tcg_url": row.get("tcg_url") or "",
    }


def load_opportunities(
    rows: list[dict[str, Any]],
    *,
    snapshot_date: date | None = None,
    target_count: int = 0,
    ranked_count: int = 0,
    database_url: str | None = None,
) -> int:
    """Replace opportunities for snapshot_date with report rows."""
    if not rows:
        return 0

    snap = snapshot_date or date.today()
    engine = create_engine(database_url or DATABASE_URL, pool_pre_ping=True)
    apply_migration(engine)

    records = [_row_to_record(r, snap) for r in rows]
    df = pd.DataFrame(records)

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM opportunities WHERE snapshot_date = :d"),
            {"d": snap},
        )
        conn.execute(
            text("DELETE FROM opportunities_snapshots WHERE snapshot_date = :d"),
            {"d": snap},
        )
        conn.execute(
            text(
                """
                INSERT INTO opportunities_snapshots
                    (snapshot_date, row_count, target_count, ranked_count)
                VALUES (:d, :rows, :targets, :ranked)
                """
            ),
            {
                "d": snap,
                "rows": len(df),
                "targets": target_count,
                "ranked": ranked_count,
            },
        )

    df.to_sql("opportunities", engine, if_exists="append", index=False, method="multi")
    return len(df)


def main() -> int:
    import asyncio

    from export_opportunities import (
        SKIP_FETCH,
        USE_CACHED_ENRICHED,
        _filter_report_rows,
        build_export_rows,
        enrich,
        load_cached_enriched,
        targets_from_ranked,
    )
    from enrich_buylist import _latest_master_path
    from scrape_tcg_listings import read_listings_lookup
    from screen_candidates import select_opportunity_targets

    async def _build_rows():
        if USE_CACHED_ENRICHED:
            enriched = load_cached_enriched()
        else:
            master = _latest_master_path()
            print(f"Enriching {master}...")
            enriched = enrich(pd.read_csv(master, low_memory=False), include_listings=False)
        ranked = select_opportunity_targets(enriched)
        if ranked.empty:
            raise RuntimeError("No opportunity targets")
        targets = targets_from_ranked(ranked)
        if SKIP_FETCH:
            listings = read_listings_lookup()
        else:
            raise RuntimeError("Set OPPORTUNITY_SKIP_FETCH=1 for load-only runs")
        export_rows = build_export_rows(ranked, listings)
        report_rows = _filter_report_rows(export_rows)
        return report_rows, len(targets), len(ranked)

    report_rows, target_count, ranked_count = asyncio.run(_build_rows())
    n = load_opportunities(
        report_rows,
        target_count=target_count,
        ranked_count=ranked_count,
    )
    print(f"Loaded {n:,} opportunities into Postgres for {date.today().isoformat()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
