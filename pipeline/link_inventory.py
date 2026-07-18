#!/usr/bin/env python3
"""Link inventory lots and record CK fulfillments for the order tracker.

Examples:
  # Assign TCG seller order # to specific lot ids
  python pipeline/link_inventory.py tcg-batch --ids 1,2,3 --tcg-order-id "D95E2DBE-6D3607-73354"

  # Link all unlinked lots from one seller
  python pipeline/link_inventory.py seller --seller "Tarkan's Cards3" --tcg-order-id "D95E2DBE-6D3607-73354"

  # Record CK shipment (creates ck_fulfillments rows, decrements qty_on_hand)
  python pipeline/link_inventory.py fulfill --ids 1,2 --ck-batch-id "CK-2026-07-02-A" --qty 3 --status sent
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

LOT_STATUSES = ("ordered", "inbound", "on_hand", "depleted", "cancelled")
FULFILLMENT_STATUSES = ("planned", "packed", "sent", "paid", "rejected", "cancelled")


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
        raise ValueError("No lot ids provided")
    return ids


def _decrements_inventory(status: str) -> bool:
    return status in ("sent", "paid")


def cmd_tcg_batch(args: argparse.Namespace) -> int:
    ids = _parse_ids(args.ids)
    updates: list[str] = []
    params: dict[str, Any] = {"ids": ids}

    if args.checkout_key is not None:
        updates.append("checkout_key = :checkout_key")
        params["checkout_key"] = _normalize_link(args.checkout_key)
    if args.tcg_order_id is not None:
        updates.append("tcg_order_id = :tcg_order_id")
        params["tcg_order_id"] = _normalize_link(args.tcg_order_id)
    if args.status:
        if args.status not in LOT_STATUSES:
            print(f"Invalid status: {args.status}", file=sys.stderr)
            return 1
        updates.append("status = :status")
        params["status"] = args.status

    if not updates:
        print("Provide --tcg-order-id and/or --checkout-key and/or --status", file=sys.stderr)
        return 1

    updates.append("updated_at = NOW()")
    sql = f"""
        UPDATE inventory_lots SET {", ".join(updates)}
        WHERE id = ANY(:ids)
        RETURNING id, name, seller, checkout_key, tcg_order_id, status, qty_on_hand
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

    status = args.status or "ordered"
    if status not in LOT_STATUSES:
        print(f"Invalid status: {status}", file=sys.stderr)
        return 1

    clauses = ["LOWER(seller) = LOWER(:seller)", "status NOT IN ('cancelled', 'depleted')"]
    params: dict[str, Any] = {"seller": seller, "tcg_order_id": tcg_order_id, "status": status}
    if not args.include_linked:
        clauses.append("tcg_order_id IS NULL")

    where_sql = " AND ".join(clauses)
    sql = f"""
        UPDATE inventory_lots
        SET tcg_order_id = :tcg_order_id,
            status = :status,
            updated_at = NOW()
        WHERE {where_sql}
        RETURNING id, name, seller, tcg_order_id, status, qty_on_hand
    """

    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    print(json.dumps({"count": len(rows), "updated": [dict(r) for r in rows]}, indent=2, default=str))
    return 0


def cmd_fulfill(args: argparse.Namespace) -> int:
    ids = _parse_ids(args.ids)
    ck_batch_id = _normalize_link(args.ck_batch_id)
    if not ck_batch_id:
        print("--ck-batch-id required", file=sys.stderr)
        return 1

    status = args.status or "sent"
    if status not in FULFILLMENT_STATUSES:
        print(f"Invalid fulfillment status: {status}", file=sys.stderr)
        return 1

    created: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        for lot_id in ids:
            lot = conn.execute(
                text(
                    """
                    SELECT id, name, qty_on_hand, ck_max_qty, ck_adj
                    FROM inventory_lots
                    WHERE id = :id
                    FOR UPDATE
                    """
                ),
                {"id": lot_id},
            ).mappings().first()
            if not lot:
                errors.append({"id": lot_id, "error": "not_found"})
                continue

            on_hand = int(lot["qty_on_hand"])
            if on_hand <= 0:
                errors.append({"id": lot_id, "error": "no_qty_on_hand"})
                continue

            if args.qty is not None:
                qty = int(args.qty)
            elif lot.get("ck_max_qty"):
                qty = min(on_hand, int(lot["ck_max_qty"]))
            else:
                qty = on_hand

            if qty < 1 or qty > on_hand:
                errors.append({"id": lot_id, "error": f"invalid_qty:{qty}"})
                continue

            ck_adj = args.ck_adj if args.ck_adj is not None else lot.get("ck_adj")
            row = conn.execute(
                text(
                    """
                    INSERT INTO ck_fulfillments (
                        inventory_lot_id, qty, ck_batch_id, ck_ref, ck_adj, status,
                        paid_amount, sent_at, paid_at, notes
                    ) VALUES (
                        :lot_id, :qty, :ck_batch_id, :ck_ref, :ck_adj, :status,
                        :paid_amount,
                        CASE WHEN :status IN ('sent', 'paid') THEN NOW() ELSE NULL END,
                        CASE WHEN :status = 'paid' THEN NOW() ELSE NULL END,
                        :notes
                    )
                    RETURNING id, inventory_lot_id, qty, ck_batch_id, status
                    """
                ),
                {
                    "lot_id": lot_id,
                    "qty": qty,
                    "ck_batch_id": ck_batch_id,
                    "ck_ref": _normalize_link(args.ck_ref),
                    "ck_adj": ck_adj,
                    "status": status,
                    "paid_amount": args.paid_amount,
                    "notes": args.notes,
                },
            ).mappings().first()

            if _decrements_inventory(status):
                next_on_hand = on_hand - qty
                lot_status = "depleted" if next_on_hand == 0 else "on_hand"
                conn.execute(
                    text(
                        """
                        UPDATE inventory_lots
                        SET qty_on_hand = :qty_on_hand,
                            status = :status,
                            updated_at = NOW()
                        WHERE id = :id
                        """
                    ),
                    {"id": lot_id, "qty_on_hand": next_on_hand, "status": lot_status},
                )

            created.append(dict(row))

    print(json.dumps({"created": created, "errors": errors}, indent=2, default=str))
    return 0 if not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Link inventory lots and CK fulfillments")
    sub = parser.add_subparsers(dest="command", required=True)

    p_tcg = sub.add_parser("tcg-batch", help="Set tcg_order_id on specific lot ids")
    p_tcg.add_argument("--ids", required=True, help="Comma-separated inventory lot ids")
    p_tcg.add_argument("--checkout-key", default=None)
    p_tcg.add_argument("--tcg-order-id", default=None)
    p_tcg.add_argument("--status", default="ordered", choices=LOT_STATUSES)
    p_tcg.set_defaults(func=cmd_tcg_batch)

    p_seller = sub.add_parser("seller", help="Link all lots from one seller to a TCG order #")
    p_seller.add_argument("--seller", required=True)
    p_seller.add_argument("--tcg-order-id", required=True)
    p_seller.add_argument("--status", default="ordered", choices=LOT_STATUSES)
    p_seller.add_argument("--include-linked", action="store_true")
    p_seller.set_defaults(func=cmd_seller)

    p_fulfill = sub.add_parser("fulfill", help="Create CK fulfillment rows for lot ids")
    p_fulfill.add_argument("--ids", required=True, help="Comma-separated inventory lot ids")
    p_fulfill.add_argument("--ck-batch-id", required=True)
    p_fulfill.add_argument("--qty", type=int, default=None, help="Per lot; default min(on_hand, ck_max)")
    p_fulfill.add_argument("--ck-adj", type=float, default=None, dest="ck_adj")
    p_fulfill.add_argument("--ck-ref", default=None)
    p_fulfill.add_argument("--paid-amount", type=float, default=None)
    p_fulfill.add_argument("--status", default="sent", choices=FULFILLMENT_STATUSES)
    p_fulfill.add_argument("--notes", default=None)
    p_fulfill.set_defaults(func=cmd_fulfill)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
