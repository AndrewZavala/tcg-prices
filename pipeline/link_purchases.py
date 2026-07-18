#!/usr/bin/env python3
"""DEPRECATED — use pipeline/link_inventory.py instead.

This script still updates the legacy `purchases` table. New workflow uses
`inventory_lots` + `ck_fulfillments`. Kept for one-off migration/debug only.

Link purchases rows to the order tracker (tcg_order_id, ck_batch_id).

Examples:
  # Assign TCG seller order # to specific purchase ids
  python pipeline/link_purchases.py batch --ids 1,2,3 --tcg-order-id "D95E2DBE-6D3607-73354" --status ordered

  # Link all unlinked cards from one seller to that seller's order #
  python pipeline/link_purchases.py seller --seller "Tarkan's Cards3" --tcg-order-id "D95E2DBE-6D3607-73354"

  # Pack for CK
  python pipeline/link_purchases.py batch --ids 1,2,3,4 --ck-batch-id "CK-2026-07-02-A" --status at_ck
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://tcg:tcg_secret@localhost:5432/tcg_buylist",
)

PURCHASE_STATUSES = ("planned", "ordered", "shipped", "at_ck", "paid", "cancelled")


def _normalize_link(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        ids.append(int(part))
    if not ids:
        raise ValueError("No purchase ids provided")
    return ids


def cmd_batch(args: argparse.Namespace) -> int:
    ids = _parse_ids(args.ids)
    updates: list[str] = []
    params: dict[str, Any] = {"ids": ids}

    if args.checkout_key is not None:
        updates.append("checkout_key = :checkout_key")
        params["checkout_key"] = _normalize_link(args.checkout_key)
    if args.tcg_order_id is not None:
        updates.append("tcg_order_id = :tcg_order_id")
        params["tcg_order_id"] = _normalize_link(args.tcg_order_id)
    if args.ck_batch_id is not None:
        updates.append("ck_batch_id = :ck_batch_id")
        params["ck_batch_id"] = _normalize_link(args.ck_batch_id)
    if args.status:
        if args.status not in PURCHASE_STATUSES:
            print(f"Invalid status: {args.status}", file=sys.stderr)
            return 1
        updates.append("status = :status")
        params["status"] = args.status

    if not updates:
        print("Provide at least one of --checkout-key, --tcg-order-id, --ck-batch-id, --status", file=sys.stderr)
        return 1

    updates.append("updated_at = NOW()")
    sql = f"""
        UPDATE purchases SET {", ".join(updates)}
        WHERE id = ANY(:ids)
        RETURNING id, name, seller, checkout_key, tcg_order_id, ck_batch_id, status
    """

    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    missing = sorted(set(ids) - {int(r["id"]) for r in rows})
    print(json.dumps({"updated": [dict(r) for r in rows], "missing_ids": missing}, indent=2, default=str))
    return 0 if not missing else 1


def cmd_seller(args: argparse.Namespace) -> int:
    seller = args.seller.strip()
    tcg_order_id = _normalize_link(args.tcg_order_id)
    if not seller or not tcg_order_id:
        print("--seller and --tcg-order-id required", file=sys.stderr)
        return 1

    clauses = ["LOWER(seller) = LOWER(:seller)", "status NOT IN ('paid', 'cancelled')"]
    params: dict[str, Any] = {"seller": seller, "tcg_order_id": tcg_order_id}
    if not args.include_linked:
        clauses.append("tcg_order_id IS NULL")

    set_parts = ["tcg_order_id = :tcg_order_id", "updated_at = NOW()"]
    if args.status:
        if args.status not in PURCHASE_STATUSES:
            print(f"Invalid status: {args.status}", file=sys.stderr)
            return 1
        set_parts.insert(1, "status = :status")
        params["status"] = args.status

    where_sql = " AND ".join(clauses)
    sql = f"""
        UPDATE purchases SET {", ".join(set_parts)}
        WHERE {where_sql}
        RETURNING id, name, seller, tcg_order_id, status
    """

    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    print(json.dumps({"count": len(rows), "updated": [dict(r) for r in rows]}, indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Link purchases to order-tracker identifiers")
    sub = parser.add_subparsers(dest="command", required=True)

    p_batch = sub.add_parser("batch", help="Link specific purchase ids")
    p_batch.add_argument("--ids", required=True, help="Comma-separated purchase ids")
    p_batch.add_argument("--checkout-key", default=None, help="e.g. 2026-07-02:165.79")
    p_batch.add_argument("--tcg-order-id", default=None, help="TCG seller order UUID")
    p_batch.add_argument("--ck-batch-id", default=None, help="e.g. CK-2026-07-02-A")
    p_batch.add_argument("--status", default=None, choices=PURCHASE_STATUSES)
    p_batch.set_defaults(func=cmd_batch)

    p_seller = sub.add_parser("seller", help="Link all purchases from one seller to a TCG order #")
    p_seller.add_argument("--seller", required=True, help="Exact TCG seller name")
    p_seller.add_argument("--tcg-order-id", required=True, help="Seller order # from TCG order history")
    p_seller.add_argument("--status", default="ordered", choices=PURCHASE_STATUSES)
    p_seller.add_argument(
        "--include-linked",
        action="store_true",
        help="Update even if tcg_order_id is already set",
    )
    p_seller.set_defaults(func=cmd_seller)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
