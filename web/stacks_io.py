"""Shared Stacks / inventory CSV parsing and DB insert helpers (no FastAPI)."""

from __future__ import annotations

import csv
import io
from typing import Any

from sqlalchemy import text

VALID_STATUSES = frozenset({"active", "sold", "keep"})


def normalize_finish(raw: str | None) -> str:
    v = (raw or "").strip().lower()
    if v in ("yes", "true", "1", "foil"):
        return "foil"
    if "etched" in v:
        return "etched"
    if v in ("normal", "nonfoil", ""):
        return "normal"
    return v or "normal"


def normalize_status(raw: str | None) -> str:
    v = (raw or "active").strip().lower()
    return v if v in VALID_STATUSES else "active"


def parse_stacks_csv(content: bytes, batch_file: str | None = None) -> list[dict[str, Any]]:
    """Parse a Stacks batch export or consolidated inventory.csv.

    inventory.csv rows may include batch_file + status; batch exports use the
    filename as batch_file and default status to active.
    """
    label = batch_file or "upload.csv"
    text_data = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text_data))
    if not reader.fieldnames:
        raise ValueError(f"{label}: CSV has no header row")

    field_map = {h.strip().lower(): h for h in reader.fieldnames if h}
    sid_key = field_map.get("scryfall id") or field_map.get("scryfall_id")
    if not sid_key:
        raise ValueError(f"{label}: missing Scryfall ID column")

    def col(*names: str) -> str | None:
        for n in names:
            if n in field_map:
                return field_map[n]
        return None

    name_k = col("name")
    set_k = col("set code", "set_code", "set")
    cn_k = col("collector number", "collector_number")
    finish_k = col("finish")
    qty_k = col("quantity", "qty", "count")
    scan_k = col("scan order", "scan_order")
    colors_k = col("colors", "color")
    batch_k = col("batch_file", "batch")
    status_k = col("status")

    rows: list[dict[str, Any]] = []
    for i, raw in enumerate(reader, start=2):
        sid = (raw.get(sid_key) or "").strip().lower()
        if not sid:
            continue
        scan = (raw.get(scan_k) or "").strip() if scan_k else str(i)
        if not scan:
            scan = str(i)
        qty_raw = (raw.get(qty_k) or "1") if qty_k else "1"
        try:
            qty = max(1, int(float(str(qty_raw).strip() or "1")))
        except ValueError:
            qty = 1
        finish = normalize_finish(raw.get(finish_k) if finish_k else "normal")
        name = ((raw.get(name_k) or "").strip() if name_k else "") or "Unknown"
        row_batch = (
            ((raw.get(batch_k) or "").strip() if batch_k else "")
            or (batch_file or "").strip()
            or "inventory.csv"
        )
        status = normalize_status(raw.get(status_k) if status_k else "active")
        rows.append(
            {
                "batch_file": row_batch,
                "scan_order": scan,
                "scryfall_id": sid,
                "set_code": ((raw.get(set_k) or "").strip().lower() if set_k else None) or None,
                "collector_number": ((raw.get(cn_k) or "").strip() if cn_k else None) or None,
                "finish": finish,
                "name": name,
                "quantity": qty,
                "colors": ((raw.get(colors_k) or "").strip() if colors_k else None) or None,
                "status": status,
            }
        )
    return rows


def clear_collection(conn) -> None:
    conn.execute(text("TRUNCATE collection_cards RESTART IDENTITY CASCADE"))
    conn.execute(text("TRUNCATE collection_import_files"))


def insert_collection_rows(conn, rows: list[dict[str, Any]], import_file_name: str) -> int:
    if not rows:
        return 0
    inserted = 0
    for row in rows:
        result = conn.execute(
            text(
                """
                INSERT INTO collection_cards (
                    batch_file, scan_order, scryfall_id, set_code, collector_number,
                    finish, name, quantity, colors, status, sold_at
                ) VALUES (
                    :batch_file, :scan_order, :scryfall_id, :set_code, :collector_number,
                    :finish, :name, :quantity, :colors, :status,
                    CASE WHEN :status = 'sold' THEN NOW() ELSE NULL END
                )
                ON CONFLICT (batch_file, scan_order) DO NOTHING
                """
            ),
            row,
        )
        inserted += result.rowcount or 0
    conn.execute(
        text(
            """
            INSERT INTO collection_import_files (file_name, row_count)
            VALUES (:file_name, :row_count)
            ON CONFLICT (file_name) DO UPDATE
              SET imported_at = NOW(), row_count = EXCLUDED.row_count
            """
        ),
        {"file_name": import_file_name, "row_count": len(rows)},
    )
    return inserted
