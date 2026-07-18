"""Read-only Postgres data explorer for demos and debugging."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.engine import Engine

_engine: Engine | None = None
router = APIRouter()

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Whitelist only — no arbitrary table names.
DATASETS: dict[str, dict[str, str]] = {
    "opportunities_current": {
        "label": "Opportunities (latest snapshot)",
        "stage": "Daily pipeline output",
        "description": "Ranked buy-on-TCG / sell-to-CK rows with profit, ROI, seller, and URLs.",
    },
    "opportunities_snapshots": {
        "label": "Opportunity snapshots",
        "stage": "Pipeline metadata",
        "description": "One row per daily opportunities export loaded into Postgres.",
    },
    "buylist_current": {
        "label": "CK buylist (latest snapshot)",
        "stage": "Source data",
        "description": "Card Kingdom buylist prices joined with TCG market data for the current snapshot.",
    },
    "buylist_snapshots": {
        "label": "Buylist snapshots",
        "stage": "Pipeline metadata",
        "description": "Dates and row counts for each CK buylist pull.",
    },
    "inventory_summary": {
        "label": "Inventory + realized profit",
        "stage": "Operations / analytics",
        "description": "Lots with expected profit (at buy) and realized profit (from paid CK fulfillments).",
    },
    "inventory_lots": {
        "label": "Inventory lots (raw)",
        "stage": "Operations",
        "description": "One row per TCG purchase — qty on hand, economics frozen at buy time.",
    },
    "ck_fulfillments": {
        "label": "CK fulfillments (raw)",
        "stage": "Operations",
        "description": "Shipments to Card Kingdom — qty, batch, status, paid amount.",
    },
    "inventory_fulfillment_detail": {
        "label": "Fulfillment detail (joined)",
        "stage": "Analytics / Tableau",
        "description": "Each CK submission joined to its inventory lot for reporting.",
    },
    "purchases": {
        "label": "Purchases (legacy)",
        "stage": "Legacy",
        "description": "Pre-inventory table; frozen after migration. New data uses inventory_lots.",
    },
}

SEARCH_COLUMNS: dict[str, list[str]] = {
    "opportunities_current": ["name", "set_name", "seller"],
    "buylist_current": ["name", "set_name", "set_code"],
    "inventory_summary": ["name", "set_name", "seller", "tcg_order_id"],
    "inventory_lots": ["name", "set_name", "seller", "tcg_order_id"],
    "ck_fulfillments": ["ck_batch_id", "ck_ref", "notes"],
    "inventory_fulfillment_detail": ["name", "set_name", "seller", "ck_batch_id"],
    "purchases": ["name", "set_name", "seller", "tcg_order_id"],
}


def init_data_api(engine: Engine) -> None:
    global _engine
    _engine = engine


def _require_engine() -> Engine:
    if _engine is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    return _engine


def _validate_dataset(name: str) -> str:
    if name not in DATASETS:
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {name}")
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid dataset name")
    return name


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_value(val) for key, val in row.items()}


def _build_where(dataset: str, q: str | None) -> tuple[str, dict[str, Any]]:
    cols = SEARCH_COLUMNS.get(dataset)
    if not q or not cols:
        return "", {}
    term = q.strip()
    if not term:
        return "", {}
    clauses = [f'"{col}" ILIKE :q' for col in cols]
    return f" WHERE ({' OR '.join(clauses)})", {"q": f"%{term}%"}


@router.get("/api/data/catalog")
def data_catalog() -> dict[str, Any]:
    """List browseable Postgres tables/views with row counts."""
    engine = _require_engine()
    items: list[dict[str, Any]] = []
    with engine.connect() as conn:
        for key, meta in DATASETS.items():
            count = conn.execute(
                text(f"SELECT COUNT(*) AS n FROM {key}")
            ).scalar()
            items.append(
                {
                    "id": key,
                    "label": meta["label"],
                    "stage": meta["stage"],
                    "description": meta["description"],
                    "row_count": int(count or 0),
                    "browse_url": f"/data?dataset={key}",
                    "api_url": f"/api/data/{key}",
                }
            )
    return {"datasets": items, "count": len(items)}


@router.get("/api/data/{dataset}")
def data_rows(
    dataset: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: str = Query("", description="Search text columns"),
    sort: str = Query("", description="Column name to sort by (desc)"),
) -> dict[str, Any]:
    """Paginated read-only rows from a whitelisted table or view."""
    name = _validate_dataset(dataset)
    engine = _require_engine()

    where_sql, params = _build_where(name, q)
    params["limit"] = limit
    params["offset"] = offset

    order_sql = ""
    if sort and _NAME_RE.match(sort):
        order_sql = f' ORDER BY "{sort}" DESC NULLS LAST'

    count_sql = f"SELECT COUNT(*) AS n FROM {name}{where_sql}"
    data_sql = f"SELECT * FROM {name}{where_sql}{order_sql} LIMIT :limit OFFSET :offset"

    with engine.connect() as conn:
        total = int(conn.execute(text(count_sql), params).scalar() or 0)
        rows = conn.execute(text(data_sql), params).mappings().all()

    columns = list(rows[0].keys()) if rows else []
    if not columns and total > 0:
        # Empty page but rows exist — fetch column names from information_schema
        with engine.connect() as conn:
            col_rows = conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :name
                    ORDER BY ordinal_position
                    """
                ),
                {"name": name},
            ).scalars().all()
            if not col_rows:
                col_rows = conn.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = (
                            SELECT table_name FROM information_schema.views
                            WHERE table_schema = 'public' AND table_name = :name
                            LIMIT 1
                          )
                        ORDER BY ordinal_position
                        """
                    ),
                    {"name": name},
                ).scalars().all()
            columns = list(col_rows)

    serialized = [_serialize_row(dict(r)) for r in rows]
    meta = DATASETS[name]
    return {
        "dataset": name,
        "label": meta["label"],
        "stage": meta["stage"],
        "description": meta["description"],
        "columns": columns,
        "rows": serialized,
        "total": total,
        "limit": limit,
        "offset": offset,
        "q": q.strip() or None,
        "api_url": f"/api/data/{name}",
    }


@router.get("/api/data/{dataset}/export.csv")
def data_export_csv(
    dataset: str,
    q: str = Query(""),
    limit: int = Query(5000, ge=1, le=20000),
) -> Response:
    """Download up to 20k rows as CSV (interview / Tableau friendly)."""
    name = _validate_dataset(dataset)
    engine = _require_engine()
    where_sql, params = _build_where(name, q)
    params["limit"] = limit

    sql = f"SELECT * FROM {name}{where_sql} LIMIT :limit"
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _json_value(v) for k, v in dict(row).items()})
    else:
        buf.write("")

    filename = f"{name}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
