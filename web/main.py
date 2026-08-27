"""FastAPI buylist API, collection matching, and price history."""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from opportunity_sellers import SELLER_SORT_KEYS, SELLER_TOP_N, build_seller_summary
from inventory_api import init_inventory_api, router as inventory_router
from data_api import init_data_api, router as data_router
from collection_api import init_collection_api, router as collection_router
from sealed_api import init_sealed_api, router as sealed_router
from pokemon_api import init_pokemon_api, router as pokemon_router

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://tcg:tcg_secret@localhost:5432/tcg_buylist",
)
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:8000").split(",")

app = FastAPI(title="Manifest Bread API", version="1.9.0")


class DevNoCacheMiddleware(BaseHTTPMiddleware):
    """Avoid stale HTML/JS/CSS while iterating on the GUI locally."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/") or path in (
            "/",
            "/opportunities",
            "/inventory",
            "/returns",
            "/sell-list",
            "/match",
            "/charts",
            "/data",
            "/architecture",
            "/architecture/model",
            "/pokemon",
            "/star-piece",
        ):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(DevNoCacheMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
init_inventory_api(engine)
init_data_api(engine)
init_collection_api(engine)
init_sealed_api(engine)
init_pokemon_api(engine)
app.include_router(inventory_router)
app.include_router(data_router)
app.include_router(collection_router)
app.include_router(sealed_router)
app.include_router(pokemon_router)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class MetaResponse(BaseModel):
    snapshot_date: str | None
    row_count: int | None
    source: str | None
    snapshot_count: int | None = None


CK_CASH_EXPR = "COALESCE(ck_cash_adjusted, cash_price)"

TCG_FALLBACK_EXPR = f"""
    CASE
      WHEN tcg_low IS NOT NULL AND tcg_market IS NOT NULL THEN
        CASE
          WHEN ABS({CK_CASH_EXPR} - tcg_low) <= ABS({CK_CASH_EXPR} - tcg_market) THEN tcg_low
          ELSE tcg_market
        END
      ELSE COALESCE(tcg_low, tcg_market)
    END
"""

TCG_BUY_EXPR = f"COALESCE(tcg_buy_price, ({TCG_FALLBACK_EXPR}))"

PCT_DIFF_EXPR = f"""
    CASE
      WHEN ({TCG_BUY_EXPR}) > 0 AND {CK_CASH_EXPR} IS NOT NULL THEN
        ROUND(
          (({CK_CASH_EXPR} - ({TCG_BUY_EXPR})) / ({TCG_BUY_EXPR}) * 100)::numeric,
          2
        )
      ELSE NULL
    END
"""

SORT_OPTIONS = {
    "pct_diff_desc": "pct_diff DESC NULLS LAST, cash_price DESC NULLS LAST, name",
    "pct_diff_asc": "pct_diff ASC NULLS LAST, name",
    "cash_desc": "cash_price DESC NULLS LAST, name",
    "name": "name",
}


def _apply_migration_002(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "002_history_indexes.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_003(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "003_tcgcsv_prices.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_004(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "004_condition_prices.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_005(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "005_refresh_buylist_current_view.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_006(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "006_opportunities.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_007(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "007_purchases.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_008(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "008_purchases_linking.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_009(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "009_inventory.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_010(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "010_inventory_reporting.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_011(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "011_inventory_ck_price_delta.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_012(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "012_inventory_tcg_product_id.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_013(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "013_inventory_dedup_seller.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_014(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "014_inventory_ordered_at.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_015(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "015_fulfillment_packed.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_016(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "016_inventory_ck_cash_expected.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_017(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "017_strip_tcg_url_sellers.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_018(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "018_inventory_qty_fulfilled_statuses.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_019(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "019_reserve_planned_qty.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_020(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "020_inventory_problem_status.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_021(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "021_collection_cards.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_022(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "022_lock_fulfillment_ck_adj.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_023(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "023_collection_keep.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_024(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "024_sealed_opportunities.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_025(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "025_pokemon_catalog.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_026(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "026_pokemon_oracle.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_029(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "029_pokemon_tcgplayer.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


def _apply_migration_030(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "030_pokemon_species_groups.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


@app.on_event("startup")
def startup_migrations() -> None:
    try:
        with engine.begin() as conn:
            _apply_migration_002(conn)
            _apply_migration_003(conn)
            _apply_migration_004(conn)
            _apply_migration_005(conn)
            _apply_migration_006(conn)
            _apply_migration_007(conn)
            _apply_migration_008(conn)
            _apply_migration_009(conn)
            _apply_migration_010(conn)
            _apply_migration_011(conn)
            _apply_migration_012(conn)
            _apply_migration_013(conn)
            _apply_migration_014(conn)
            _apply_migration_015(conn)
            _apply_migration_016(conn)
            _apply_migration_017(conn)
            _apply_migration_018(conn)
            _apply_migration_019(conn)
            _apply_migration_020(conn)
            _apply_migration_021(conn)
            _apply_migration_022(conn)
            _apply_migration_023(conn)
            _apply_migration_024(conn)
            _apply_migration_025(conn)
            _apply_migration_026(conn)
            _apply_migration_029(conn)
            _apply_migration_030(conn)
    except Exception:
        pass  # indexes/columns may already exist


@app.get("/api/meta", response_model=MetaResponse)
def get_meta() -> MetaResponse:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT snapshot_date::text, row_count, source
                FROM buylist_snapshots
                ORDER BY snapshot_date DESC
                LIMIT 1
                """
            )
        ).mappings().first()
        snap_count = conn.execute(
            text("SELECT COUNT(*) FROM buylist_snapshots")
        ).scalar()
    if not row:
        return MetaResponse(snapshot_date=None, row_count=None, source=None, snapshot_count=0)
    return MetaResponse(**row, snapshot_count=snap_count)


class OpportunitiesMetaResponse(BaseModel):
    snapshot_date: str | None
    row_count: int | None
    target_count: int | None
    ranked_count: int | None


OPPORTUNITY_SORT = {
    "profit_desc": "order_profit DESC NULLS LAST, ck_cash DESC NULLS LAST, name",
    "profit_asc": "order_profit ASC NULLS LAST, name",
    "roi_desc": "order_roi DESC NULLS LAST, order_profit DESC NULLS LAST",
    "roi_asc": "order_roi ASC NULLS LAST, order_profit ASC NULLS LAST, name",
    "ck_desc": "ck_cash DESC NULLS LAST, name",
    "name": "name, set_name",
}


def _opportunity_snapshot_clause(snapshot_date: str) -> tuple[str, dict[str, Any]]:
    if snapshot_date.strip():
        return "snapshot_date = :snapshot_date", {"snapshot_date": snapshot_date.strip()}
    return (
        "snapshot_date = (SELECT MAX(snapshot_date) FROM opportunities_snapshots)",
        {},
    )


def _fetch_opportunity_rows(conn, snapshot_date: str = "") -> list[dict[str, Any]]:
    snap_clause, snap_params = _opportunity_snapshot_clause(snapshot_date)
    sql = f"""
        SELECT id, snapshot_date::text AS snapshot_date, product_id, name, set_name,
               variant, finish, condition_display, condition_raw,
               ck_cash, ck_adj, ck_max_qty, lowest_price, seller_price, shipping_price,
               seller, seller_key, lowest_qty, max_qty, max_qty_price, order_qty,
               profit_per_copy, order_profit, order_roi, order_cost, roi,
               ck_url, tcg_url
        FROM opportunities
        WHERE {snap_clause}
    """
    rows = conn.execute(text(sql), snap_params).mappings().all()
    float_cols = (
        "ck_cash", "ck_adj", "lowest_price", "seller_price", "shipping_price",
        "max_qty_price", "profit_per_copy", "order_profit", "order_roi", "order_cost", "roi",
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        for key in float_cols:
            if row.get(key) is not None:
                row[key] = float(row[key])
        for key in ("lowest_qty", "max_qty", "order_qty", "ck_max_qty", "id"):
            if row.get(key) is not None:
                row[key] = int(row[key])
        out.append(row)
    return out


@app.get("/api/opportunities/meta", response_model=OpportunitiesMetaResponse)
def get_opportunities_meta() -> OpportunitiesMetaResponse:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT snapshot_date::text, row_count, target_count, ranked_count
                FROM opportunities_snapshots
                ORDER BY snapshot_date DESC
                LIMIT 1
                """
            )
        ).mappings().first()
    if not row:
        return OpportunitiesMetaResponse(
            snapshot_date=None, row_count=None, target_count=None, ranked_count=None
        )
    return OpportunitiesMetaResponse(**row)


@app.get("/api/opportunities")
def list_opportunities(
    q: str = Query("", description="Card name search"),
    seller: str = Query("", description="Seller name contains"),
    seller_key: str = Query("", description="Exact seller_key"),
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
    """Read filtered rows from opportunities (latest snapshot by default)."""
    clauses = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if snapshot_date.strip():
        clauses.append("snapshot_date = :snapshot_date")
        params["snapshot_date"] = snapshot_date.strip()
    else:
        clauses.append(
            "snapshot_date = (SELECT MAX(snapshot_date) FROM opportunities_snapshots)"
        )

    if q.strip():
        clauses.append("name ILIKE :q")
        params["q"] = f"%{q.strip()}%"
    if seller.strip():
        clauses.append("seller ILIKE :seller")
        params["seller"] = f"%{seller.strip()}%"
    if seller_key.strip():
        clauses.append("seller_key = :seller_key")
        params["seller_key"] = seller_key.strip()
    if min_profit is not None:
        clauses.append("order_profit >= :min_profit")
        params["min_profit"] = min_profit
    if min_roi is not None:
        clauses.append("order_roi >= :min_roi")
        params["min_roi"] = min_roi

    where_sql = " AND ".join(clauses)
    order_by = OPPORTUNITY_SORT.get(sort, OPPORTUNITY_SORT["profit_desc"])
    sql = f"""
        SELECT id, snapshot_date::text AS snapshot_date, product_id, name, set_name,
               variant, finish, condition_display, condition_raw,
               ck_cash, ck_adj, ck_max_qty, lowest_price, seller_price, shipping_price,
               seller, seller_key, lowest_qty, max_qty, max_qty_price, order_qty,
               profit_per_copy, order_profit, order_roi, order_cost, roi,
               ck_url, tcg_url
        FROM opportunities
        WHERE {where_sql}
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
    """
    count_sql = f"SELECT COUNT(*) AS n FROM opportunities WHERE {where_sql}"

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        total = conn.execute(text(count_sql), params).scalar() or 0
        snap = None
        if rows:
            snap = rows[0]["snapshot_date"]
        elif not snapshot_date.strip():
            snap_row = conn.execute(
                text("SELECT MAX(snapshot_date)::text AS d FROM opportunities_snapshots")
            ).mappings().first()
            snap = snap_row["d"] if snap_row else None

    float_cols = (
        "ck_cash", "ck_adj", "lowest_price", "seller_price", "shipping_price",
        "max_qty_price", "profit_per_copy", "order_profit", "order_roi", "order_cost", "roi",
    )
    results = []
    for r in rows:
        row = dict(r)
        for key in float_cols:
            if row.get(key) is not None:
                row[key] = float(row[key])
        for key in ("lowest_qty", "max_qty", "order_qty", "ck_max_qty", "id"):
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


@app.get("/api/opportunities/sellers")
def list_opportunity_sellers(
    q: str = Query("", description="Search seller or card name in buy list"),
    snapshot_date: str = Query("", description="YYYY-MM-DD; default latest"),
    sort: str = Query(
        "profit_desc",
        description="profit_desc, profit_asc, roi_desc, roi_asc, name, cards_desc, cost_desc",
    ),
    limit: int = Query(SELLER_TOP_N, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Per-seller batched orders aggregated from the latest opportunities snapshot."""
    with engine.connect() as conn:
        rows = _fetch_opportunity_rows(conn, snapshot_date)
        snap = None
        if rows:
            snap = rows[0]["snapshot_date"]
        elif not snapshot_date.strip():
            snap_row = conn.execute(
                text("SELECT MAX(snapshot_date)::text AS d FROM opportunities_snapshots")
            ).mappings().first()
            snap = snap_row["d"] if snap_row else None

    sellers = build_seller_summary(rows, top_n=None, q=q)
    sort_key = SELLER_SORT_KEYS.get(sort, SELLER_SORT_KEYS["profit_desc"])
    sellers.sort(key=sort_key)
    total = len(sellers)
    page = sellers[offset : offset + limit]

    return {
        "snapshot_date": snap,
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "results": page,
    }


PURCHASE_STATUSES = ("planned", "ordered", "shipped", "at_ck", "paid", "cancelled")

PURCHASE_SORT = {
    "created_desc": "created_at DESC, id DESC",
    "profit_desc": "order_profit DESC NULLS LAST, created_at DESC",
    "status": "status, created_at DESC",
    "name": "name, created_at DESC",
}

PURCHASE_FLOAT_COLS = (
    "seller_price", "shipping_price", "ck_cash", "ck_adj",
    "profit_per_copy", "order_profit", "order_roi",
)


class PurchaseCreateItem(BaseModel):
    opportunity_id: int
    qty: int | None = None
    notes: str | None = None


class PurchaseBatchCreate(BaseModel):
    items: list[PurchaseCreateItem]


class PurchaseUpdate(BaseModel):
    status: str | None = None
    qty: int | None = None
    notes: str | None = None
    checkout_key: str | None = None
    tcg_order_id: str | None = None
    ck_batch_id: str | None = None
    name: str | None = None
    seller: str | None = None
    set_name: str | None = None
    finish: str | None = None
    condition: str | None = None
    seller_price: float | None = None
    shipping_price: float | None = None
    ck_cash: float | None = None
    ck_adj: float | None = None
    tcg_url: str | None = None
    ck_url: str | None = None


class PurchaseBatchLink(BaseModel):
    purchase_ids: list[int]
    checkout_key: str | None = None
    tcg_order_id: str | None = None
    ck_batch_id: str | None = None
    status: str | None = None


class PurchaseBatchDelete(BaseModel):
    purchase_ids: list[int]


class PurchaseSellerLink(BaseModel):
    seller: str
    tcg_order_id: str
    status: str | None = "ordered"
    only_unlinked: bool = True


class PurchaseManualCreate(BaseModel):
    name: str
    seller: str
    seller_price: float
    qty: int = 1
    set_name: str | None = None
    variant: str | None = None
    finish: str | None = "normal"
    condition: str | None = "Near Mint"
    shipping_price: float | None = None
    ck_cash: float | None = None
    ck_adj: float | None = None
    tcg_url: str | None = None
    ck_url: str | None = None
    seller_key: str | None = None
    product_id: str | None = None
    tcg_order_id: str | None = None
    notes: str | None = None
    status: str | None = "planned"


MANUAL_CONDITION_MULT: dict[str, float] = {
    "Near Mint": 1.0,
    "Lightly Played": 0.75,
    "Moderately Played": 0.5,
    "Heavily Played": 0.25,
    "Damaged": 0.0,
}


def _normalize_link_field(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_purchase_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if out.get("created_at") is not None:
        out["created_at"] = out["created_at"].isoformat()
    if out.get("updated_at") is not None:
        out["updated_at"] = out["updated_at"].isoformat()
    if out.get("snapshot_date") is not None:
        out["snapshot_date"] = str(out["snapshot_date"])
    for key in PURCHASE_FLOAT_COLS:
        if out.get(key) is not None:
            out[key] = float(out[key])
    for key in ("id", "qty", "order_qty", "opportunity_id"):
        if out.get(key) is not None:
            out[key] = int(out[key])
    return out


def _get_opportunity_by_id(conn, opportunity_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id, snapshot_date::text AS snapshot_date, product_id, name, set_name,
                   variant, finish, condition_display, condition_raw,
                   ck_cash, ck_adj, seller_price, shipping_price,
                   seller, seller_key, order_qty,
                   profit_per_copy, order_profit, order_roi,
                   ck_url, tcg_url
            FROM opportunities
            WHERE id = :id
            """
        ),
        {"id": opportunity_id},
    ).mappings().first()
    return dict(row) if row else None


def _active_purchase_exists(conn, opp: dict[str, Any]) -> bool:
    return _active_purchase_exists_for_keys(
        conn,
        opp["product_id"],
        opp.get("finish"),
        opp.get("condition_raw"),
        opp.get("seller_key"),
    )


def _active_purchase_exists_for_keys(
    conn,
    product_id: str,
    finish: str | None,
    condition_raw: str | None,
    seller_key: str | None,
) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT 1 FROM purchases
                WHERE product_id = :product_id
                  AND COALESCE(finish, '') = COALESCE(:finish, '')
                  AND COALESCE(condition_raw, '') = COALESCE(:condition_raw, '')
                  AND COALESCE(seller_key, '') = COALESCE(:seller_key, '')
                  AND status IN ('planned', 'ordered')
                LIMIT 1
                """
            ),
            {
                "product_id": product_id,
                "finish": finish,
                "condition_raw": condition_raw,
                "seller_key": seller_key,
            },
        ).scalar()
    )


def _parse_tcg_product_id(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"/product/(\d+)", url, re.I)
    return match.group(1) if match else None


def _parse_seller_key_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        qs = parse_qs(urlparse(url).query)
        sellers = qs.get("Sellers") or qs.get("sellers")
        if sellers and sellers[0].strip():
            return sellers[0].strip()
    except Exception:
        pass
    return None


def _manual_product_id(body: PurchaseManualCreate) -> str:
    if body.product_id and body.product_id.strip():
        return body.product_id.strip()
    from_url = _parse_tcg_product_id(body.tcg_url)
    if from_url:
        return from_url
    slug = re.sub(r"[^a-z0-9]+", "-", body.name.strip().lower())[:48].strip("-") or "card"
    seller_bit = re.sub(r"[^a-z0-9]+", "-", body.seller.strip().lower())[:24].strip("-") or "seller"
    return f"manual:{slug}:{seller_bit}"


def _recalc_purchase_economics(
    *,
    seller_price: float | None,
    shipping_price: float | None,
    ck_cash: float | None,
    ck_adj: float | None,
    condition_display: str | None,
    qty: int,
) -> dict[str, Any]:
    shipping = float(shipping_price or 0)
    adj = ck_adj
    if adj is None and ck_cash is not None:
        mult = MANUAL_CONDITION_MULT.get(condition_display or "Near Mint", 1.0)
        adj = round(float(ck_cash) * mult, 2)
    profit_per_copy = None
    order_profit = None
    order_roi = None
    if adj is not None and seller_price is not None:
        order_cost = float(seller_price) * qty + shipping
        order_profit = round(float(adj) * qty - order_cost, 2)
        profit_per_copy = round(float(adj) - float(seller_price), 2)
        order_roi = round(order_profit / order_cost * 100, 2) if order_cost > 0 else None
    return {
        "ck_adj": adj,
        "profit_per_copy": profit_per_copy,
        "order_profit": order_profit,
        "order_roi": order_roi,
        "shipping_price": round(shipping, 2) if shipping else None,
    }


def _manual_economics(body: PurchaseManualCreate, qty: int) -> dict[str, Any]:
    econ = _recalc_purchase_economics(
        seller_price=body.seller_price,
        shipping_price=body.shipping_price,
        ck_cash=body.ck_cash,
        ck_adj=body.ck_adj,
        condition_display=body.condition or "Near Mint",
        qty=qty,
    )
    return {
        "ck_cash": body.ck_cash,
        **econ,
    }


def _insert_purchase_record(conn, fields: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            INSERT INTO purchases (
                status, qty, opportunity_id, snapshot_date, product_id, name,
                set_name, variant, finish, condition_display, condition_raw,
                seller, seller_key, seller_price, shipping_price,
                ck_cash, ck_adj, order_qty, profit_per_copy, order_profit, order_roi,
                tcg_url, ck_url, notes, tcg_order_id, ck_batch_id, checkout_key
            ) VALUES (
                :status, :qty, :opportunity_id, :snapshot_date, :product_id, :name,
                :set_name, :variant, :finish, :condition_display, :condition_raw,
                :seller, :seller_key, :seller_price, :shipping_price,
                :ck_cash, :ck_adj, :order_qty, :profit_per_copy, :order_profit, :order_roi,
                :tcg_url, :ck_url, :notes, :tcg_order_id, :ck_batch_id, :checkout_key
            )
            RETURNING *
            """
        ),
        fields,
    ).mappings().first()
    return _normalize_purchase_row(dict(row))


def _insert_purchase(conn, opp: dict[str, Any], qty: int | None, notes: str | None) -> dict[str, Any]:
    use_qty = qty if qty is not None else int(opp.get("order_qty") or 1)
    if use_qty < 1:
        use_qty = 1
    return _insert_purchase_record(
        conn,
        {
            "status": "planned",
            "qty": use_qty,
            "opportunity_id": opp["id"],
            "snapshot_date": opp["snapshot_date"],
            "product_id": opp["product_id"],
            "name": opp["name"],
            "set_name": opp.get("set_name"),
            "variant": opp.get("variant"),
            "finish": opp.get("finish"),
            "condition_display": opp.get("condition_display"),
            "condition_raw": opp.get("condition_raw"),
            "seller": opp.get("seller"),
            "seller_key": opp.get("seller_key"),
            "seller_price": opp.get("seller_price"),
            "shipping_price": opp.get("shipping_price"),
            "ck_cash": opp.get("ck_cash"),
            "ck_adj": opp.get("ck_adj"),
            "order_qty": opp.get("order_qty"),
            "profit_per_copy": opp.get("profit_per_copy"),
            "order_profit": opp.get("order_profit"),
            "order_roi": opp.get("order_roi"),
            "tcg_url": opp.get("tcg_url"),
            "ck_url": opp.get("ck_url"),
            "notes": notes,
            "tcg_order_id": None,
            "ck_batch_id": None,
            "checkout_key": None,
        },
    )


def _create_purchase_from_opportunity(
    conn, opportunity_id: int, qty: int | None = None, notes: str | None = None
) -> dict[str, Any]:
    opp = _get_opportunity_by_id(conn, opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    if _active_purchase_exists(conn, opp):
        raise HTTPException(
            status_code=409,
            detail="Already in purchases queue (planned or ordered)",
        )
    return _insert_purchase(conn, opp, qty, notes)


# --- Legacy purchases API (deprecated; use /api/inventory) ---


@app.post("/api/purchases")
def create_purchase(item: PurchaseCreateItem) -> dict[str, Any]:
    """Add one opportunity row to the purchases queue."""
    with engine.begin() as conn:
        row = _create_purchase_from_opportunity(
            conn, item.opportunity_id, item.qty, item.notes
        )
    return row


@app.post("/api/purchases/batch")
def create_purchases_batch(body: PurchaseBatchCreate) -> dict[str, Any]:
    """Add multiple opportunity rows; skips duplicates."""
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    with engine.begin() as conn:
        for item in body.items:
            try:
                opp = _get_opportunity_by_id(conn, item.opportunity_id)
                if not opp:
                    errors.append(
                        {"opportunity_id": item.opportunity_id, "error": "not_found"}
                    )
                    continue
                if _active_purchase_exists(conn, opp):
                    skipped.append(
                        {
                            "opportunity_id": item.opportunity_id,
                            "name": opp.get("name"),
                            "reason": "already_queued",
                        }
                    )
                    continue
                created.append(_insert_purchase(conn, opp, item.qty, item.notes))
            except Exception as exc:
                errors.append(
                    {"opportunity_id": item.opportunity_id, "error": str(exc)}
                )

    return {"created": created, "skipped": skipped, "errors": errors}


@app.post("/api/purchases/manual")
def create_manual_purchase(body: PurchaseManualCreate) -> dict[str, Any]:
    """Add a purchase found outside the opportunities pipeline (e.g. spotted on TCGplayer)."""
    name = body.name.strip()
    seller = body.seller.strip()
    if not name or not seller:
        raise HTTPException(status_code=400, detail="name and seller are required")
    if body.seller_price <= 0:
        raise HTTPException(status_code=400, detail="seller_price must be > 0")

    qty = body.qty if body.qty and body.qty >= 1 else 1
    status = body.status or "planned"
    if status not in PURCHASE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    condition_raw = (body.condition or "Near Mint").strip()
    finish = (body.finish or "normal").strip().lower()
    seller_key = (body.seller_key or _parse_seller_key_from_url(body.tcg_url) or "").strip() or None
    product_id = _manual_product_id(body)
    economics = _manual_economics(body, qty)

    dedup_row = {
        "product_id": product_id,
        "finish": finish,
        "condition_raw": condition_raw,
        "seller_key": seller_key,
    }

    with engine.begin() as conn:
        if _active_purchase_exists_for_keys(
            conn,
            dedup_row["product_id"],
            dedup_row["finish"],
            dedup_row["condition_raw"],
            dedup_row["seller_key"],
        ):
            raise HTTPException(
                status_code=409,
                detail="Already in purchases queue (planned or ordered)",
            )
        row = _insert_purchase_record(
            conn,
            {
                "status": status,
                "qty": qty,
                "opportunity_id": None,
                "snapshot_date": date.today(),
                "product_id": product_id,
                "name": name,
                "set_name": body.set_name.strip() if body.set_name else None,
                "variant": body.variant.strip() if body.variant else None,
                "finish": finish,
                "condition_display": condition_raw,
                "condition_raw": condition_raw,
                "seller": seller,
                "seller_key": seller_key,
                "seller_price": round(float(body.seller_price), 2),
                "shipping_price": economics["shipping_price"],
                "ck_cash": economics["ck_cash"],
                "ck_adj": economics["ck_adj"],
                "order_qty": qty,
                "profit_per_copy": economics["profit_per_copy"],
                "order_profit": economics["order_profit"],
                "order_roi": economics["order_roi"],
                "tcg_url": body.tcg_url.strip() if body.tcg_url else None,
                "ck_url": body.ck_url.strip() if body.ck_url else None,
                "notes": body.notes.strip() if body.notes else None,
                "tcg_order_id": _normalize_link_field(body.tcg_order_id),
                "ck_batch_id": None,
                "checkout_key": None,
            },
        )
    return row


@app.get("/api/purchases")
def list_purchases(
    status: str = Query("", description="Filter by status"),
    seller: str = Query("", description="Seller name contains"),
    q: str = Query("", description="Card name search"),
    checkout_key: str = Query("", description="Exact checkout_key"),
    tcg_order_id: str = Query("", description="Exact tcg_order_id"),
    ck_batch_id: str = Query("", description="Exact ck_batch_id"),
    unlinked: bool = Query(False, description="Only rows missing tcg_order_id"),
    sort: str = Query("created_desc", description="created_desc, profit_desc, status, name"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    clauses = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if status.strip():
        if status.strip() not in PURCHASE_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        clauses.append("status = :status")
        params["status"] = status.strip()
    if seller.strip():
        clauses.append("seller ILIKE :seller")
        params["seller"] = f"%{seller.strip()}%"
    if q.strip():
        clauses.append("name ILIKE :q")
        params["q"] = f"%{q.strip()}%"
    if checkout_key.strip():
        clauses.append("checkout_key = :checkout_key")
        params["checkout_key"] = checkout_key.strip()
    if tcg_order_id.strip():
        clauses.append("tcg_order_id = :tcg_order_id")
        params["tcg_order_id"] = tcg_order_id.strip()
    if ck_batch_id.strip():
        clauses.append("ck_batch_id = :ck_batch_id")
        params["ck_batch_id"] = ck_batch_id.strip()
    if unlinked:
        clauses.append("tcg_order_id IS NULL")

    where_sql = " AND ".join(clauses)
    order_by = PURCHASE_SORT.get(sort, PURCHASE_SORT["created_desc"])
    sql = f"""
        SELECT * FROM purchases
        WHERE {where_sql}
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
    """
    count_sql = f"SELECT COUNT(*) AS n FROM purchases WHERE {where_sql}"

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        total = conn.execute(text(count_sql), params).scalar() or 0

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "results": [_normalize_purchase_row(dict(r)) for r in rows],
    }


@app.get("/api/purchases/linking-summary")
def purchases_linking_summary() -> dict[str, Any]:
    """Distinct checkout keys, TCG order ids, and CK batches for filters."""
    with engine.connect() as conn:
        unlinked = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM purchases
                WHERE tcg_order_id IS NULL AND status NOT IN ('paid', 'cancelled')
                """
            )
        ).scalar() or 0
        checkouts = conn.execute(
            text(
                """
                SELECT checkout_key, COUNT(*) AS n,
                       MIN(status) AS min_status,
                       MAX(created_at)::text AS last_created
                FROM purchases
                WHERE checkout_key IS NOT NULL
                GROUP BY checkout_key
                ORDER BY MAX(created_at) DESC
                LIMIT 100
                """
            )
        ).mappings().all()
        tcg_orders = conn.execute(
            text(
                """
                SELECT tcg_order_id, COUNT(*) AS n, MAX(seller) AS seller
                FROM purchases
                WHERE tcg_order_id IS NOT NULL
                GROUP BY tcg_order_id
                ORDER BY MAX(created_at) DESC
                LIMIT 100
                """
            )
        ).mappings().all()
        ck_batches = conn.execute(
            text(
                """
                SELECT ck_batch_id, COUNT(*) AS n,
                       SUM(order_profit) AS total_profit
                FROM purchases
                WHERE ck_batch_id IS NOT NULL
                GROUP BY ck_batch_id
                ORDER BY MAX(updated_at) DESC
                LIMIT 100
                """
            )
        ).mappings().all()

    return {
        "unlinked_active": int(unlinked),
        "checkout_keys": [
            {
                "checkout_key": r["checkout_key"],
                "count": int(r["n"]),
                "last_created": r["last_created"],
            }
            for r in checkouts
        ],
        "tcg_orders": [
            {
                "tcg_order_id": r["tcg_order_id"],
                "count": int(r["n"]),
                "seller": r["seller"],
            }
            for r in tcg_orders
        ],
        "ck_batches": [
            {
                "ck_batch_id": r["ck_batch_id"],
                "count": int(r["n"]),
                "total_profit": float(r["total_profit"]) if r["total_profit"] is not None else None,
            }
            for r in ck_batches
        ],
    }


@app.patch("/api/purchases/{purchase_id}")
def update_purchase(purchase_id: int, body: PurchaseUpdate) -> dict[str, Any]:
    fields_set = body.model_fields_set
    economics_fields = {"qty", "seller_price", "shipping_price", "ck_cash", "ck_adj", "condition"}

    with engine.begin() as conn:
        current = conn.execute(
            text("SELECT * FROM purchases WHERE id = :id"),
            {"id": purchase_id},
        ).mappings().first()
        if not current:
            raise HTTPException(status_code=404, detail="Purchase not found")

        merged = dict(current)
        updates: list[str] = []
        params: dict[str, Any] = {"id": purchase_id}

        if body.status is not None:
            if body.status not in PURCHASE_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid status")
            merged["status"] = body.status
            updates.append("status = :status")
            params["status"] = body.status

        if body.qty is not None:
            if body.qty < 1:
                raise HTTPException(status_code=400, detail="qty must be >= 1")
            merged["qty"] = body.qty

        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="name is required")
            merged["name"] = name
            updates.append("name = :name")
            params["name"] = name

        if body.seller is not None:
            seller = body.seller.strip()
            if not seller:
                raise HTTPException(status_code=400, detail="seller is required")
            merged["seller"] = seller
            updates.append("seller = :seller")
            params["seller"] = seller

        if "set_name" in fields_set:
            set_name = body.set_name.strip() if body.set_name else None
            merged["set_name"] = set_name
            updates.append("set_name = :set_name")
            params["set_name"] = set_name

        if body.finish is not None:
            finish = body.finish.strip().lower()
            merged["finish"] = finish
            updates.append("finish = :finish")
            params["finish"] = finish

        if "condition" in fields_set:
            condition = (body.condition or "Near Mint").strip()
            merged["condition_display"] = condition
            merged["condition_raw"] = condition
            updates.append("condition_display = :condition_display")
            updates.append("condition_raw = :condition_raw")
            params["condition_display"] = condition
            params["condition_raw"] = condition

        if "seller_price" in fields_set:
            if body.seller_price is None or body.seller_price <= 0:
                raise HTTPException(status_code=400, detail="seller_price must be > 0")
            merged["seller_price"] = round(float(body.seller_price), 2)
            updates.append("seller_price = :seller_price")
            params["seller_price"] = merged["seller_price"]

        if "shipping_price" in fields_set:
            shipping = round(float(body.shipping_price), 2) if body.shipping_price is not None else None
            merged["shipping_price"] = shipping
            updates.append("shipping_price = :shipping_price")
            params["shipping_price"] = shipping

        if "ck_cash" in fields_set:
            ck_cash = round(float(body.ck_cash), 2) if body.ck_cash is not None else None
            merged["ck_cash"] = ck_cash
            updates.append("ck_cash = :ck_cash")
            params["ck_cash"] = ck_cash

        if "ck_adj" in fields_set:
            ck_adj = round(float(body.ck_adj), 2) if body.ck_adj is not None else None
            merged["ck_adj"] = ck_adj
            updates.append("ck_adj = :ck_adj")
            params["ck_adj"] = ck_adj

        if "notes" in fields_set:
            notes = body.notes.strip() if body.notes else None
            merged["notes"] = notes
            updates.append("notes = :notes")
            params["notes"] = notes

        if "checkout_key" in fields_set:
            merged["checkout_key"] = _normalize_link_field(body.checkout_key)
            updates.append("checkout_key = :checkout_key")
            params["checkout_key"] = merged["checkout_key"]

        if "tcg_order_id" in fields_set:
            merged["tcg_order_id"] = _normalize_link_field(body.tcg_order_id)
            updates.append("tcg_order_id = :tcg_order_id")
            params["tcg_order_id"] = merged["tcg_order_id"]

        if "ck_batch_id" in fields_set:
            merged["ck_batch_id"] = _normalize_link_field(body.ck_batch_id)
            updates.append("ck_batch_id = :ck_batch_id")
            params["ck_batch_id"] = merged["ck_batch_id"]

        if "tcg_url" in fields_set:
            tcg_url = body.tcg_url.strip() if body.tcg_url else None
            merged["tcg_url"] = tcg_url
            updates.append("tcg_url = :tcg_url")
            params["tcg_url"] = tcg_url

        if "ck_url" in fields_set:
            ck_url = body.ck_url.strip() if body.ck_url else None
            merged["ck_url"] = ck_url
            updates.append("ck_url = :ck_url")
            params["ck_url"] = ck_url

        if body.qty is not None:
            updates.append("qty = :qty")
            params["qty"] = body.qty

        if economics_fields & fields_set or body.qty is not None:
            if "ck_adj" not in fields_set and ("ck_cash" in fields_set or "condition" in fields_set):
                if merged.get("ck_cash") is not None:
                    mult = MANUAL_CONDITION_MULT.get(merged.get("condition_display") or "Near Mint", 1.0)
                    merged["ck_adj"] = round(float(merged["ck_cash"]) * mult, 2)
                    if "ck_adj = :ck_adj" not in updates:
                        updates.append("ck_adj = :ck_adj")
                        params["ck_adj"] = merged["ck_adj"]

            econ = _recalc_purchase_economics(
                seller_price=float(merged["seller_price"]) if merged.get("seller_price") is not None else None,
                shipping_price=merged.get("shipping_price"),
                ck_cash=float(merged["ck_cash"]) if merged.get("ck_cash") is not None else None,
                ck_adj=float(merged["ck_adj"]) if merged.get("ck_adj") is not None else None,
                condition_display=merged.get("condition_display"),
                qty=int(merged["qty"]),
            )
            merged.update(econ)
            for key in ("ck_adj", "profit_per_copy", "order_profit", "order_roi", "shipping_price"):
                if f"{key} = :{key}" not in updates:
                    updates.append(f"{key} = :{key}")
                    params[key] = merged[key]
            merged["order_qty"] = int(merged["qty"])
            if "order_qty = :order_qty" not in updates:
                updates.append("order_qty = :order_qty")
                params["order_qty"] = merged["order_qty"]

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        updates.append("updated_at = NOW()")
        sql = f"""
            UPDATE purchases SET {", ".join(updates)}
            WHERE id = :id
            RETURNING *
        """
        row = conn.execute(text(sql), params).mappings().first()

    return _normalize_purchase_row(dict(row))


@app.delete("/api/purchases/{purchase_id}")
def delete_purchase(purchase_id: int) -> dict[str, Any]:
    """Remove one purchase row from the queue."""
    with engine.begin() as conn:
        row = conn.execute(
            text("DELETE FROM purchases WHERE id = :id RETURNING id, name"),
            {"id": purchase_id},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Purchase not found")
    return {"deleted": True, "id": row["id"], "name": row["name"]}


@app.post("/api/purchases/batch-delete")
def batch_delete_purchases(body: PurchaseBatchDelete) -> dict[str, Any]:
    """Remove multiple purchase rows."""
    if not body.purchase_ids:
        raise HTTPException(status_code=400, detail="purchase_ids required")
    with engine.begin() as conn:
        rows = conn.execute(
            text("DELETE FROM purchases WHERE id = ANY(:ids) RETURNING id, name"),
            {"ids": body.purchase_ids},
        ).mappings().all()
    deleted_ids = {int(r["id"]) for r in rows}
    missing = sorted(set(body.purchase_ids) - deleted_ids)
    return {
        "deleted": [{"id": r["id"], "name": r["name"]} for r in rows],
        "count": len(rows),
        "missing_ids": missing,
    }


def _build_batch_link_updates(body: PurchaseBatchLink) -> tuple[list[str], dict[str, Any]]:
    updates: list[str] = []
    params: dict[str, Any] = {}
    fields_set = body.model_fields_set

    if "checkout_key" in fields_set:
        updates.append("checkout_key = :checkout_key")
        params["checkout_key"] = _normalize_link_field(body.checkout_key)
    if "tcg_order_id" in fields_set:
        updates.append("tcg_order_id = :tcg_order_id")
        params["tcg_order_id"] = _normalize_link_field(body.tcg_order_id)
    if "ck_batch_id" in fields_set:
        updates.append("ck_batch_id = :ck_batch_id")
        params["ck_batch_id"] = _normalize_link_field(body.ck_batch_id)
    if body.status is not None:
        if body.status not in PURCHASE_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        updates.append("status = :status")
        params["status"] = body.status

    return updates, params


@app.post("/api/purchases/batch-link")
def batch_link_purchases(body: PurchaseBatchLink) -> dict[str, Any]:
    """Assign checkout_key, tcg_order_id, and/or ck_batch_id to multiple purchases."""
    if not body.purchase_ids:
        raise HTTPException(status_code=400, detail="purchase_ids required")

    updates, params = _build_batch_link_updates(body)
    if not updates:
        raise HTTPException(status_code=400, detail="No link fields to update")

    updates.append("updated_at = NOW()")
    params["ids"] = body.purchase_ids
    sql = f"""
        UPDATE purchases SET {", ".join(updates)}
        WHERE id = ANY(:ids)
        RETURNING *
    """

    with engine.begin() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    updated = [_normalize_purchase_row(dict(r)) for r in rows]
    missing = sorted(set(body.purchase_ids) - {r["id"] for r in updated})
    return {"updated": updated, "missing_ids": missing}


@app.post("/api/purchases/link-seller")
def link_seller_purchases(body: PurchaseSellerLink) -> dict[str, Any]:
    """Link all purchases from one seller to a TCG seller order #."""
    seller = body.seller.strip()
    tcg_order_id = _normalize_link_field(body.tcg_order_id)
    if not seller or not tcg_order_id:
        raise HTTPException(status_code=400, detail="seller and tcg_order_id required")

    clauses = ["LOWER(seller) = LOWER(:seller)", "status NOT IN ('paid', 'cancelled')"]
    params: dict[str, Any] = {"seller": seller, "tcg_order_id": tcg_order_id}

    if body.only_unlinked:
        clauses.append("tcg_order_id IS NULL")

    set_parts = ["tcg_order_id = :tcg_order_id", "updated_at = NOW()"]
    if body.status is not None:
        if body.status not in PURCHASE_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        set_parts.insert(1, "status = :status")
        params["status"] = body.status

    where_sql = " AND ".join(clauses)
    sql = f"""
        UPDATE purchases SET {", ".join(set_parts)}
        WHERE {where_sql}
        RETURNING *
    """

    with engine.begin() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    return {
        "updated": [_normalize_purchase_row(dict(r)) for r in rows],
        "count": len(rows),
    }


@app.get("/api/search")
def search_cards(
    q: str = Query("", description="Card name search"),
    set_code: str = Query("", description="Scryfall set code filter"),
    finish: str = Query("", description="Finish: normal, foil, etched"),
    min_cash: float | None = None,
    sort: str = Query(
        "pct_diff_desc",
        description="Sort: pct_diff_desc, pct_diff_asc, cash_desc, name",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    clauses = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if q.strip():
        clauses.append("name ILIKE :q")
        params["q"] = f"%{q.strip()}%"
    if set_code.strip():
        clauses.append("set_code = :set_code")
        params["set_code"] = set_code.strip().lower()
    if finish.strip():
        clauses.append("finish = :finish")
        params["finish"] = finish.strip().lower()
    if min_cash is not None:
        clauses.append("cash_price >= :min_cash")
        params["min_cash"] = min_cash

    order_by = SORT_OPTIONS.get(sort, SORT_OPTIONS["pct_diff_desc"])
    where_sql = " AND ".join(clauses)
    sql = f"""
        WITH base AS (
            SELECT product_id, name, set_name, finish, cash_price,
                   max_qty, scryfall_id, set_code, tcgplayer_id,
                   tcg_market, tcg_low, tcg_mid,
                   {TCG_BUY_EXPR} AS tcg_buy_price,
                   tcg_listing_condition,
                   {CK_CASH_EXPR} AS ck_cash_adjusted,
                   condition_multiplier,
                   {CK_CASH_EXPR} - ({TCG_BUY_EXPR}) AS diff_usd,
                   {PCT_DIFF_EXPR} AS pct_diff
            FROM buylist_current
            WHERE {where_sql}
        )
        SELECT * FROM base
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
    """
    count_sql = f"""
        SELECT COUNT(*) AS n
        FROM buylist_current
        WHERE {where_sql}
    """

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        total = conn.execute(text(count_sql), params).scalar() or 0

    results = []
    for r in rows:
        row = dict(r)
        for key in (
            "cash_price",
            "ck_cash_adjusted",
            "condition_multiplier",
            "tcg_market",
            "tcg_low",
            "tcg_mid",
            "tcg_buy_price",
            "diff_usd",
            "pct_diff",
        ):
            if row.get(key) is not None:
                row[key] = float(row[key])
        results.append(row)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "results": results,
    }


@app.post("/api/collection/match")
async def match_collection_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a CSV file")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    try:
        collection = parse_collection_csv(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with engine.connect() as conn:
        ck_rows = conn.execute(
            text(
                """
                SELECT product_id, name, set_name, finish, cash_price, credit_price,
                       max_qty, scryfall_id, set_code
                FROM buylist_current
                WHERE scryfall_id IS NOT NULL
                """
            )
        ).mappings().all()

    if not ck_rows:
        raise HTTPException(
            status_code=503,
            detail="No buylist loaded. Run the daily pipeline first.",
        )

    meta = get_meta()
    result = match_collection(collection, [dict(r) for r in ck_rows])
    result["snapshot_date"] = meta.snapshot_date
    result["filename"] = file.filename
    return result


@app.get("/api/history/search")
def history_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(25, ge=1, le=50),
) -> dict[str, Any]:
    """Find cards for price charts (from cards with history in DB)."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT scryfall_id, name, set_code, finish,
                       MAX(cash_price) AS latest_cash,
                       COUNT(DISTINCT snapshot_date) AS snapshot_days
                FROM buylist_cards
                WHERE scryfall_id IS NOT NULL
                  AND name ILIKE :q
                GROUP BY scryfall_id, name, set_code, finish
                ORDER BY snapshot_days DESC, latest_cash DESC NULLS LAST, name
                LIMIT :limit
                """
            ),
            {"q": f"%{q.strip()}%", "limit": limit},
        ).mappings().all()
    return {"results": [dict(r) for r in rows]}


@app.get("/api/history/series")
def history_series(
    scryfall_id: str = Query(...),
    finish: str = Query("normal"),
    days: int = Query(90, ge=7, le=365),
    min_cash: float | None = Query(None, description="Only snapshots where CK cash >= this"),
) -> dict[str, Any]:
    """CK cash/credit vs TCG buy (condition-adjusted) over time for one card+finish."""
    finish = finish.strip().lower()
    since = date.today() - timedelta(days=days)
    clauses = [
        "scryfall_id = :sid",
        "finish = :finish",
        "snapshot_date >= :since",
    ]
    params: dict[str, Any] = {
        "sid": scryfall_id.strip().lower(),
        "finish": finish,
        "since": since,
    }
    if min_cash is not None:
        clauses.append("cash_price >= :min_cash")
        params["min_cash"] = min_cash

    where_sql = " AND ".join(clauses)
    sql = f"""
        SELECT snapshot_date::text AS snapshot_date,
               cash_price, credit_price,
               ck_cash_adjusted, tcg_buy_price,
               tcg_market, tcg_low, tcg_mid,
               tcg_listing_condition,
               name, set_name, set_code, product_id
        FROM buylist_cards
        WHERE {where_sql}
        ORDER BY snapshot_date ASC
    """

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No history for this card/finish in the selected range. "
            "Need multiple daily pipeline runs.",
        )

    series = []
    for r in rows:
        ck_val = (
            float(r["ck_cash_adjusted"])
            if r["ck_cash_adjusted"] is not None
            else (float(r["cash_price"]) if r["cash_price"] is not None else None)
        )
        low = float(r["tcg_low"]) if r["tcg_low"] is not None else None
        mkt = float(r["tcg_market"]) if r["tcg_market"] is not None else None
        listed_buy = float(r["tcg_buy_price"]) if r["tcg_buy_price"] is not None else None
        if listed_buy is not None:
            buy = listed_buy
        elif low is not None and mkt is not None and ck_val is not None:
            buy = low if abs(ck_val - low) <= abs(ck_val - mkt) else mkt
        else:
            buy = low if low is not None else mkt
        series.append(
            {
                "date": r["snapshot_date"],
                "ck_cash": float(r["cash_price"]) if r["cash_price"] is not None else None,
                "ck_cash_adjusted": ck_val,
                "ck_credit": float(r["credit_price"]) if r["credit_price"] is not None else None,
                "tcg_buy_price": float(buy) if buy is not None else None,
                "tcg_market": float(r["tcg_market"]) if r["tcg_market"] is not None else None,
                "tcg_low": float(r["tcg_low"]) if r["tcg_low"] is not None else None,
                "tcg_mid": float(r["tcg_mid"]) if r["tcg_mid"] is not None else None,
                "tcg_listing_condition": r["tcg_listing_condition"],
            }
        )

    first = rows[0]
    return {
        "scryfall_id": scryfall_id,
        "finish": finish,
        "days": days,
        "name": first["name"],
        "set_name": first["set_name"],
        "set_code": first["set_code"],
        "product_id": first["product_id"],
        "point_count": len(series),
        "series": series,
    }


@app.get("/api/card/{product_id}")
def get_card(product_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM buylist_current WHERE product_id = :pid"),
            {"pid": product_id},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Card not found")
    return dict(row)


def _page(name: str):
    path = os.path.join(STATIC_DIR, name)
    if os.path.isfile(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="Page not found")


@app.get("/")
def index():
    return _page("index.html")


@app.get("/match")
def match_page():
    return _page("match.html")


@app.get("/sell-list")
def sell_list_page():
    return _page("sell-list.html")


@app.get("/charts")
def charts_page():
    return _page("charts.html")


@app.get("/opportunities")
def opportunities_page():
    return _page("opportunities.html")


@app.get("/inventory")
def inventory_page():
    return _page("inventory.html")


@app.get("/returns")
def returns_page():
    return _page("returns.html")


@app.get("/data")
def data_page():
    return _page("data.html")


@app.get("/architecture")
def architecture_page():
    return _page("architecture.html")


@app.get("/architecture/model")
def architecture_model_page():
    return _page("architecture-model.html")


@app.get("/pokemon")
def pokemon_page():
    return _page("pokemon.html")


@app.get("/star-piece")
def star_piece_page():
    return _page("pokemon.html")


@app.get("/purchases")
def purchases_page():
    return RedirectResponse(url="/inventory", status_code=302)


if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
