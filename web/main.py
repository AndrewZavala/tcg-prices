"""FastAPI buylist API, collection matching, and price history."""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from collection_match import match_collection, parse_collection_csv

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://tcg:tcg_secret@localhost:5432/tcg_buylist",
)
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:8000").split(",")

app = FastAPI(title="TCG Prices API", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class MetaResponse(BaseModel):
    snapshot_date: str | None
    row_count: int | None
    source: str | None
    snapshot_count: int | None = None


def _apply_migration_002(conn) -> None:
    mig = os.path.join(os.path.dirname(__file__), "..", "migrations", "002_history_indexes.sql")
    if os.path.isfile(mig):
        conn.execute(text(open(mig, encoding="utf-8").read()))


@app.on_event("startup")
def startup_migrations() -> None:
    try:
        with engine.begin() as conn:
            _apply_migration_002(conn)
    except Exception:
        pass  # indexes may already exist


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


@app.get("/api/search")
def search_cards(
    q: str = Query("", description="Card name search"),
    set_code: str = Query("", description="Scryfall set code filter"),
    finish: str = Query("", description="Finish: normal, foil, etched"),
    min_cash: float | None = None,
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

    where_sql = " AND ".join(clauses)
    sql = f"""
        SELECT product_id, name, set_name, finish, cash_price, credit_price,
               max_qty, scryfall_id, set_code
        FROM buylist_current
        WHERE {where_sql}
        ORDER BY credit_price DESC NULLS LAST, name
        LIMIT :limit OFFSET :offset
    """
    count_sql = f"SELECT COUNT(*) AS n FROM buylist_current WHERE {where_sql}"

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        total = conn.execute(text(count_sql), params).scalar() or 0

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": [dict(r) for r in rows],
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
    """CK cash/credit vs Scryfall USD over time for one card+finish."""
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
               usd, usd_foil, usd_etched,
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
        tcg = r["usd"]
        if finish == "foil":
            tcg = r["usd_foil"] or r["usd"]
        elif finish == "etched":
            tcg = r["usd_etched"] or r["usd"]
        series.append(
            {
                "date": r["snapshot_date"],
                "ck_cash": float(r["cash_price"]) if r["cash_price"] is not None else None,
                "ck_credit": float(r["credit_price"]) if r["credit_price"] is not None else None,
                "tcg_usd": float(tcg) if tcg is not None else None,
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


@app.get("/charts")
def charts_page():
    return _page("charts.html")


if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
