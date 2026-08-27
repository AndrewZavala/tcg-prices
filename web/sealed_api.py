"""API routes for sealed-product opportunities."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter(tags=["sealed-opportunities"])

_engine = None

SEALED_SORT = {
    "profit_desc": "order_profit DESC NULLS LAST, ck_cash DESC NULLS LAST, name",
    "profit_asc": "order_profit ASC NULLS LAST, name",
    "roi_desc": "order_roi DESC NULLS LAST, order_profit DESC NULLS LAST",
    "roi_asc": "order_roi ASC NULLS LAST, order_profit ASC NULLS LAST, name",
    "ck_desc": "ck_cash DESC NULLS LAST, name",
    "name": "name, set_name",
}


class SealedOpportunitiesMetaResponse(BaseModel):
    snapshot_date: str | None
    row_count: int | None
    matched_count: int | None
    ck_buy_count: int | None


def init_sealed_api(engine) -> None:
    global _engine
    _engine = engine


@router.get("/api/sealed-opportunities/meta", response_model=SealedOpportunitiesMetaResponse)
def get_sealed_opportunities_meta() -> SealedOpportunitiesMetaResponse:
    assert _engine is not None
    with _engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT snapshot_date::text, row_count, matched_count, ck_buy_count
                FROM sealed_opportunities_snapshots
                ORDER BY snapshot_date DESC
                LIMIT 1
                """
            )
        ).mappings().first()
    if not row:
        return SealedOpportunitiesMetaResponse(
            snapshot_date=None, row_count=None, matched_count=None, ck_buy_count=None
        )
    return SealedOpportunitiesMetaResponse(**row)


@router.get("/api/sealed-opportunities")
def list_sealed_opportunities(
    q: str = Query("", description="Product name search"),
    min_profit: float | None = Query(None, description="Minimum order_profit"),
    min_roi: float | None = Query(None, description="Minimum order_roi"),
    snapshot_date: str = Query("", description="YYYY-MM-DD; default latest"),
    sort: str = Query(
        "profit_desc",
        description="profit_desc, profit_asc, roi_desc, roi_asc, ck_desc, name",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Read filtered sealed opportunity rows (latest snapshot by default)."""
    assert _engine is not None
    clauses = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if snapshot_date.strip():
        clauses.append("snapshot_date = :snapshot_date")
        params["snapshot_date"] = snapshot_date.strip()
    else:
        clauses.append(
            "snapshot_date = (SELECT MAX(snapshot_date) FROM sealed_opportunities_snapshots)"
        )

    if q.strip():
        clauses.append("(name ILIKE :q OR tcg_name ILIKE :q OR set_name ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    if min_profit is not None:
        clauses.append("order_profit >= :min_profit")
        params["min_profit"] = min_profit
    if min_roi is not None:
        clauses.append("order_roi >= :min_roi")
        params["min_roi"] = min_roi

    where_sql = " AND ".join(clauses)
    order_by = SEALED_SORT.get(sort, SEALED_SORT["profit_desc"])
    sql = f"""
        SELECT id, snapshot_date::text AS snapshot_date, product_id, ck_product_id,
               name, set_name, tcg_name, match_score,
               ck_cash, ck_max_qty, lowest_price, seller_price, shipping_price,
               seller, seller_key, order_qty,
               profit_per_copy, order_profit, order_roi, order_cost, roi,
               ck_url, tcg_url
        FROM sealed_opportunities
        WHERE {where_sql}
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
    """
    count_sql = f"SELECT COUNT(*) AS n FROM sealed_opportunities WHERE {where_sql}"

    with _engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        total = conn.execute(text(count_sql), params).scalar() or 0
        snap = None
        if rows:
            snap = rows[0]["snapshot_date"]
        elif not snapshot_date.strip():
            snap_row = conn.execute(
                text(
                    "SELECT MAX(snapshot_date)::text AS d FROM sealed_opportunities_snapshots"
                )
            ).mappings().first()
            snap = snap_row["d"] if snap_row else None

    float_cols = (
        "match_score", "ck_cash", "lowest_price", "seller_price", "shipping_price",
        "profit_per_copy", "order_profit", "order_roi", "order_cost", "roi",
    )
    results = []
    for r in rows:
        row = dict(r)
        for key in float_cols:
            if row.get(key) is not None:
                row[key] = float(row[key])
        for key in ("order_qty", "ck_max_qty", "id"):
            if row.get(key) is not None:
                row[key] = int(row[key])
        results.append(row)

    return {
        "snapshot_date": snap,
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "results": results,
    }
