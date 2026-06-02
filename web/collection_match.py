"""Match uploaded collection CSV rows against CK buylist (current snapshot)."""

from __future__ import annotations

import csv
import io
from typing import Any

# Column aliases (lowercase) -> canonical field
COLUMN_ALIASES: dict[str, str] = {
    "scryfall id": "scryfall_id",
    "scryfall_id": "scryfall_id",
    "id": "scryfall_id",
    "name": "name",
    "card name": "name",
    "title": "name",
    "set code": "set_code",
    "set": "set_code",
    "setcode": "set_code",
    "collector number": "collector_number",
    "collector_number": "collector_number",
    "finish": "finish",
    "foil": "finish",
    "quantity": "quantity",
    "qty": "quantity",
    "count": "quantity",
}


def _normalize_header(h: str) -> str:
    return COLUMN_ALIASES.get(h.strip().lower(), h.strip().lower())


def _normalize_finish(raw: str) -> str:
    v = (raw or "").strip().lower()
    if v in ("yes", "true", "1", "foil"):
        return "foil"
    if "etched" in v:
        return "etched"
    return "normal"


def parse_collection_csv(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    field_map = {_normalize_header(h): h for h in reader.fieldnames if h}
    if "scryfall_id" not in field_map:
        raise ValueError(
            "CSV must include a Scryfall ID column (e.g. 'Scryfall ID' from Manabox/Moxfield/Stacks export)"
        )

    rows: list[dict[str, Any]] = []
    for i, raw in enumerate(reader, start=2):
        sid = (raw.get(field_map["scryfall_id"]) or "").strip()
        if not sid:
            continue
        finish_raw = raw.get(field_map.get("finish", ""), "normal") if "finish" in field_map else "normal"
        qty_raw = raw.get(field_map.get("quantity", ""), "1") if "quantity" in field_map else "1"
        try:
            qty = max(1, int(float(str(qty_raw).strip() or "1")))
        except ValueError:
            qty = 1

        rows.append(
            {
                "row_num": i,
                "scryfall_id": sid.lower(),
                "name": (raw.get(field_map.get("name", ""), "") or "").strip() or None,
                "set_code": (raw.get(field_map.get("set_code", ""), "") or "").strip().lower() or None,
                "collector_number": (raw.get(field_map.get("collector_number", ""), "") or "").strip() or None,
                "finish": _normalize_finish(str(finish_raw)),
                "quantity": qty,
            }
        )
    if not rows:
        raise ValueError("No rows with Scryfall ID found in CSV")
    return rows


def finish_matches(stack_finish: str, ck_finish: str | None, ck_name: str | None) -> bool:
    ck_finish = (ck_finish or "normal").lower()
    name = (ck_name or "").lower()
    if stack_finish == "etched":
        return ck_finish == "etched" or "etched" in name
    if stack_finish == "foil":
        return ck_finish == "foil"
    return ck_finish in ("normal", "nonfoil") or ck_finish not in ("foil", "etched")


def match_collection(
    collection: list[dict[str, Any]],
    ck_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Match collection lines to CK buylist rows from buylist_current."""
    by_id: dict[str, list[dict[str, Any]]] = {}
    for row in ck_rows:
        sid = (row.get("scryfall_id") or "").strip().lower()
        if sid:
            by_id.setdefault(sid, []).append(row)

    results: list[dict[str, Any]] = []
    stats = {"matched": 0, "no_scryfall_id": 0, "wrong_finish": 0}

    for item in collection:
        sid = item["scryfall_id"]
        finish = item["finish"]
        base = {**item}

        if sid not in by_id:
            stats["no_scryfall_id"] += 1
            results.append(
                {
                    **base,
                    "ck_match": "no_scryfall_id",
                    "ck_cash_price": None,
                    "ck_credit_price": None,
                    "ck_max_qty": None,
                    "ck_name": None,
                    "ck_set_name": None,
                    "line_cash_total": None,
                    "line_credit_total": None,
                }
            )
            continue

        candidates = by_id[sid]
        hit = next(
            (
                c
                for c in candidates
                if finish_matches(finish, c.get("finish"), c.get("name"))
            ),
            None,
        )
        if hit:
            stats["matched"] += 1
            cash = float(hit["cash_price"]) if hit.get("cash_price") is not None else None
            credit = float(hit["credit_price"]) if hit.get("credit_price") is not None else None
            qty = item["quantity"]
            results.append(
                {
                    **base,
                    "ck_match": "matched",
                    "ck_cash_price": cash,
                    "ck_credit_price": credit,
                    "ck_max_qty": hit.get("max_qty"),
                    "ck_name": hit.get("name"),
                    "ck_set_name": hit.get("set_name"),
                    "product_id": hit.get("product_id"),
                    "line_cash_total": round(cash * qty, 2) if cash is not None else None,
                    "line_credit_total": round(credit * qty, 2) if credit is not None else None,
                }
            )
        else:
            stats["wrong_finish"] += 1
            any_row = candidates[0]
            results.append(
                {
                    **base,
                    "ck_match": "wrong_finish",
                    "ck_cash_price": None,
                    "ck_credit_price": None,
                    "ck_max_qty": None,
                    "ck_name": any_row.get("name"),
                    "ck_set_name": any_row.get("set_name"),
                    "line_cash_total": None,
                    "line_credit_total": None,
                }
            )

    total = len(collection)
    matched_lines = [r for r in results if r["ck_match"] == "matched"]
    return {
        "total": total,
        "matched": stats["matched"],
        "no_scryfall_id": stats["no_scryfall_id"],
        "wrong_finish": stats["wrong_finish"],
        "match_pct": round(100 * stats["matched"] / total, 1) if total else 0,
        "total_cash": round(sum(r["line_cash_total"] or 0 for r in matched_lines), 2),
        "total_credit": round(sum(r["line_credit_total"] or 0 for r in matched_lines), 2),
        "results": results,
    }
