"""Stacks / personal collection API — sell list, import, mark-sold / restore."""

from __future__ import annotations

import re
from typing import Any

from datetime import date

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

from collection_share import build_share_html
from stacks_io import (
    clear_collection,
    insert_collection_rows,
    normalize_finish,
    parse_stacks_csv,
)

router = APIRouter()
_engine: Engine | None = None

COLLECTION_STATUSES = ("active", "sold", "keep")
# Skip penny/two-cent CK offers — not worth shipping.
MIN_SELL_CK_CASH = 0.03


def init_collection_api(engine: Engine) -> None:
    global _engine
    _engine = engine


def _clean_ck_edition(set_name: str | None) -> str:
    s = (set_name or "").strip()
    s = re.sub(r"\s+FOIL$", "", s, flags=re.I)
    s = re.sub(r"\s+\([A-Z0-9]+\)$", "", s)
    return s.strip()


def _ck_export_name(name: str | None, variation: str | None) -> str:
    """CK CSV Title: base name plus CK variation when present (as CK stores it)."""
    base = (name or "").strip()
    var = (variation or "").strip()
    if base and var:
        return f"{base} ({var})"
    return base or var


def _ck_export_foil(finish: str | None) -> str:
    """CK accepts 1/true/yes or 0/false/no — use 0/1 to avoid TRUE/FALSE edge cases."""
    return "1" if (finish or "").strip().lower() == "foil" else "0"


def _finish_match_sql(coll_alias: str = "c", buy_alias: str = "b") -> str:
    return f"""
        (
          (
            lower(COALESCE({coll_alias}.finish, 'normal')) = 'etched'
            AND (
              lower(COALESCE({buy_alias}.finish, '')) = 'etched'
              OR lower(COALESCE({buy_alias}.name, '')) LIKE '%etched%'
            )
          )
          OR (
            lower(COALESCE({coll_alias}.finish, 'normal')) = 'foil'
            AND lower(COALESCE({buy_alias}.finish, '')) = 'foil'
          )
          OR (
            lower(COALESCE({coll_alias}.finish, 'normal')) IN ('normal', 'nonfoil')
            AND lower(COALESCE({buy_alias}.finish, 'normal')) NOT IN ('foil', 'etched')
            AND lower(COALESCE({buy_alias}.name, '')) NOT LIKE '%etched%'
          )
        )
    """


def _tcg_price_sql(coll_alias: str = "c", buy_alias: str = "b") -> str:
    return f"""
        CASE
          WHEN lower(COALESCE({coll_alias}.finish, 'normal')) = 'foil'
            THEN {buy_alias}.usd_foil
          WHEN lower(COALESCE({coll_alias}.finish, 'normal')) = 'etched'
            THEN COALESCE({buy_alias}.usd_etched, {buy_alias}.usd_foil)
          ELSE {buy_alias}.usd
        END
    """


class IdsBody(BaseModel):
    ids: list[int]


class CollectionCardUpdate(BaseModel):
    name: str | None = None
    set_code: str | None = None
    collector_number: str | None = None
    finish: str | None = None
    quantity: int | None = None
    scryfall_id: str | None = None
    status: str | None = None
    notes: str | None = None


@router.get("/api/collection/summary")
def collection_summary() -> dict[str, Any]:
    assert _engine is not None
    finish_sql = _finish_match_sql()
    with _engine.connect() as conn:
        active = conn.execute(
            text("SELECT COUNT(*) FROM collection_cards WHERE status = 'active'")
        ).scalar() or 0
        keep = conn.execute(
            text("SELECT COUNT(*) FROM collection_cards WHERE status = 'keep'")
        ).scalar() or 0
        sold = conn.execute(
            text("SELECT COUNT(*) FROM collection_cards WHERE status = 'sold'")
        ).scalar() or 0
        sellable = conn.execute(
            text(
                f"""
                SELECT COUNT(*) FROM collection_cards c
                WHERE c.status = 'active'
                  AND EXISTS (
                    SELECT 1 FROM buylist_current b
                    WHERE lower(b.scryfall_id) = lower(c.scryfall_id)
                      AND b.cash_price IS NOT NULL
                      AND b.cash_price >= :min_cash
                      AND {finish_sql}
                  )
                """
            ),
            {"min_cash": MIN_SELL_CK_CASH},
        ).scalar() or 0
        imports = conn.execute(
            text("SELECT COUNT(*) FROM collection_import_files")
        ).scalar() or 0
    return {
        "active": int(active),
        "keep": int(keep),
        "sold": int(sold),
        "sellable": int(sellable),
        "imported_files": int(imports),
    }


@router.get("/api/collection/sell-list")
def collection_sell_list(
    q: str = Query("", description="Card name search"),
) -> dict[str, Any]:
    assert _engine is not None
    finish_sql = _finish_match_sql()
    tcg_sql = _tcg_price_sql()
    clauses = [
        "c.status = 'active'",
        "b.cash_price IS NOT NULL",
        "b.cash_price >= :min_cash",
        finish_sql,
    ]
    params: dict[str, Any] = {"min_cash": MIN_SELL_CK_CASH}
    if q.strip():
        clauses.append("(c.name ILIKE :q OR b.name ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    where_sql = " AND ".join(clauses)

    sql = f"""
        SELECT
            c.id,
            c.batch_file,
            c.scan_order,
            c.scryfall_id,
            c.set_code,
            c.collector_number,
            c.finish,
            c.name,
            c.quantity,
            c.colors,
            b.name AS ck_name,
            b.set_name AS ck_set_name,
            b.variation AS ck_variation,
            b.cash_price,
            b.credit_price,
            b.max_qty AS ck_max_qty,
            b.product_id,
            ({tcg_sql}) AS tcg_price
        FROM collection_cards c
        INNER JOIN buylist_current b
          ON lower(b.scryfall_id) = lower(c.scryfall_id)
        WHERE {where_sql}
        ORDER BY
            COALESCE((regexp_match(c.batch_file, '(?i)batch(\\d+)'))[1]::int, 0),
            c.batch_file,
            NULLIF(regexp_replace(c.scan_order, '\\D', '', 'g'), '')::bigint NULLS LAST,
            c.scan_order,
            c.id
    """

    with _engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(sql), params).mappings().all()]

    batches_map: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        cash = float(raw["cash_price"]) if raw.get("cash_price") is not None else None
        credit = float(raw["credit_price"]) if raw.get("credit_price") is not None else None
        tcg = float(raw["tcg_price"]) if raw.get("tcg_price") is not None else None
        qty = int(raw["quantity"] or 1)
        line_cash = round(cash * qty, 2) if cash is not None else None
        line_credit = round(credit * qty, 2) if credit is not None else None
        pct = None
        if credit is not None and tcg and tcg > 0:
            pct = round(credit / tcg * 100, 1)
        item = {
            "id": raw["id"],
            "batch_file": raw["batch_file"],
            "scan_order": raw["scan_order"],
            "scryfall_id": raw["scryfall_id"],
            "set_code": raw.get("set_code"),
            "collector_number": raw.get("collector_number"),
            "finish": raw["finish"],
            "name": raw["name"],
            "quantity": qty,
            "colors": raw.get("colors"),
            "ck_name": raw.get("ck_name"),
            "ck_set_name": raw.get("ck_set_name"),
            "ck_variation": (raw.get("ck_variation") or "").strip() or None,
            "ck_edition": _clean_ck_edition(raw.get("ck_set_name")),
            # Exact Title string for CK CSV import only (name + variation as CK stores it).
            "ck_export_name": _ck_export_name(raw.get("ck_name"), raw.get("ck_variation")),
            "cash_price": cash,
            "credit_price": credit,
            "line_cash": line_cash,
            "line_credit": line_credit,
            "tcg_price": tcg,
            "pct_of_tcg": pct,
            "ck_max_qty": raw.get("ck_max_qty"),
            "product_id": raw.get("product_id"),
            "foil": _ck_export_foil(raw.get("finish")),
        }
        batches_map.setdefault(raw["batch_file"], []).append(item)

    batches = []
    total_cash = 0.0
    total_credit = 0.0
    total_tcg = 0.0
    line_count = 0
    for batch_file, items in batches_map.items():
        b_cash = sum(i["line_cash"] or 0 for i in items)
        b_credit = sum(i["line_credit"] or 0 for i in items)
        b_tcg = sum((i["tcg_price"] or 0) * i["quantity"] for i in items)
        total_cash += b_cash
        total_credit += b_credit
        total_tcg += b_tcg
        line_count += len(items)
        batches.append(
            {
                "batch_file": batch_file,
                "totals": {
                    "lines": len(items),
                    "cash": round(b_cash, 2),
                    "credit": round(b_credit, 2),
                    "tcg": round(b_tcg, 2),
                },
                "rows": items,
            }
        )

    return {
        "summary": {
            "lines": line_count,
            "total_cash": round(total_cash, 2),
            "total_credit": round(total_credit, 2),
            "total_tcg": round(total_tcg, 2),
        },
        "batches": batches,
    }


@router.get("/api/collection/share.html")
def export_collection_share_html() -> Response:
    """Download a self-contained HTML inventory (active + keep) for sharing."""
    assert _engine is not None
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                WITH set_names AS (
                    SELECT
                        LOWER(b.set_code) AS set_code,
                        MODE() WITHIN GROUP (ORDER BY b.clean_set) AS set_name
                    FROM buylist_current b
                    WHERE b.set_code IS NOT NULL
                      AND b.clean_set IS NOT NULL
                      AND b.clean_set NOT ILIKE '%promo%'
                    GROUP BY LOWER(b.set_code)
                )
                SELECT
                    c.id,
                    c.name,
                    c.set_code,
                    c.collector_number,
                    c.finish,
                    c.quantity,
                    c.colors,
                    c.batch_file,
                    c.scan_order,
                    c.status,
                    c.scryfall_id,
                    COALESCE(sn.set_name, UPPER(c.set_code), 'Unknown set') AS set_name
                FROM collection_cards c
                LEFT JOIN set_names sn ON sn.set_code = LOWER(c.set_code)
                WHERE c.status IN ('active', 'keep')
                ORDER BY c.name, sn.set_name NULLS LAST, c.set_code, c.collector_number, c.id
                """
            )
        ).mappings().all()

    today = date.today()
    html_body = build_share_html([dict(r) for r in rows], exported_on=today)
    filename = f"inventory_share_{today.isoformat()}.html"
    # inline so Sell list can open it live (Mark sold needs same-origin API).
    # Users can still Save As from the browser for offline friend copies.
    return Response(
        content=html_body,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/api/collection/cards")
def list_collection_cards(
    status: str = Query("", description="active, sold, keep, or empty for all"),
    q: str = Query(""),
    batch_file: str = Query(""),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    assert _engine is not None
    clauses = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status.strip():
        if status.strip() not in COLLECTION_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        clauses.append("status = :status")
        params["status"] = status.strip()
    if q.strip():
        clauses.append("name ILIKE :q")
        params["q"] = f"%{q.strip()}%"
    if batch_file.strip():
        clauses.append("batch_file = :batch_file")
        params["batch_file"] = batch_file.strip()
    where_sql = " AND ".join(clauses)
    order = (
        "sold_at DESC NULLS LAST, id DESC"
        if status.strip() == "sold"
        else (
            "batch_file, NULLIF(regexp_replace(scan_order, '\\D', '', 'g'), '')::bigint "
            "NULLS LAST, scan_order, id"
        )
    )
    sql = f"""
        SELECT * FROM collection_cards
        WHERE {where_sql}
        ORDER BY {order}
        LIMIT :limit OFFSET :offset
    """
    count_sql = f"SELECT COUNT(*) FROM collection_cards WHERE {where_sql}"
    with _engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        total = conn.execute(text(count_sql), params).scalar() or 0
    results = []
    for r in rows:
        d = dict(r)
        for key in ("sold_at", "created_at", "updated_at"):
            if d.get(key) is not None:
                d[key] = d[key].isoformat()
        results.append(d)
    return {"total": int(total), "limit": limit, "offset": offset, "results": results}


@router.patch("/api/collection/cards/{card_id}")
def update_collection_card(card_id: int, body: CollectionCardUpdate) -> dict[str, Any]:
    """Edit a Stacks collection row (finish, printing, qty, status, etc.)."""
    assert _engine is not None
    if card_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid card id")

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates: list[str] = []
    params: dict[str, Any] = {"id": card_id}

    if "name" in fields:
        name = (fields["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name cannot be empty")
        updates.append("name = :name")
        params["name"] = name

    if "set_code" in fields:
        raw = fields["set_code"]
        updates.append("set_code = :set_code")
        params["set_code"] = (raw or "").strip().lower() or None

    if "collector_number" in fields:
        raw = fields["collector_number"]
        updates.append("collector_number = :collector_number")
        params["collector_number"] = (raw or "").strip() or None

    if "finish" in fields:
        updates.append("finish = :finish")
        params["finish"] = normalize_finish(fields["finish"])

    if "quantity" in fields:
        qty = fields["quantity"]
        if qty is None or int(qty) < 1:
            raise HTTPException(status_code=400, detail="quantity must be >= 1")
        updates.append("quantity = :quantity")
        params["quantity"] = int(qty)

    if "scryfall_id" in fields:
        sid = (fields["scryfall_id"] or "").strip().lower()
        if not sid:
            raise HTTPException(status_code=400, detail="scryfall_id cannot be empty")
        updates.append("scryfall_id = :scryfall_id")
        params["scryfall_id"] = sid

    if "status" in fields:
        status = (fields["status"] or "").strip().lower()
        if status not in COLLECTION_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        updates.append("status = :status")
        params["status"] = status
        if status == "sold":
            updates.append("sold_at = COALESCE(sold_at, NOW())")
        else:
            updates.append("sold_at = NULL")

    if "notes" in fields:
        raw = fields["notes"]
        updates.append("notes = :notes")
        params["notes"] = (raw or "").strip() or None

    updates.append("updated_at = NOW()")
    sql = f"""
        UPDATE collection_cards
        SET {", ".join(updates)}
        WHERE id = :id
        RETURNING *
    """
    with _engine.begin() as conn:
        row = conn.execute(text(sql), params).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Card not found")
    d = dict(row)
    for key in ("sold_at", "created_at", "updated_at"):
        if d.get(key) is not None:
            d[key] = d[key].isoformat()
    return d


@router.post("/api/collection/mark-sold")
def mark_collection_sold(body: IdsBody) -> dict[str, Any]:
    assert _engine is not None
    ids = [i for i in body.ids if isinstance(i, int) and i > 0]
    if not ids:
        raise HTTPException(status_code=400, detail="ids required")
    with _engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE collection_cards
                SET status = 'sold', sold_at = NOW(), updated_at = NOW()
                WHERE id = ANY(:ids) AND status IN ('active', 'keep')
                RETURNING id
                """
            ),
            {"ids": ids},
        )
        updated = [r[0] for r in result.fetchall()]
    return {"updated": len(updated), "ids": updated}


@router.post("/api/collection/mark-keep")
def mark_collection_keep(body: IdsBody) -> dict[str, Any]:
    """Tag cards as keep — stay in collection / share, hide from CK sell list."""
    assert _engine is not None
    ids = [i for i in body.ids if isinstance(i, int) and i > 0]
    if not ids:
        raise HTTPException(status_code=400, detail="ids required")
    with _engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE collection_cards
                SET status = 'keep', sold_at = NULL, updated_at = NOW()
                WHERE id = ANY(:ids) AND status = 'active'
                RETURNING id
                """
            ),
            {"ids": ids},
        )
        updated = [r[0] for r in result.fetchall()]
    return {"updated": len(updated), "ids": updated}


@router.post("/api/collection/restore")
def restore_collection_cards(body: IdsBody) -> dict[str, Any]:
    assert _engine is not None
    ids = [i for i in body.ids if isinstance(i, int) and i > 0]
    if not ids:
        raise HTTPException(status_code=400, detail="ids required")
    with _engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE collection_cards
                SET status = 'active', sold_at = NULL, updated_at = NOW()
                WHERE id = ANY(:ids) AND status IN ('sold', 'keep')
                RETURNING id
                """
            ),
            {"ids": ids},
        )
        updated = [r[0] for r in result.fetchall()]
    return {"updated": len(updated), "ids": updated}


@router.post("/api/collection/import")
async def import_collection_files(
    files: list[UploadFile] = File(...),
    replace: bool = Query(
        False,
        description="Clear existing collection before import (use with inventory.csv)",
    ),
) -> dict[str, Any]:
    """Import Stacks batch CSVs (incremental) or a full inventory.csv (replace).

    Batch exports are skipped if the filename was already imported. Matching to
    CK happens live on the sell list via buylist_current — no pipeline step.
    """
    assert _engine is not None
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[str] = []
    new_batch_files: list[str] = []

    with _engine.begin() as conn:
        names = [
            (f.filename or "upload.csv").strip().replace("\\", "/").split("/")[-1]
            for f in files
        ]
        # Consolidated inventory always replaces so sold/keep status wins over batch dumps.
        do_replace = replace or any(n.lower() == "inventory.csv" for n in names)
        if do_replace:
            clear_collection(conn)

        for f in files:
            name = (f.filename or "upload.csv").strip()
            batch_file = name.replace("\\", "/").split("/")[-1]
            if not batch_file.lower().endswith(".csv"):
                errors.append(f"{batch_file}: not a CSV")
                continue

            if not do_replace:
                already = bool(
                    conn.execute(
                        text("SELECT 1 FROM collection_import_files WHERE file_name = :n"),
                        {"n": batch_file},
                    ).scalar()
                )
                if already:
                    skipped.append(
                        {
                            "file_name": batch_file,
                            "reason": "already_imported",
                        }
                    )
                    continue

            content = await f.read()
            try:
                rows = parse_stacks_csv(content, batch_file)
            except ValueError as e:
                errors.append(str(e))
                continue
            if not rows:
                errors.append(f"{batch_file}: no rows with Scryfall ID")
                continue

            n = insert_collection_rows(conn, rows, batch_file)
            sold = sum(1 for r in rows if r.get("status") == "sold")
            keep = sum(1 for r in rows if r.get("status") == "keep")
            active = sum(1 for r in rows if r.get("status") == "active")
            imported.append(
                {
                    "file_name": batch_file,
                    "parsed_rows": len(rows),
                    "inserted": n,
                    "active_rows": active,
                    "sold_rows": sold,
                    "keep_rows": keep,
                    "replaced": do_replace,
                }
            )
            new_batch_files.append(batch_file)

        sellable_new = 0
        finish_sql = _finish_match_sql()
        sellable_base = f"""
            SELECT COUNT(*) FROM collection_cards c
            WHERE c.status = 'active'
              AND EXISTS (
                SELECT 1 FROM buylist_current b
                WHERE lower(b.scryfall_id) = lower(c.scryfall_id)
                  AND b.cash_price IS NOT NULL
                  AND b.cash_price >= :min_cash
                  AND {finish_sql}
              )
        """
        sellable_total = int(
            conn.execute(
                text(sellable_base),
                {"min_cash": MIN_SELL_CK_CASH},
            ).scalar()
            or 0
        )
        if do_replace:
            # Full replace — all sellable cards are "new" to this load.
            sellable_new = sellable_total
            for item in imported:
                item["sellable"] = sellable_total
        elif new_batch_files:
            sellable_new = int(
                conn.execute(
                    text(sellable_base + " AND c.batch_file = ANY(:batches)"),
                    {"min_cash": MIN_SELL_CK_CASH, "batches": new_batch_files},
                ).scalar()
                or 0
            )
            for item in imported:
                item["sellable"] = int(
                    conn.execute(
                        text(sellable_base + " AND c.batch_file = :batch"),
                        {
                            "min_cash": MIN_SELL_CK_CASH,
                            "batch": item["file_name"],
                        },
                    ).scalar()
                    or 0
                )

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "files": len(imported),
        "skipped_files": len(skipped),
        "inserted_total": sum(i["inserted"] for i in imported),
        "sellable_new": sellable_new,
        "sellable_total": sellable_total,
        "replaced": do_replace,
    }


@router.get("/api/collection/imports")
def list_collection_imports() -> dict[str, Any]:
    assert _engine is not None
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT file_name, imported_at, row_count
                FROM collection_import_files
                ORDER BY imported_at DESC
                """
            )
        ).mappings().all()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("imported_at") is not None:
            d["imported_at"] = d["imported_at"].isoformat()
        results.append(d)
    return {"results": results}
