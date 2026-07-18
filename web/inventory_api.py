"""Inventory lots + CK fulfillments API."""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

try:
    from tcg_condition import effective_profit_qty, strip_seller_from_tcg_url
except ImportError:
    def effective_profit_qty(tcg_qty: float, ck_max_qty: float | None) -> float:
        qty = max(float(tcg_qty or 0), 0.0)
        if qty <= 0:
            return 0.0
        if ck_max_qty is None or ck_max_qty <= 0:
            return qty
        ck_cap = float(ck_max_qty)
        if qty <= ck_cap:
            return qty
        return min(qty, ck_cap * 2)

    def strip_seller_from_tcg_url(url: str | None) -> str | None:
        if not url or not str(url).strip():
            return url
        from urllib.parse import parse_qsl, urlencode, urlunparse

        raw = str(url).strip()
        try:
            parts = urlparse(raw)
        except Exception:
            return raw
        if not parts.query:
            return raw
        pairs = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() != "sellers"
        ]
        return urlunparse(
            (parts.scheme, parts.netloc, parts.path, parts.params, urlencode(pairs), parts.fragment)
        ) or raw


INVENTORY_STATUSES = ("ordered", "inbound", "on_hand", "depleted", "cancelled")
FULFILLMENT_STATUSES = ("planned", "packed", "sent", "paid", "rejected", "cancelled")
LIFECYCLE_STAGES = ("inbound", "need_to_sell", "to_pack", "to_ship", "awaiting_payment", "paid")
LIFECYCLE_LOT_STAGES = ("inbound", "need_to_sell")
LIFECYCLE_FULFILLMENT_STAGES = ("to_pack", "to_ship", "awaiting_payment", "paid")
NEED_TO_SELL_DAYS = 5
# CK buylist / "fulfilled today" calendar — match Pacific business day, not UTC CURRENT_DATE.
APP_TIMEZONE = "America/Los_Angeles"
FULFILLMENT_SORT = {
    "sent_desc": "sent_at DESC NULLS LAST, fulfillment_id DESC",
    "paid_desc": "paid_at DESC NULLS LAST, fulfillment_id DESC",
    "packed_desc": "packed_at DESC NULLS LAST, fulfillment_id DESC",
    "profit_desc": "fulfillment_profit DESC NULLS LAST, fulfillment_id DESC",
    "name": "name, fulfillment_id DESC",
}
INVENTORY_SORT = {
    "created_desc": "created_at DESC, id DESC",
    "profit_desc": "expected_profit DESC NULLS LAST, created_at DESC",
    "remaining_desc": "qty_on_hand DESC, created_at DESC",
    "name": "name, created_at DESC",
    "ordered_asc": "COALESCE(ordered_at, acquired_at, created_at::date) ASC, id ASC",
}
INVENTORY_FLOAT_COLS = (
    "seller_price", "shipping_price", "ck_cash", "ck_adj", "ck_cash_expected",
    "ck_cash_prior", "ck_cash_delta",
    "profit_per_copy", "expected_profit", "expected_roi",
    "realized_profit_paid", "realized_profit_sent", "at_risk_cost",
)
MANUAL_CONDITION_MULT: dict[str, float] = {
    "Near Mint": 1.0,
    "Lightly Played": 0.75,
    "Moderately Played": 0.5,
    "Heavily Played": 0.25,
    "Damaged": 0.0,
}

_engine: Engine | None = None
router = APIRouter()


class InventoryCreateItem(BaseModel):
    opportunity_id: int
    qty: int | None = None
    notes: str | None = None
    tcg_order_id: str | None = None
    status: str | None = "ordered"


class InventoryBatchCreate(BaseModel):
    items: list[InventoryCreateItem]


class InventoryManualCreate(BaseModel):
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
    ck_max_qty: int | None = None
    tcg_url: str | None = None
    ck_url: str | None = None
    seller_key: str | None = None
    product_id: str | None = None
    tcg_order_id: str | None = None
    notes: str | None = None
    status: str | None = "on_hand"
    ordered_at: date | None = None


class InventoryUpdate(BaseModel):
    status: str | None = None
    qty_original: int | None = None
    qty_on_hand: int | None = None
    notes: str | None = None
    checkout_key: str | None = None
    tcg_order_id: str | None = None
    name: str | None = None
    seller: str | None = None
    set_name: str | None = None
    finish: str | None = None
    condition: str | None = None
    seller_price: float | None = None
    shipping_price: float | None = None
    ck_cash: float | None = None
    ck_adj: float | None = None
    ck_cash_expected: float | None = None
    expected_ck_qty: int | None = None
    ck_max_qty: int | None = None
    tcg_url: str | None = None
    ck_url: str | None = None
    ordered_at: date | None = None


class FulfillmentCreate(BaseModel):
    qty: int
    ck_batch_id: str | None = None
    ck_ref: str | None = None
    ck_adj: float | None = None
    status: str | None = "planned"
    paid_amount: float | None = None
    notes: str | None = None


class FulfillmentBatchItem(BaseModel):
    inventory_lot_id: int
    qty: int
    ck_adj: float | None = None
    paid_amount: float | None = None
    notes: str | None = None


class FulfillmentBatchCreate(BaseModel):
    items: list[FulfillmentBatchItem]
    ck_ref: str | None = None
    ck_batch_id: str | None = None
    status: str | None = "sent"
    notes: str | None = None


class FulfillmentUpdate(BaseModel):
    qty: int | None = None
    ck_batch_id: str | None = None
    ck_ref: str | None = None
    ck_adj: float | None = None
    status: str | None = None
    paid_amount: float | None = None
    notes: str | None = None


class InventoryBatchLink(BaseModel):
    lot_ids: list[int]
    tcg_order_id: str | None = None
    status: str | None = None


class InventoryBatchDelete(BaseModel):
    lot_ids: list[int]


class InventorySellerLink(BaseModel):
    seller: str
    tcg_order_id: str
    status: str | None = "ordered"
    only_unlinked: bool = True


def init_inventory_api(engine: Engine) -> APIRouter:
    global _engine
    _engine = engine
    return router


def _normalize_link_field(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_inventory_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for ts_key in ("created_at", "updated_at"):
        if out.get(ts_key) is not None:
            out[ts_key] = out[ts_key].isoformat()
    if out.get("acquired_at") is not None:
        out["acquired_at"] = str(out["acquired_at"])
    if out.get("ordered_at") is not None:
        out["ordered_at"] = str(out["ordered_at"])
    if out.get("snapshot_date") is not None:
        out["snapshot_date"] = str(out["snapshot_date"])
    for key in INVENTORY_FLOAT_COLS:
        if out.get(key) is not None:
            out[key] = float(out[key])
    for key in (
        "id", "qty_original", "qty_on_hand", "qty_remaining", "qty_fulfilled",
        "qty_packing", "qty_fulfilled_paid", "expected_ck_qty", "ck_max_qty", "opportunity_id",
        "legacy_purchase_id",
    ):
        if out.get(key) is not None:
            out[key] = int(out[key])
    if out.get("ck_price_snapshot") is not None:
        out["ck_price_snapshot"] = str(out["ck_price_snapshot"])
    return out


def _normalize_fulfillment_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for ts_key in ("created_at", "updated_at", "packed_at", "sent_at", "paid_at"):
        if out.get(ts_key) is not None:
            out[ts_key] = out[ts_key].isoformat()
    for key in ("ck_adj", "paid_amount", "fulfillment_profit", "fulfillment_revenue", "fulfillment_cost"):
        if out.get(key) is not None:
            out[key] = float(out[key])
    for key in ("id", "inventory_lot_id", "qty", "fulfillment_id", "lot_id"):
        if out.get(key) is not None:
            out[key] = int(out[key])
    return out


def _fulfillment_detail_select() -> str:
    return """
        SELECT
            cf.id AS fulfillment_id,
            cf.inventory_lot_id AS lot_id,
            cf.qty AS fulfillment_qty,
            cf.ck_batch_id,
            cf.ck_ref,
            cf.ck_adj AS fulfillment_ck_adj,
            cf.status AS fulfillment_status,
            cf.paid_amount,
            cf.packed_at,
            cf.sent_at,
            cf.paid_at,
            cf.created_at,
            cf.notes AS fulfillment_notes,
            il.name,
            il.set_name,
            il.variant,
            il.finish,
            il.condition_display,
            il.seller,
            il.seller_price,
            il.shipping_price,
            il.ck_adj AS lot_ck_adj,
            il.qty_original,
            il.tcg_order_id,
            il.tcg_url,
            il.ck_url,
            il.status AS lot_status,
            ROUND(
                COALESCE(
                    cf.paid_amount,
                    cf.qty * COALESCE(cf.ck_adj, il.ck_adj, 0)
                ),
                2
            ) AS fulfillment_revenue,
            ROUND(
                cf.qty * COALESCE(il.seller_price, 0)
                + COALESCE(il.shipping_price, 0)
                  * (cf.qty::numeric / NULLIF(il.qty_original, 0)),
                2
            ) AS fulfillment_cost,
            ROUND(
                COALESCE(
                    cf.paid_amount,
                    cf.qty * COALESCE(cf.ck_adj, il.ck_adj, 0)
                )
                - (
                    cf.qty * COALESCE(il.seller_price, 0)
                    + COALESCE(il.shipping_price, 0)
                      * (cf.qty::numeric / NULLIF(il.qty_original, 0))
                ),
                2
            ) AS fulfillment_profit
        FROM ck_fulfillments cf
        JOIN inventory_lots il ON il.id = cf.inventory_lot_id
        WHERE cf.status NOT IN ('cancelled', 'rejected')
    """


def _sql_app_today() -> str:
    """Date in APP_TIMEZONE (CK 'today' for once-per-day max qty)."""
    return f"(CURRENT_TIMESTAMP AT TIME ZONE '{APP_TIMEZONE}')::date"


def _sql_ts_app_date(expr: str) -> str:
    """Calendar date of a timestamptz in APP_TIMEZONE."""
    return f"(({expr}) AT TIME ZONE '{APP_TIMEZONE}')::date"


def _need_to_sell_lot_predicate(table_id: str = "inventory_with_realized.id") -> str:
    """Stock ready to sell to CK — skip cards already fulfilled today.

    - On hand: eligible immediately (order date ignored).
    - Ordered / inbound: only after NEED_TO_SELL_DAYS from order date.
    CK only accepts max qty once per day, so any planned/sent/paid fulfillment whose
    effective date is today (APP_TIMEZONE) removes that card (same TCG product+finish,
    or name+finish if no product id) from this queue until tomorrow — including sibling lots.
    Lots with no current CK cash (not on latest buylist for this finish) are excluded —
    they cannot be sold to CK right now.
    qty_on_hand is free/unreserved stock only — planned pack lines already leave this queue.
    """
    lot_table = table_id.rsplit(".", 1)[0]
    today = _sql_app_today()
    event_day = (
        f"COALESCE("
        f"{_sql_ts_app_date('cf.sent_at')}, "
        f"{_sql_ts_app_date('cf.packed_at')}, "
        f"{_sql_ts_app_date('cf.created_at')}"
        f")"
    )
    order_day = (
        f"COALESCE("
        f"ordered_at, acquired_at, {_sql_ts_app_date('created_at')}"
        f")"
    )
    same_card = f"""
        (
          (
            {lot_table}.tcg_product_id IS NOT NULL
            AND sib.tcg_product_id = {lot_table}.tcg_product_id
            AND lower(COALESCE(sib.finish, '')) = lower(COALESCE({lot_table}.finish, ''))
          )
          OR (
            {lot_table}.tcg_product_id IS NULL
            AND sib.name = {lot_table}.name
            AND lower(COALESCE(sib.finish, '')) = lower(COALESCE({lot_table}.finish, ''))
          )
        )
    """
    return f"""
        status IN ('ordered', 'inbound', 'on_hand')
        AND qty_on_hand > 0
        AND ck_cash IS NOT NULL
        AND (
            status = 'on_hand'
            OR {order_day}
                <= ({today} - INTERVAL '{NEED_TO_SELL_DAYS} days')
        )
        AND NOT EXISTS (
            SELECT 1
            FROM ck_fulfillments cf
            JOIN inventory_lots sib ON sib.id = cf.inventory_lot_id
            WHERE cf.status IN ('planned', 'packed', 'sent', 'paid')
              AND {event_day} = {today}
              AND {same_card}
        )
    """


def _to_ship_lot_predicate(table_id: str = "inventory_with_realized.id") -> str:
    """On-hand stock with a CK order/batch assigned but not yet mailed."""
    return f"""
        status = 'on_hand' AND qty_on_hand > 0
        AND (
            NULLIF(BTRIM(legacy_ck_batch_id), '') IS NOT NULL
            OR EXISTS (
                SELECT 1 FROM ck_fulfillments cf
                WHERE cf.inventory_lot_id = {table_id}
                  AND cf.status IN ('planned', 'packed')
                  AND (
                      NULLIF(BTRIM(cf.ck_ref), '') IS NOT NULL
                      OR NULLIF(BTRIM(cf.ck_batch_id), '') IS NOT NULL
                  )
            )
        )
    """


def _apply_lifecycle_lot_filter(lifecycle: str, clauses: list[str]) -> None:
    if lifecycle == "inbound":
        clauses.append("status IN ('ordered', 'inbound')")
    elif lifecycle == "need_to_sell":
        clauses.append(_need_to_sell_lot_predicate())
    else:
        raise HTTPException(status_code=400, detail="Invalid lifecycle for lot list")


def _parse_order_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    return date.fromisoformat(text[:10])


def _recalc_inventory_economics(
    *,
    seller_price: float | None,
    shipping_price: float | None,
    ck_cash: float | None,
    ck_adj: float | None,
    condition_display: str | None,
    qty: int,
    buy_qty: int | None = None,
) -> dict[str, Any]:
    """Expected flip economics for `qty` sellable copies.

    `buy_qty` is the purchased lot size (for shipping allocation). When larger than
    `qty`, only a proportional share of shipping is charged — leftover copies are
    inventory, not a loss against expected profit.
    """
    shipping = float(shipping_price or 0)
    sell_qty = max(int(qty or 0), 0)
    purchased = max(int(buy_qty if buy_qty is not None else sell_qty), 1)
    ship_share = shipping * (sell_qty / purchased) if shipping and sell_qty else 0.0
    adj = ck_adj
    if adj is None and ck_cash is not None:
        mult = MANUAL_CONDITION_MULT.get(condition_display or "Near Mint", 1.0)
        adj = round(float(ck_cash) * mult, 2)
    profit_per_copy = None
    expected_profit = None
    expected_roi = None
    if adj is not None and seller_price is not None and sell_qty > 0:
        order_cost = float(seller_price) * sell_qty + ship_share
        expected_profit = round(float(adj) * sell_qty - order_cost, 2)
        profit_per_copy = round(float(adj) - float(seller_price), 2)
        expected_roi = round(expected_profit / order_cost * 100, 2) if order_cost > 0 else None
    return {
        "ck_adj": adj,
        "profit_per_copy": profit_per_copy,
        "expected_profit": expected_profit,
        "expected_roi": expected_roi,
        "shipping_price": round(shipping, 2) if shipping else None,
    }


def _parse_tcg_product_id(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"/product/(\d+)", url, re.I)
    return match.group(1) if match else None


def _clean_tcg_product_id(value: str | None) -> str | None:
    if value is None:
        return None
    text_val = str(value).strip().replace(".0", "")
    if not text_val or text_val.lower() in {"nan", "none"}:
        return None
    if text_val.startswith("manual:"):
        return None
    try:
        return str(int(float(text_val)))
    except (ValueError, TypeError):
        return None


def _resolve_tcg_product_id(
    stored_id: str | None = None,
    tcg_url: str | None = None,
) -> str | None:
    """Canonical TCGplayer product id for CK buylist matching."""
    return _clean_tcg_product_id(stored_id) or _parse_tcg_product_id(tcg_url)


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


def _manual_product_id(body: InventoryManualCreate) -> str:
    if body.product_id and body.product_id.strip():
        return body.product_id.strip()
    from_url = _parse_tcg_product_id(body.tcg_url)
    if from_url:
        return from_url
    slug = re.sub(r"[^a-z0-9]+", "-", body.name.strip().lower())[:48].strip("-") or "card"
    seller_bit = re.sub(r"[^a-z0-9]+", "-", body.seller.strip().lower())[:24].strip("-") or "seller"
    return f"manual:{slug}:{seller_bit}"


def _get_opportunity_by_id(conn, opportunity_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id, snapshot_date::text AS snapshot_date, product_id, name, set_name,
                   variant, finish, condition_display, condition_raw,
                   ck_cash, ck_adj, ck_max_qty, seller_price, shipping_price,
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


def _active_inventory_exists_for_keys(
    conn,
    product_id: str,
    finish: str | None,
    condition_raw: str | None,
    seller_key: str | None,
    seller: str | None = None,
) -> bool:
    """True if an active lot already matches this listing identity.

    Prefer seller_key when present. When it's blank (common for manual / older rows),
    also require seller name so two sellers of the same TCG product don't collide.
    """
    key = (seller_key or "").strip()
    seller_name = (seller or "").strip()
    if key:
        return bool(
            conn.execute(
                text(
                    """
                    SELECT 1 FROM inventory_lots
                    WHERE product_id = :product_id
                      AND COALESCE(finish, '') = COALESCE(:finish, '')
                      AND COALESCE(condition_raw, '') = COALESCE(:condition_raw, '')
                      AND COALESCE(seller_key, '') = :seller_key
                      AND status IN ('ordered', 'inbound', 'on_hand')
                    LIMIT 1
                    """
                ),
                {
                    "product_id": product_id,
                    "finish": finish,
                    "condition_raw": condition_raw,
                    "seller_key": key,
                },
            ).scalar()
        )

    # No seller_key — fall back to seller display name so different sellers don't block each other.
    if seller_name:
        return bool(
            conn.execute(
                text(
                    """
                    SELECT 1 FROM inventory_lots
                    WHERE product_id = :product_id
                      AND COALESCE(finish, '') = COALESCE(:finish, '')
                      AND COALESCE(condition_raw, '') = COALESCE(:condition_raw, '')
                      AND COALESCE(NULLIF(BTRIM(seller_key), ''), '') = ''
                      AND LOWER(BTRIM(COALESCE(seller, ''))) = LOWER(:seller)
                      AND status IN ('ordered', 'inbound', 'on_hand')
                    LIMIT 1
                    """
                ),
                {
                    "product_id": product_id,
                    "finish": finish,
                    "condition_raw": condition_raw,
                    "seller": seller_name,
                },
            ).scalar()
        )

    return bool(
        conn.execute(
            text(
                """
                SELECT 1 FROM inventory_lots
                WHERE product_id = :product_id
                  AND COALESCE(finish, '') = COALESCE(:finish, '')
                  AND COALESCE(condition_raw, '') = COALESCE(:condition_raw, '')
                  AND COALESCE(NULLIF(BTRIM(seller_key), ''), '') = ''
                  AND COALESCE(NULLIF(BTRIM(seller), ''), '') = ''
                  AND status IN ('ordered', 'inbound', 'on_hand')
                LIMIT 1
                """
            ),
            {
                "product_id": product_id,
                "finish": finish,
                "condition_raw": condition_raw,
            },
        ).scalar()
    )


def _inventory_view_row(conn, lot_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        text("SELECT * FROM inventory_with_realized WHERE id = :id"),
        {"id": lot_id},
    ).mappings().first()
    return _normalize_inventory_row(dict(row)) if row else None


def _insert_inventory_lot(conn, fields: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            INSERT INTO inventory_lots (
                status, qty_original, qty_on_hand, opportunity_id, snapshot_date,
                product_id, tcg_product_id, name, set_name, variant, finish, condition_display,
                condition_raw, seller, seller_key, seller_price, shipping_price,
                ck_cash, ck_cash_expected, ck_adj, ck_max_qty, expected_ck_qty, profit_per_copy,
                expected_profit, expected_roi, tcg_url, ck_url, notes, checkout_key,
                tcg_order_id, acquired_at, ordered_at
            ) VALUES (
                :status, :qty_original, :qty_on_hand, :opportunity_id, :snapshot_date,
                :product_id, :tcg_product_id, :name, :set_name, :variant, :finish, :condition_display,
                :condition_raw, :seller, :seller_key, :seller_price, :shipping_price,
                :ck_cash, :ck_cash_expected, :ck_adj, :ck_max_qty, :expected_ck_qty, :profit_per_copy,
                :expected_profit, :expected_roi, :tcg_url, :ck_url, :notes, :checkout_key,
                :tcg_order_id, :acquired_at, :ordered_at
            )
            RETURNING id
            """
        ),
        fields,
    ).scalar()
    view_row = _inventory_view_row(conn, int(row))
    if not view_row:
        raise HTTPException(status_code=500, detail="Failed to load created inventory lot")
    return view_row


def _build_lot_fields_from_opportunity(
    opp: dict[str, Any],
    qty: int,
    notes: str | None,
    tcg_order_id: str | None,
    status: str,
) -> dict[str, Any]:
    ck_max = opp.get("ck_max_qty")
    ck_max_int = int(ck_max) if ck_max is not None else None
    expected_ck_qty = int(effective_profit_qty(qty, ck_max_int))
    econ = _recalc_inventory_economics(
        seller_price=float(opp["seller_price"]) if opp.get("seller_price") is not None else None,
        shipping_price=opp.get("shipping_price"),
        ck_cash=float(opp["ck_cash"]) if opp.get("ck_cash") is not None else None,
        ck_adj=float(opp["ck_adj"]) if opp.get("ck_adj") is not None else None,
        condition_display=opp.get("condition_display"),
        qty=expected_ck_qty,
        buy_qty=qty,
    )
    lot_status = status if status in INVENTORY_STATUSES else "ordered"
    if lot_status == "depleted":
        lot_status = "ordered"
    tcg_url = strip_seller_from_tcg_url(opp.get("tcg_url"))
    tcg_product_id = _resolve_tcg_product_id(opp.get("product_id"), tcg_url)
    product_id = tcg_product_id or opp["product_id"]
    order_day = date.today()
    return {
        "status": lot_status,
        "qty_original": qty,
        "qty_on_hand": qty,
        "opportunity_id": opp["id"],
        "snapshot_date": opp["snapshot_date"],
        "product_id": product_id,
        "tcg_product_id": tcg_product_id,
        "name": opp["name"],
        "set_name": opp.get("set_name"),
        "variant": opp.get("variant"),
        "finish": opp.get("finish"),
        "condition_display": opp.get("condition_display"),
        "condition_raw": opp.get("condition_raw"),
        "seller": opp.get("seller"),
        "seller_key": opp.get("seller_key"),
        "seller_price": opp.get("seller_price"),
        "shipping_price": econ["shipping_price"] if econ["shipping_price"] is not None else opp.get("shipping_price"),
        "ck_cash": opp.get("ck_cash"),
        "ck_cash_expected": opp.get("ck_cash"),
        "ck_adj": econ["ck_adj"] if econ["ck_adj"] is not None else opp.get("ck_adj"),
        "ck_max_qty": ck_max_int,
        "expected_ck_qty": expected_ck_qty,
        "profit_per_copy": econ["profit_per_copy"] if econ["profit_per_copy"] is not None else opp.get("profit_per_copy"),
        "expected_profit": econ["expected_profit"] if econ["expected_profit"] is not None else opp.get("order_profit"),
        "expected_roi": econ["expected_roi"] if econ["expected_roi"] is not None else opp.get("order_roi"),
        "tcg_url": tcg_url,
        "ck_url": opp.get("ck_url"),
        "notes": notes,
        "checkout_key": None,
        "tcg_order_id": _normalize_link_field(tcg_order_id),
        "acquired_at": order_day,
        "ordered_at": order_day,
    }


def _fulfillment_decrements_inventory(status: str) -> bool:
    """Statuses that leave free on-hand stock (mutually exclusive with inbound/on-hand queues)."""
    return status in ("planned", "packed", "sent", "paid")


def _apply_fulfillment_qty_change(
    conn,
    lot_id: int,
    old_status: str | None,
    new_status: str,
    old_qty: int,
    new_qty: int,
) -> None:
    old_dec = _fulfillment_decrements_inventory(old_status or "planned")
    new_dec = _fulfillment_decrements_inventory(new_status)
    delta = 0
    if old_dec:
        delta += old_qty
    if new_dec:
        delta -= new_qty
    if delta == 0:
        return
    row = conn.execute(
        text("SELECT qty_on_hand, status FROM inventory_lots WHERE id = :id FOR UPDATE"),
        {"id": lot_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Inventory lot not found")
    next_qty = int(row["qty_on_hand"]) + delta
    if next_qty < 0:
        raise HTTPException(status_code=400, detail="Not enough free stock for this fulfillment")
    cur_status = row["status"]
    if next_qty == 0:
        lot_status = "depleted"
    elif cur_status in ("ordered", "inbound", "on_hand"):
        # Keep acquisition stage for remaining free copies.
        lot_status = cur_status
    else:
        lot_status = "on_hand"
    conn.execute(
        text(
            """
            UPDATE inventory_lots
            SET qty_on_hand = :qty_on_hand,
                status = CASE WHEN status = 'cancelled' THEN status ELSE :lot_status END,
                updated_at = NOW()
            WHERE id = :id
            """
        ),
        {"id": lot_id, "qty_on_hand": next_qty, "lot_status": lot_status},
    )


@router.get("/api/inventory")
def list_inventory(
    lifecycle: str = Query("", description="inbound or to_ship lifecycle tab"),
    status: str = Query("", description="Filter by lot status"),
    seller: str = Query("", description="Seller name contains"),
    q: str = Query("", description="Card name search"),
    tcg_order_id: str = Query("", description="Exact tcg_order_id"),
    ck_batch_id: str = Query("", description="Lots with fulfillment in this CK batch"),
    unlinked: bool = Query(False, description="Only lots missing tcg_order_id"),
    has_remaining: bool = Query(False, description="Only lots with qty_on_hand > 0"),
    sort: str = Query("created_desc"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    clauses = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if lifecycle.strip():
        stage = lifecycle.strip()
        if stage not in LIFECYCLE_LOT_STAGES:
            raise HTTPException(
                status_code=400,
                detail=f"lifecycle must be one of: {', '.join(LIFECYCLE_LOT_STAGES)}",
            )
        _apply_lifecycle_lot_filter(stage, clauses)
    elif status.strip():
        if status.strip() not in INVENTORY_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        clauses.append("status = :status")
        params["status"] = status.strip()
    if seller.strip():
        clauses.append("seller ILIKE :seller")
        params["seller"] = f"%{seller.strip()}%"
    if q.strip():
        clauses.append("name ILIKE :q")
        params["q"] = f"%{q.strip()}%"
    if tcg_order_id.strip():
        clauses.append("tcg_order_id = :tcg_order_id")
        params["tcg_order_id"] = tcg_order_id.strip()
    if ck_batch_id.strip():
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM ck_fulfillments cf
                WHERE cf.inventory_lot_id = inventory_with_realized.id
                  AND cf.ck_batch_id = :ck_batch_id
            )
            """
        )
        params["ck_batch_id"] = ck_batch_id.strip()
    if has_remaining:
        clauses.append("qty_on_hand > 0")
    if unlinked:
        clauses.append("tcg_order_id IS NULL")

    where_sql = " AND ".join(clauses)
    default_sort = "ordered_asc" if lifecycle.strip() == "need_to_sell" else "created_desc"
    order_by = INVENTORY_SORT.get(sort, INVENTORY_SORT[default_sort])
    if lifecycle.strip() == "need_to_sell" and sort == "created_desc":
        order_by = INVENTORY_SORT["ordered_asc"]
    sql = f"""
        SELECT * FROM inventory_with_realized
        WHERE {where_sql}
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
    """
    count_sql = f"SELECT COUNT(*) AS n FROM inventory_with_realized WHERE {where_sql}"

    with _engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        total = conn.execute(text(count_sql), params).scalar() or 0

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "lifecycle": lifecycle.strip() or None,
        "results": [_normalize_inventory_row(dict(r)) for r in rows],
    }


@router.get("/api/inventory/fulfillments")
def list_inventory_fulfillments(
    lifecycle: str = Query(..., description="to_pack, to_ship, awaiting_payment, or paid"),
    q: str = Query("", description="Card name search"),
    seller: str = Query("", description="Seller name contains"),
    ck_batch_id: str = Query("", description="Exact CK batch id"),
    sort: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    stage = lifecycle.strip()
    if stage not in LIFECYCLE_FULFILLMENT_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"lifecycle must be one of: {', '.join(LIFECYCLE_FULFILLMENT_STAGES)}",
        )

    status_map = {
        "to_pack": "planned",
        "to_ship": "packed",
        "awaiting_payment": "sent",
        "paid": "paid",
    }
    clauses = ["fulfillment_status = :fulfillment_status"]
    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "fulfillment_status": status_map[stage],
    }

    if q.strip():
        clauses.append("name ILIKE :q")
        params["q"] = f"%{q.strip()}%"
    if seller.strip():
        clauses.append("seller ILIKE :seller")
        params["seller"] = f"%{seller.strip()}%"
    if ck_batch_id.strip():
        clauses.append("ck_batch_id = :ck_batch_id")
        params["ck_batch_id"] = ck_batch_id.strip()

    where_sql = " AND ".join(clauses)
    default_sort = (
        "paid_desc"
        if stage == "paid"
        else ("name" if stage in ("to_pack", "to_ship") else "sent_desc")
    )
    order_by = FULFILLMENT_SORT.get(sort or default_sort, FULFILLMENT_SORT[default_sort])
    base = _fulfillment_detail_select()
    sql = f"""
        SELECT * FROM ({base}) fulfillment_detail
        WHERE {where_sql}
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
    """
    count_sql = f"""
        SELECT COUNT(*) AS n FROM ({base}) fulfillment_detail
        WHERE {where_sql}
    """
    totals_sql = f"""
        SELECT
            COUNT(*) AS row_count,
            COALESCE(SUM(fulfillment_revenue), 0) AS total_revenue,
            COALESCE(SUM(fulfillment_cost), 0) AS total_cost,
            COALESCE(SUM(fulfillment_profit), 0) AS total_profit
        FROM ({base}) fulfillment_detail
        WHERE {where_sql}
    """

    with _engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        total = conn.execute(text(count_sql), params).scalar() or 0
        totals = conn.execute(text(totals_sql), params).mappings().first()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort or default_sort,
        "lifecycle": stage,
        "totals": {
            "row_count": int(totals["row_count"]) if totals else 0,
            "total_revenue": float(totals["total_revenue"]) if totals else 0.0,
            "total_cost": float(totals["total_cost"]) if totals else 0.0,
            "total_profit": float(totals["total_profit"]) if totals else 0.0,
        },
        "results": [_normalize_fulfillment_row(dict(r)) for r in rows],
    }


@router.get("/api/inventory/lifecycle-summary")
def inventory_lifecycle_summary() -> dict[str, Any]:
    with _engine.connect() as conn:
        inbound = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM inventory_lots
                WHERE status IN ('ordered', 'inbound')
                """
            )
        ).scalar() or 0
        to_pack = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM ck_fulfillments
                WHERE status = 'planned'
                """
            )
        ).scalar() or 0
        to_ship = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM ck_fulfillments
                WHERE status = 'packed'
                """
            )
        ).scalar() or 0
        need_to_sell = conn.execute(
            text(
                f"""
                SELECT COUNT(*) FROM inventory_lots
                WHERE {_need_to_sell_lot_predicate('inventory_lots.id')}
                """
            )
        ).scalar() or 0
        awaiting = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM ck_fulfillments
                WHERE status = 'sent'
                """
            )
        ).scalar() or 0
        paid_row = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS n,
                    COALESCE(SUM(COALESCE(paid_amount, qty * COALESCE(ck_adj, 0))), 0) AS revenue,
                    COALESCE(SUM(paid_amount), 0) AS paid_recorded
                FROM ck_fulfillments
                WHERE status = 'paid'
                """
            )
        ).mappings().first()
        paid_profit = conn.execute(
            text(
                f"""
                SELECT COALESCE(SUM(fulfillment_profit), 0) AS total_profit
                FROM ({_fulfillment_detail_select()}) fd
                WHERE fulfillment_status = 'paid'
                """
            )
        ).scalar() or 0
        total_lots = conn.execute(
            text("SELECT COUNT(*) FROM inventory_lots WHERE status != 'cancelled'")
        ).scalar() or 0

    return {
        "total_lots": int(total_lots),
        "inbound": int(inbound),
        "to_pack": int(to_pack),
        "to_ship": int(to_ship),
        "need_to_sell": int(need_to_sell),
        "awaiting_payment": int(awaiting),
        "paid": int(paid_row["n"]) if paid_row else 0,
        "paid_revenue": float(paid_row["revenue"]) if paid_row else 0.0,
        "paid_profit": float(paid_profit),
        "need_to_sell_days": NEED_TO_SELL_DAYS,
    }


@router.get("/api/inventory/ck-returns")
def inventory_ck_returns(
    month: str = Query("", description="YYYY-MM month filter; empty = all months"),
    statuses: str = Query(
        "planned,packed,sent,paid",
        description="Comma-separated fulfillment statuses (default: planned,packed,sent,paid)",
    ),
) -> dict[str, Any]:
    """Monthly cost / expected CK revenue / profit for lines committed toward CK."""
    allowed = {"planned", "packed", "sent", "paid"}
    status_list = [s.strip().lower() for s in statuses.split(",") if s.strip()]
    status_list = [s for s in status_list if s in allowed]
    if not status_list:
        status_list = ["planned", "packed", "sent", "paid"]

    month_key = month.strip()
    if month_key and not re.fullmatch(r"\d{4}-\d{2}", month_key):
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")

    status_params = {f"st{i}": s for i, s in enumerate(status_list)}
    status_in = ", ".join(f":st{i}" for i in range(len(status_list)))
    # Event date: when stock moved toward CK / was paid.
    event_expr = "COALESCE(fd.sent_at, fd.packed_at, fd.paid_at, fd.created_at)"
    detail = _fulfillment_detail_select()

    month_clause = ""
    params: dict[str, Any] = dict(status_params)
    if month_key:
        month_clause = f"AND to_char({event_expr}, 'YYYY-MM') = :month"
        params["month"] = month_key

    with _engine.connect() as conn:
        months = [
            str(r[0])
            for r in conn.execute(
                text(
                    f"""
                    SELECT to_char({event_expr}, 'YYYY-MM') AS m
                    FROM ({detail}) fd
                    WHERE fd.fulfillment_status IN ({status_in})
                    GROUP BY 1
                    ORDER BY 1 DESC
                    """
                ),
                status_params,
            ).all()
            if r[0]
        ]

        by_month_rows = conn.execute(
            text(
                f"""
                SELECT
                    to_char({event_expr}, 'YYYY-MM') AS month,
                    COUNT(*) AS lines,
                    COALESCE(SUM(fd.fulfillment_qty), 0) AS qty,
                    COALESCE(SUM(fd.fulfillment_cost), 0) AS cost,
                    COALESCE(SUM(fd.fulfillment_revenue), 0) AS revenue,
                    COALESCE(SUM(fd.fulfillment_profit), 0) AS profit,
                    COALESCE(SUM(fd.fulfillment_qty) FILTER (WHERE fd.fulfillment_status = 'planned'), 0) AS qty_planned,
                    COALESCE(SUM(fd.fulfillment_qty) FILTER (WHERE fd.fulfillment_status = 'packed'), 0) AS qty_packed,
                    COALESCE(SUM(fd.fulfillment_qty) FILTER (WHERE fd.fulfillment_status = 'sent'), 0) AS qty_sent,
                    COALESCE(SUM(fd.fulfillment_qty) FILTER (WHERE fd.fulfillment_status = 'paid'), 0) AS qty_paid,
                    COALESCE(SUM(fd.fulfillment_revenue) FILTER (WHERE fd.fulfillment_status = 'paid'), 0) AS paid_revenue,
                    COALESCE(SUM(fd.fulfillment_profit) FILTER (WHERE fd.fulfillment_status = 'paid'), 0) AS paid_profit
                FROM ({detail}) fd
                WHERE fd.fulfillment_status IN ({status_in})
                GROUP BY 1
                ORDER BY 1 ASC
                """
            ),
            status_params,
        ).mappings().all()

        summary = conn.execute(
            text(
                f"""
                SELECT
                    COUNT(*) AS lines,
                    COALESCE(SUM(fd.fulfillment_qty), 0) AS qty,
                    COALESCE(SUM(fd.fulfillment_cost), 0) AS cost,
                    COALESCE(SUM(fd.fulfillment_revenue), 0) AS revenue,
                    COALESCE(SUM(fd.fulfillment_profit), 0) AS profit,
                    COALESCE(SUM(fd.fulfillment_revenue) FILTER (WHERE fd.fulfillment_status = 'paid'), 0) AS paid_revenue,
                    COALESCE(SUM(fd.fulfillment_profit) FILTER (WHERE fd.fulfillment_status = 'paid'), 0) AS paid_profit
                FROM ({detail}) fd
                WHERE fd.fulfillment_status IN ({status_in})
                {month_clause}
                """
            ),
            params,
        ).mappings().first()

        by_status_rows = conn.execute(
            text(
                f"""
                SELECT
                    fd.fulfillment_status AS status,
                    COUNT(*) AS lines,
                    COALESCE(SUM(fd.fulfillment_qty), 0) AS qty,
                    COALESCE(SUM(fd.fulfillment_cost), 0) AS cost,
                    COALESCE(SUM(fd.fulfillment_revenue), 0) AS revenue,
                    COALESCE(SUM(fd.fulfillment_profit), 0) AS profit
                FROM ({detail}) fd
                WHERE fd.fulfillment_status IN ({status_in})
                {month_clause}
                GROUP BY 1
                ORDER BY CASE fd.fulfillment_status
                    WHEN 'planned' THEN 1
                    WHEN 'packed' THEN 2
                    WHEN 'sent' THEN 3
                    WHEN 'paid' THEN 4
                    ELSE 5
                END
                """
            ),
            params,
        ).mappings().all()

        top_cards = conn.execute(
            text(
                f"""
                SELECT
                    fd.name,
                    fd.finish,
                    COUNT(*) AS lines,
                    COALESCE(SUM(fd.fulfillment_qty), 0) AS qty,
                    COALESCE(SUM(fd.fulfillment_cost), 0) AS cost,
                    COALESCE(SUM(fd.fulfillment_revenue), 0) AS revenue,
                    COALESCE(SUM(fd.fulfillment_profit), 0) AS profit
                FROM ({detail}) fd
                WHERE fd.fulfillment_status IN ({status_in})
                {month_clause}
                GROUP BY fd.name, fd.finish
                ORDER BY profit DESC NULLS LAST, revenue DESC
                LIMIT 25
                """
            ),
            params,
        ).mappings().all()

    def _money(row: dict[str, Any], *keys: str) -> dict[str, Any]:
        out = dict(row)
        for k in keys:
            if out.get(k) is not None:
                out[k] = float(out[k])
        for k in ("lines", "qty", "qty_planned", "qty_packed", "qty_sent", "qty_paid"):
            if out.get(k) is not None:
                out[k] = int(out[k])
        return out

    money_keys = ("cost", "revenue", "profit", "paid_revenue", "paid_profit")
    summary_out = _money(dict(summary or {}), *money_keys)
    cost = float(summary_out.get("cost") or 0)
    profit = float(summary_out.get("profit") or 0)
    summary_out["roi_pct"] = round(profit / cost * 100, 2) if cost > 0 else None

    return {
        "statuses": status_list,
        "month": month_key or None,
        "months": months,
        "summary": summary_out,
        "by_month": [_money(dict(r), *money_keys) for r in by_month_rows],
        "by_status": [_money(dict(r), *money_keys) for r in by_status_rows],
        "top_cards": [_money(dict(r), *money_keys) for r in top_cards],
    }


def _open_book_positions_sql() -> str:
    """Free stock + unpaid fulfillments (excludes paid). Buy-month for bucketing."""
    buy_month = f"""
        to_char(
            COALESCE(
                il.ordered_at,
                il.acquired_at,
                ({_sql_ts_app_date('il.created_at')})
            ),
            'YYYY-MM'
        )
    """
    free_cost = """
        ROUND(
            il.qty_on_hand * COALESCE(il.seller_price, 0)
            + COALESCE(il.shipping_price, 0)
              * (il.qty_on_hand::numeric / NULLIF(il.qty_original, 0)),
            2
        )
    """
    free_revenue = """
        ROUND(il.qty_on_hand * COALESCE(il.ck_adj, 0), 2)
    """
    detail = _fulfillment_detail_select()
    return f"""
        SELECT
            'free'::text AS stage,
            il.id AS lot_id,
            il.name,
            il.finish,
            il.qty_on_hand AS qty,
            {free_cost} AS cost,
            {free_revenue} AS revenue,
            ROUND(({free_revenue}) - ({free_cost}), 2) AS profit,
            {buy_month} AS buy_month
        FROM inventory_lots il
        WHERE il.status != 'cancelled'
          AND il.qty_on_hand > 0

        UNION ALL

        SELECT
            CASE fd.fulfillment_status
                WHEN 'planned' THEN 'planned'
                WHEN 'packed' THEN 'packed'
                WHEN 'sent' THEN 'sent'
                ELSE fd.fulfillment_status
            END AS stage,
            fd.lot_id,
            fd.name,
            fd.finish,
            fd.fulfillment_qty AS qty,
            fd.fulfillment_cost AS cost,
            fd.fulfillment_revenue AS revenue,
            fd.fulfillment_profit AS profit,
            to_char(
                COALESCE(
                    fd_lot.ordered_at,
                    fd_lot.acquired_at,
                    ({_sql_ts_app_date('fd_lot.created_at')})
                ),
                'YYYY-MM'
            ) AS buy_month
        FROM ({detail}) fd
        JOIN inventory_lots fd_lot ON fd_lot.id = fd.lot_id
        WHERE fd.fulfillment_status IN ('planned', 'packed', 'sent')
    """


@router.get("/api/inventory/ck-returns/open")
def inventory_ck_returns_open(
    month: str = Query("", description="YYYY-MM buy-month filter; empty = all"),
) -> dict[str, Any]:
    """Cost / expected CK / profit for inventory not yet paid (free + planned/packed/sent)."""
    month_key = month.strip()
    if month_key and not re.fullmatch(r"\d{4}-\d{2}", month_key):
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")

    base = _open_book_positions_sql()
    month_clause = ""
    params: dict[str, Any] = {}
    if month_key:
        month_clause = "AND buy_month = :month"
        params["month"] = month_key

    with _engine.connect() as conn:
        months = [
            str(r[0])
            for r in conn.execute(
                text(
                    f"""
                    SELECT buy_month
                    FROM ({base}) ob
                    WHERE buy_month IS NOT NULL
                    GROUP BY 1
                    ORDER BY 1 DESC
                    """
                )
            ).all()
            if r[0]
        ]

        by_month_rows = conn.execute(
            text(
                f"""
                SELECT
                    buy_month AS month,
                    COUNT(*) AS lines,
                    COALESCE(SUM(qty), 0) AS qty,
                    COALESCE(SUM(cost), 0) AS cost,
                    COALESCE(SUM(revenue), 0) AS revenue,
                    COALESCE(SUM(profit), 0) AS profit
                FROM ({base}) ob
                WHERE buy_month IS NOT NULL
                GROUP BY 1
                ORDER BY 1 ASC
                """
            )
        ).mappings().all()

        summary = conn.execute(
            text(
                f"""
                SELECT
                    COUNT(*) AS lines,
                    COALESCE(SUM(qty), 0) AS qty,
                    COALESCE(SUM(cost), 0) AS cost,
                    COALESCE(SUM(revenue), 0) AS revenue,
                    COALESCE(SUM(profit), 0) AS profit
                FROM ({base}) ob
                WHERE 1=1
                {month_clause}
                """
            ),
            params,
        ).mappings().first()

        by_stage_rows = conn.execute(
            text(
                f"""
                SELECT
                    stage,
                    COUNT(*) AS lines,
                    COALESCE(SUM(qty), 0) AS qty,
                    COALESCE(SUM(cost), 0) AS cost,
                    COALESCE(SUM(revenue), 0) AS revenue,
                    COALESCE(SUM(profit), 0) AS profit
                FROM ({base}) ob
                WHERE 1=1
                {month_clause}
                GROUP BY stage
                ORDER BY CASE stage
                    WHEN 'free' THEN 1
                    WHEN 'planned' THEN 2
                    WHEN 'packed' THEN 3
                    WHEN 'sent' THEN 4
                    ELSE 5
                END
                """
            ),
            params,
        ).mappings().all()

        top_cards = conn.execute(
            text(
                f"""
                SELECT
                    name,
                    finish,
                    COUNT(*) AS lines,
                    COALESCE(SUM(qty), 0) AS qty,
                    COALESCE(SUM(cost), 0) AS cost,
                    COALESCE(SUM(revenue), 0) AS revenue,
                    COALESCE(SUM(profit), 0) AS profit
                FROM ({base}) ob
                WHERE 1=1
                {month_clause}
                GROUP BY name, finish
                ORDER BY profit DESC NULLS LAST, revenue DESC
                LIMIT 25
                """
            ),
            params,
        ).mappings().all()

    def _money(row: dict[str, Any], *keys: str) -> dict[str, Any]:
        out = dict(row)
        for k in keys:
            if out.get(k) is not None:
                out[k] = float(out[k])
        for k in ("lines", "qty"):
            if out.get(k) is not None:
                out[k] = int(out[k])
        return out

    money_keys = ("cost", "revenue", "profit")
    summary_out = _money(dict(summary or {}), *money_keys)
    cost = float(summary_out.get("cost") or 0)
    profit = float(summary_out.get("profit") or 0)
    summary_out["roi_pct"] = round(profit / cost * 100, 2) if cost > 0 else None

    return {
        "month": month_key or None,
        "months": months,
        "summary": summary_out,
        "by_month": [_money(dict(r), *money_keys) for r in by_month_rows],
        "by_stage": [_money(dict(r), *money_keys) for r in by_stage_rows],
        "top_cards": [_money(dict(r), *money_keys) for r in top_cards],
    }


@router.get("/api/inventory/linking-summary")
def inventory_linking_summary() -> dict[str, Any]:
    with _engine.connect() as conn:
        unlinked = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM inventory_lots
                WHERE tcg_order_id IS NULL AND status NOT IN ('cancelled', 'depleted')
                """
            )
        ).scalar() or 0
        remaining = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM inventory_lots
                WHERE qty_on_hand > 0 AND status NOT IN ('cancelled')
                """
            )
        ).scalar() or 0
        tcg_orders = conn.execute(
            text(
                """
                SELECT tcg_order_id, COUNT(*) AS n, MAX(seller) AS seller
                FROM inventory_lots
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
                SELECT ck_batch_id, COUNT(*) AS n, SUM(qty) AS total_qty
                FROM ck_fulfillments
                WHERE ck_batch_id IS NOT NULL AND status NOT IN ('cancelled', 'rejected')
                GROUP BY ck_batch_id
                ORDER BY MAX(created_at) DESC
                LIMIT 100
                """
            )
        ).mappings().all()

    return {
        "unlinked_active": int(unlinked),
        "remaining_lots": int(remaining),
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
                "total_qty": int(r["total_qty"]) if r["total_qty"] is not None else 0,
            }
            for r in ck_batches
        ],
    }


@router.post("/api/inventory/batch-link")
def batch_link_inventory(body: InventoryBatchLink) -> dict[str, Any]:
    if not body.lot_ids:
        raise HTTPException(status_code=400, detail="lot_ids required")
    if not body.tcg_order_id:
        raise HTTPException(status_code=400, detail="tcg_order_id required")

    status = body.status or "ordered"
    if status not in INVENTORY_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    with _engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                UPDATE inventory_lots
                SET tcg_order_id = :tcg_order_id,
                    status = :status,
                    ordered_at = COALESCE(ordered_at, CURRENT_DATE),
                    acquired_at = COALESCE(acquired_at, CURRENT_DATE),
                    updated_at = NOW()
                WHERE id = ANY(:ids)
                RETURNING id, name, tcg_order_id
                """
            ),
            {
                "ids": body.lot_ids,
                "tcg_order_id": _normalize_link_field(body.tcg_order_id),
                "status": status,
            },
        ).mappings().all()

    updated = [dict(r) for r in rows]
    missing = sorted(set(body.lot_ids) - {int(r["id"]) for r in updated})
    return {"updated": updated, "count": len(updated), "missing_ids": missing}


@router.post("/api/inventory/batch-delete")
def batch_delete_inventory(body: InventoryBatchDelete) -> dict[str, Any]:
    if not body.lot_ids:
        raise HTTPException(status_code=400, detail="lot_ids required")
    with _engine.begin() as conn:
        rows = conn.execute(
            text("DELETE FROM inventory_lots WHERE id = ANY(:ids) RETURNING id, name"),
            {"ids": body.lot_ids},
        ).mappings().all()
    return {
        "deleted": [{"id": r["id"], "name": r["name"]} for r in rows],
        "count": len(rows),
        "missing_ids": sorted(set(body.lot_ids) - {int(r["id"]) for r in rows}),
    }


@router.post("/api/inventory/link-seller")
def link_seller_inventory(body: InventorySellerLink) -> dict[str, Any]:
    """Link all inventory lots from one seller to a TCG seller order #."""
    seller = body.seller.strip()
    tcg_order_id = _normalize_link_field(body.tcg_order_id)
    if not seller or not tcg_order_id:
        raise HTTPException(status_code=400, detail="seller and tcg_order_id required")

    status = body.status or "ordered"
    if status not in INVENTORY_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    clauses = ["LOWER(seller) = LOWER(:seller)", "status NOT IN ('cancelled', 'depleted')"]
    params: dict[str, Any] = {"seller": seller, "tcg_order_id": tcg_order_id, "status": status}
    if body.only_unlinked:
        clauses.append("tcg_order_id IS NULL")

    where_sql = " AND ".join(clauses)
    sql = f"""
        UPDATE inventory_lots
        SET tcg_order_id = :tcg_order_id,
            status = :status,
            ordered_at = COALESCE(ordered_at, CURRENT_DATE),
            acquired_at = COALESCE(acquired_at, CURRENT_DATE),
            updated_at = NOW()
        WHERE {where_sql}
        RETURNING id, name, seller, tcg_order_id, status, qty_on_hand
    """

    with _engine.begin() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    return {
        "count": len(rows),
        "updated": [_normalize_inventory_row(dict(r)) for r in rows],
    }


@router.get("/api/inventory/{lot_id}")
def get_inventory_lot(lot_id: int, include_fulfillments: bool = Query(True)) -> dict[str, Any]:
    with _engine.connect() as conn:
        lot = _inventory_view_row(conn, lot_id)
        if not lot:
            raise HTTPException(status_code=404, detail="Inventory lot not found")
        out: dict[str, Any] = {"lot": lot}
        if include_fulfillments:
            rows = conn.execute(
                text(
                    """
                    SELECT * FROM ck_fulfillments
                    WHERE inventory_lot_id = :lot_id
                    ORDER BY created_at ASC, id ASC
                    """
                ),
                {"lot_id": lot_id},
            ).mappings().all()
            out["fulfillments"] = [_normalize_fulfillment_row(dict(r)) for r in rows]
    return out


@router.post("/api/inventory")
def create_inventory(item: InventoryCreateItem) -> dict[str, Any]:
    qty = item.qty if item.qty and item.qty >= 1 else None
    status = item.status or "ordered"
    with _engine.begin() as conn:
        opp = _get_opportunity_by_id(conn, item.opportunity_id)
        if not opp:
            raise HTTPException(status_code=404, detail=f"Opportunity {item.opportunity_id} not found")
        if _active_inventory_exists_for_keys(
            conn,
            opp["product_id"],
            opp.get("finish"),
            opp.get("condition_raw"),
            opp.get("seller_key"),
            opp.get("seller"),
        ):
            raise HTTPException(status_code=409, detail="Already in inventory")
        use_qty = qty if qty is not None else int(opp.get("order_qty") or 1)
        fields = _build_lot_fields_from_opportunity(
            opp, use_qty, item.notes, item.tcg_order_id, status
        )
        return _insert_inventory_lot(conn, fields)


@router.post("/api/inventory/batch")
def create_inventory_batch(body: InventoryBatchCreate) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    with _engine.begin() as conn:
        for item in body.items:
            try:
                opp = _get_opportunity_by_id(conn, item.opportunity_id)
                if not opp:
                    errors.append({"opportunity_id": item.opportunity_id, "error": "not_found"})
                    continue
                if _active_inventory_exists_for_keys(
                    conn,
                    opp["product_id"],
                    opp.get("finish"),
                    opp.get("condition_raw"),
                    opp.get("seller_key"),
                    opp.get("seller"),
                ):
                    skipped.append(
                        {
                            "opportunity_id": item.opportunity_id,
                            "name": opp.get("name"),
                            "reason": "already_in_inventory",
                        }
                    )
                    continue
                use_qty = item.qty if item.qty and item.qty >= 1 else int(opp.get("order_qty") or 1)
                status = item.status or "ordered"
                fields = _build_lot_fields_from_opportunity(
                    opp, use_qty, item.notes, item.tcg_order_id, status
                )
                created.append(_insert_inventory_lot(conn, fields))
            except Exception as exc:
                errors.append({"opportunity_id": item.opportunity_id, "error": str(exc)})

    return {"created": created, "skipped": skipped, "errors": errors}


@router.post("/api/inventory/manual")
def create_manual_inventory(body: InventoryManualCreate) -> dict[str, Any]:
    name = body.name.strip()
    seller = body.seller.strip()
    if not name or not seller:
        raise HTTPException(status_code=400, detail="name and seller are required")
    if body.seller_price <= 0:
        raise HTTPException(status_code=400, detail="seller_price must be > 0")

    qty = body.qty if body.qty >= 1 else 1
    status = body.status or "on_hand"
    if status not in INVENTORY_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    condition_raw = (body.condition or "Near Mint").strip()
    finish = (body.finish or "normal").strip().lower()
    seller_key = (body.seller_key or _parse_seller_key_from_url(body.tcg_url) or "").strip() or None
    tcg_url = strip_seller_from_tcg_url(body.tcg_url.strip() if body.tcg_url else None)
    tcg_product_id = _resolve_tcg_product_id(body.product_id, tcg_url)
    product_id = tcg_product_id or _manual_product_id(body)
    ck_max_int = body.ck_max_qty
    expected_ck_qty = int(effective_profit_qty(qty, ck_max_int))
    econ = _recalc_inventory_economics(
        seller_price=body.seller_price,
        shipping_price=body.shipping_price,
        ck_cash=body.ck_cash,
        ck_adj=body.ck_adj,
        condition_display=condition_raw,
        qty=expected_ck_qty,
        buy_qty=qty,
    )

    with _engine.begin() as conn:
        if _active_inventory_exists_for_keys(
            conn, product_id, finish, condition_raw, seller_key, seller
        ):
            raise HTTPException(status_code=409, detail="Already in inventory")
        return _insert_inventory_lot(
            conn,
            {
                "status": status,
                "qty_original": qty,
                "qty_on_hand": qty,
                "opportunity_id": None,
                "snapshot_date": date.today(),
                "product_id": product_id,
                "tcg_product_id": tcg_product_id,
                "name": name,
                "set_name": body.set_name.strip() if body.set_name else None,
                "variant": body.variant.strip() if body.variant else None,
                "finish": finish,
                "condition_display": condition_raw,
                "condition_raw": condition_raw,
                "seller": seller,
                "seller_key": seller_key,
                "seller_price": round(float(body.seller_price), 2),
                "shipping_price": econ["shipping_price"],
                "ck_cash": body.ck_cash,
                "ck_cash_expected": body.ck_cash,
                "ck_adj": econ["ck_adj"],
                "ck_max_qty": ck_max_int,
                "expected_ck_qty": expected_ck_qty,
                "profit_per_copy": econ["profit_per_copy"],
                "expected_profit": econ["expected_profit"],
                "expected_roi": econ["expected_roi"],
                "tcg_url": tcg_url,
                "ck_url": body.ck_url.strip() if body.ck_url else None,
                "notes": body.notes.strip() if body.notes else None,
                "checkout_key": None,
                "tcg_order_id": _normalize_link_field(body.tcg_order_id),
                "acquired_at": _parse_order_date(body.ordered_at) or date.today(),
                "ordered_at": _parse_order_date(body.ordered_at) or date.today(),
            },
        )


@router.patch("/api/inventory/{lot_id}")
def update_inventory_lot(lot_id: int, body: InventoryUpdate) -> dict[str, Any]:
    fields_set = body.model_fields_set
    economics_fields = {
        "seller_price", "shipping_price", "ck_cash", "ck_adj", "condition",
        "expected_ck_qty", "qty_original",
    }

    with _engine.begin() as conn:
        current = conn.execute(
            text("SELECT * FROM inventory_lots WHERE id = :id FOR UPDATE"),
            {"id": lot_id},
        ).mappings().first()
        if not current:
            raise HTTPException(status_code=404, detail="Inventory lot not found")

        fulfilled_committed = int(
            conn.execute(
                text(
                    """
                    SELECT COALESCE(SUM(qty), 0)
                    FROM ck_fulfillments
                    WHERE inventory_lot_id = :id
                      AND status NOT IN ('cancelled', 'rejected')
                    """
                ),
                {"id": lot_id},
            ).scalar()
            or 0
        )
        # Free stock + reserved (planned/packed/sent/paid) cannot exceed bought qty.
        fulfilled_decremented = fulfilled_committed

        merged = dict(current)
        updates: list[str] = []
        params: dict[str, Any] = {"id": lot_id}

        if body.status is not None:
            if body.status not in INVENTORY_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid status")
            merged["status"] = body.status
            updates.append("status = :status")
            params["status"] = body.status

        if "qty_original" in fields_set:
            if body.qty_original is None or body.qty_original < 1:
                raise HTTPException(status_code=400, detail="qty_original must be >= 1")
            if body.qty_original < fulfilled_committed:
                raise HTTPException(
                    status_code=400,
                    detail=f"Bought qty cannot be below {fulfilled_committed} already on CK fulfillments",
                )
            old_original = int(merged["qty_original"])
            merged["qty_original"] = int(body.qty_original)
            updates.append("qty_original = :qty_original")
            params["qty_original"] = merged["qty_original"]
            # If stock still matched the old buy size (or overshoots), sync free stock.
            if "qty_on_hand" not in fields_set:
                on_hand = int(merged["qty_on_hand"])
                if on_hand == old_original or on_hand > merged["qty_original"] - fulfilled_committed:
                    merged["qty_on_hand"] = max(0, merged["qty_original"] - fulfilled_committed)
                    updates.append("qty_on_hand = :qty_on_hand")
                    params["qty_on_hand"] = merged["qty_on_hand"]
                    if body.status is None and merged.get("status") != "cancelled":
                        auto_status = "depleted" if merged["qty_on_hand"] == 0 else merged["status"]
                        if merged["qty_on_hand"] > 0 and merged.get("status") == "depleted":
                            auto_status = "on_hand"
                        if auto_status != merged.get("status"):
                            merged["status"] = auto_status
                            updates.append("status = :status")
                            params["status"] = auto_status
            if body.expected_ck_qty is None:
                ck_max = merged.get("ck_max_qty")
                ck_max_int = int(ck_max) if ck_max is not None else None
                merged["expected_ck_qty"] = int(
                    effective_profit_qty(merged["qty_original"], ck_max_int)
                )
                updates.append("expected_ck_qty = :expected_ck_qty")
                params["expected_ck_qty"] = merged["expected_ck_qty"]

        if body.qty_on_hand is not None:
            if body.qty_on_hand < 0 or body.qty_on_hand > int(merged["qty_original"]):
                raise HTTPException(status_code=400, detail="qty_on_hand out of range")
            remaining_cap = int(merged["qty_original"]) - fulfilled_decremented
            if body.qty_on_hand > remaining_cap:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Free on-hand cannot exceed {remaining_cap} "
                        "after planned/packed/sent CK lines"
                    ),
                )
            merged["qty_on_hand"] = body.qty_on_hand
            updates.append("qty_on_hand = :qty_on_hand")
            params["qty_on_hand"] = body.qty_on_hand

        for field, col in (
            (body.name, "name"),
            (body.seller, "seller"),
        ):
            if field is not None:
                val = field.strip()
                if not val:
                    raise HTTPException(status_code=400, detail=f"{col} is required")
                merged[col] = val
                updates.append(f"{col} = :{col}")
                params[col] = val

        if "set_name" in fields_set:
            merged["set_name"] = body.set_name.strip() if body.set_name else None
            updates.append("set_name = :set_name")
            params["set_name"] = merged["set_name"]

        if body.finish is not None:
            merged["finish"] = body.finish.strip().lower()
            updates.append("finish = :finish")
            params["finish"] = merged["finish"]

        if "condition" in fields_set:
            condition = (body.condition or "Near Mint").strip()
            merged["condition_display"] = condition
            merged["condition_raw"] = condition
            updates.extend(["condition_display = :condition_display", "condition_raw = :condition_raw"])
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

        if "ck_cash_expected" in fields_set:
            ck_exp = (
                round(float(body.ck_cash_expected), 2) if body.ck_cash_expected is not None else None
            )
            merged["ck_cash_expected"] = ck_exp
            updates.append("ck_cash_expected = :ck_cash_expected")
            params["ck_cash_expected"] = ck_exp

        if "ck_adj" in fields_set:
            ck_adj = round(float(body.ck_adj), 2) if body.ck_adj is not None else None
            merged["ck_adj"] = ck_adj
            updates.append("ck_adj = :ck_adj")
            params["ck_adj"] = ck_adj

        if "ck_cash" in fields_set or "ck_cash_expected" in fields_set:
            if merged.get("ck_cash") is not None and merged.get("ck_cash_expected") is not None:
                merged["ck_cash_delta"] = round(
                    float(merged["ck_cash"]) - float(merged["ck_cash_expected"]), 2
                )
            else:
                merged["ck_cash_delta"] = None
            updates.append("ck_cash_delta = :ck_cash_delta")
            params["ck_cash_delta"] = merged["ck_cash_delta"]

        if body.expected_ck_qty is not None:
            merged["expected_ck_qty"] = body.expected_ck_qty
            updates.append("expected_ck_qty = :expected_ck_qty")
            params["expected_ck_qty"] = body.expected_ck_qty

        if "ck_max_qty" in fields_set:
            ck_max = int(body.ck_max_qty) if body.ck_max_qty is not None else None
            merged["ck_max_qty"] = ck_max
            updates.append("ck_max_qty = :ck_max_qty")
            params["ck_max_qty"] = ck_max

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
            if merged["tcg_order_id"] and not merged.get("ordered_at"):
                merged["ordered_at"] = date.today()
                updates.append("ordered_at = :ordered_at")
                params["ordered_at"] = merged["ordered_at"]
                if not merged.get("acquired_at"):
                    updates.append("acquired_at = :acquired_at")
                    params["acquired_at"] = merged["ordered_at"]

        if "ordered_at" in fields_set:
            ordered = _parse_order_date(body.ordered_at)
            merged["ordered_at"] = ordered
            updates.append("ordered_at = :ordered_at")
            params["ordered_at"] = ordered
            if ordered and not merged.get("acquired_at"):
                updates.append("acquired_at = :acquired_at")
                params["acquired_at"] = ordered

        if "tcg_url" in fields_set:
            merged["tcg_url"] = strip_seller_from_tcg_url(
                body.tcg_url.strip() if body.tcg_url else None
            )
            updates.append("tcg_url = :tcg_url")
            params["tcg_url"] = merged["tcg_url"]
            resolved = _resolve_tcg_product_id(merged.get("product_id"), merged["tcg_url"])
            if resolved:
                merged["tcg_product_id"] = resolved
                updates.append("tcg_product_id = :tcg_product_id")
                params["tcg_product_id"] = resolved
                if str(merged.get("product_id") or "").startswith("manual:"):
                    merged["product_id"] = resolved
                    updates.append("product_id = :product_id")
                    params["product_id"] = resolved

        if "ck_url" in fields_set:
            merged["ck_url"] = body.ck_url.strip() if body.ck_url else None
            updates.append("ck_url = :ck_url")
            params["ck_url"] = merged["ck_url"]

        if economics_fields & fields_set or body.expected_ck_qty is not None:
            qty_for_econ = int(merged.get("expected_ck_qty") or merged["qty_original"])
            if "ck_adj" not in fields_set and ("ck_cash" in fields_set or "condition" in fields_set):
                if merged.get("ck_cash") is not None:
                    mult = MANUAL_CONDITION_MULT.get(merged.get("condition_display") or "Near Mint", 1.0)
                    merged["ck_adj"] = round(float(merged["ck_cash"]) * mult, 2)
                    updates.append("ck_adj = :ck_adj")
                    params["ck_adj"] = merged["ck_adj"]
            econ = _recalc_inventory_economics(
                seller_price=float(merged["seller_price"]) if merged.get("seller_price") is not None else None,
                shipping_price=merged.get("shipping_price"),
                ck_cash=float(merged["ck_cash"]) if merged.get("ck_cash") is not None else None,
                ck_adj=float(merged["ck_adj"]) if merged.get("ck_adj") is not None else None,
                condition_display=merged.get("condition_display"),
                qty=qty_for_econ,
                buy_qty=int(merged.get("qty_original") or qty_for_econ),
            )
            for key in ("ck_adj", "profit_per_copy", "expected_profit", "expected_roi", "shipping_price"):
                if f"{key} = :{key}" not in updates:
                    updates.append(f"{key} = :{key}")
                    params[key] = econ[key]

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        updates.append("updated_at = NOW()")
        conn.execute(
            text(f"UPDATE inventory_lots SET {', '.join(updates)} WHERE id = :id"),
            params,
        )

    with _engine.connect() as conn:
        lot = _inventory_view_row(conn, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Inventory lot not found")
    return lot


@router.delete("/api/inventory/{lot_id}")
def delete_inventory_lot(lot_id: int) -> dict[str, Any]:
    with _engine.begin() as conn:
        row = conn.execute(
            text("DELETE FROM inventory_lots WHERE id = :id RETURNING id, name"),
            {"id": lot_id},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Inventory lot not found")
    return {"deleted": True, "id": row["id"], "name": row["name"]}


@router.get("/api/inventory/{lot_id}/fulfillments")
def list_fulfillments(lot_id: int) -> dict[str, Any]:
    with _engine.connect() as conn:
        lot = conn.execute(
            text("SELECT id FROM inventory_lots WHERE id = :id"),
            {"id": lot_id},
        ).scalar()
        if not lot:
            raise HTTPException(status_code=404, detail="Inventory lot not found")
        rows = conn.execute(
            text(
                """
                SELECT * FROM ck_fulfillments
                WHERE inventory_lot_id = :lot_id
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"lot_id": lot_id},
        ).mappings().all()
    return {"fulfillments": [_normalize_fulfillment_row(dict(r)) for r in rows]}


def _create_fulfillment_row(
    conn,
    lot_id: int,
    *,
    qty: int,
    status: str,
    ck_batch_id: str | None,
    ck_ref: str | None,
    ck_adj: float | None,
    paid_amount: float | None,
    notes: str | None,
) -> dict[str, Any]:
    if qty < 1:
        raise HTTPException(status_code=400, detail="qty must be >= 1")
    if status not in FULFILLMENT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid fulfillment status")

    lot = conn.execute(
        text("SELECT id, name, ck_adj FROM inventory_lots WHERE id = :id FOR UPDATE"),
        {"id": lot_id},
    ).mappings().first()
    if not lot:
        raise HTTPException(status_code=404, detail=f"Inventory lot {lot_id} not found")

    if _fulfillment_decrements_inventory(status):
        on_hand = conn.execute(
            text("SELECT qty_on_hand FROM inventory_lots WHERE id = :id"),
            {"id": lot_id},
        ).scalar()
        if int(on_hand) < qty:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough qty on hand for {lot.get('name') or lot_id}",
            )

    resolved_adj = ck_adj if ck_adj is not None else lot.get("ck_adj")
    row = conn.execute(
        text(
            """
            INSERT INTO ck_fulfillments (
                inventory_lot_id, qty, ck_batch_id, ck_ref, ck_adj, status,
                paid_amount, packed_at, sent_at, paid_at, notes
            ) VALUES (
                :inventory_lot_id, :qty, :ck_batch_id, :ck_ref, :ck_adj, :status,
                :paid_amount,
                CASE WHEN :status IN ('packed', 'sent', 'paid') THEN NOW() ELSE NULL END,
                CASE WHEN :status IN ('sent', 'paid') THEN NOW() ELSE NULL END,
                CASE WHEN :status = 'paid' THEN NOW() ELSE NULL END,
                :notes
            )
            RETURNING *
            """
        ),
        {
            "inventory_lot_id": lot_id,
            "qty": qty,
            "ck_batch_id": _normalize_link_field(ck_batch_id),
            "ck_ref": _normalize_link_field(ck_ref),
            "ck_adj": round(float(resolved_adj), 2) if resolved_adj is not None else None,
            "status": status,
            "paid_amount": round(float(paid_amount), 2) if paid_amount is not None else None,
            "notes": notes.strip() if notes else None,
        },
    ).mappings().first()

    if _fulfillment_decrements_inventory(status):
        _apply_fulfillment_qty_change(conn, lot_id, None, status, 0, qty)

    return _normalize_fulfillment_row(dict(row))


@router.post("/api/inventory/fulfillments/batch")
def create_fulfillment_batch(body: FulfillmentBatchCreate) -> dict[str, Any]:
    if not body.items:
        raise HTTPException(status_code=400, detail="items required")
    status = body.status or "sent"
    if status not in FULFILLMENT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid fulfillment status")
    ck_ref = _normalize_link_field(body.ck_ref)
    ck_batch_id = _normalize_link_field(body.ck_batch_id)
    if not ck_ref and not ck_batch_id:
        raise HTTPException(status_code=400, detail="CK order # (ck_ref) or batch id required")

    created: list[dict[str, Any]] = []
    with _engine.begin() as conn:
        for item in body.items:
            item_notes = item.notes.strip() if item.notes else None
            shared_notes = body.notes.strip() if body.notes else None
            notes = item_notes or shared_notes
            created.append(
                _create_fulfillment_row(
                    conn,
                    item.inventory_lot_id,
                    qty=item.qty,
                    status=status,
                    ck_batch_id=ck_batch_id,
                    ck_ref=ck_ref,
                    ck_adj=item.ck_adj,
                    paid_amount=item.paid_amount,
                    notes=notes,
                )
            )
    return {"created": created, "count": len(created)}


@router.post("/api/inventory/{lot_id}/fulfillments")
def create_fulfillment(lot_id: int, body: FulfillmentCreate) -> dict[str, Any]:
    status = body.status or "planned"
    with _engine.begin() as conn:
        return _create_fulfillment_row(
            conn,
            lot_id,
            qty=body.qty,
            status=status,
            ck_batch_id=body.ck_batch_id,
            ck_ref=body.ck_ref,
            ck_adj=body.ck_adj,
            paid_amount=body.paid_amount,
            notes=body.notes,
        )


@router.patch("/api/inventory/{lot_id}/fulfillments/{fulfillment_id}")
def update_fulfillment(lot_id: int, fulfillment_id: int, body: FulfillmentUpdate) -> dict[str, Any]:
    fields_set = body.model_fields_set

    with _engine.begin() as conn:
        current = conn.execute(
            text(
                """
                SELECT * FROM ck_fulfillments
                WHERE id = :id AND inventory_lot_id = :lot_id
                FOR UPDATE
                """
            ),
            {"id": fulfillment_id, "lot_id": lot_id},
        ).mappings().first()
        if not current:
            raise HTTPException(status_code=404, detail="Fulfillment not found")

        old_status = current["status"]
        old_qty = int(current["qty"])
        new_status = body.status if body.status is not None else old_status
        new_qty = body.qty if body.qty is not None else old_qty

        if new_status not in FULFILLMENT_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid fulfillment status")
        if new_qty < 1:
            raise HTTPException(status_code=400, detail="qty must be >= 1")

        if old_status != new_status or old_qty != new_qty:
            _apply_fulfillment_qty_change(conn, lot_id, old_status, new_status, old_qty, new_qty)

        updates: list[str] = []
        params: dict[str, Any] = {"id": fulfillment_id, "lot_id": lot_id}

        if body.qty is not None:
            updates.append("qty = :qty")
            params["qty"] = new_qty
        if body.status is not None:
            updates.append("status = :status")
            params["status"] = new_status
            if new_status == "planned":
                updates.append("packed_at = NULL")
                updates.append("sent_at = NULL")
                updates.append("paid_at = NULL")
            elif new_status == "packed":
                updates.append("packed_at = COALESCE(packed_at, NOW())")
                updates.append("sent_at = NULL")
                updates.append("paid_at = NULL")
            elif new_status == "sent":
                updates.append("packed_at = COALESCE(packed_at, NOW())")
                updates.append("sent_at = COALESCE(sent_at, NOW())")
                updates.append("paid_at = NULL")
            elif new_status == "paid":
                updates.append("packed_at = COALESCE(packed_at, NOW())")
                updates.append("sent_at = COALESCE(sent_at, NOW())")
                updates.append("paid_at = COALESCE(paid_at, NOW())")
        if "ck_batch_id" in fields_set:
            updates.append("ck_batch_id = :ck_batch_id")
            params["ck_batch_id"] = _normalize_link_field(body.ck_batch_id)
        if "ck_ref" in fields_set:
            updates.append("ck_ref = :ck_ref")
            params["ck_ref"] = _normalize_link_field(body.ck_ref)
        if "ck_adj" in fields_set:
            updates.append("ck_adj = :ck_adj")
            params["ck_adj"] = round(float(body.ck_adj), 2) if body.ck_adj is not None else None
        if "paid_amount" in fields_set:
            updates.append("paid_amount = :paid_amount")
            params["paid_amount"] = (
                round(float(body.paid_amount), 2) if body.paid_amount is not None else None
            )
        if "notes" in fields_set:
            updates.append("notes = :notes")
            params["notes"] = body.notes.strip() if body.notes else None

        if not updates:
            return _normalize_fulfillment_row(dict(current))

        updates.append("updated_at = NOW()")
        row = conn.execute(
            text(
                f"""
                UPDATE ck_fulfillments SET {', '.join(updates)}
                WHERE id = :id AND inventory_lot_id = :lot_id
                RETURNING *
                """
            ),
            params,
        ).mappings().first()

    return _normalize_fulfillment_row(dict(row))


@router.delete("/api/inventory/{lot_id}/fulfillments/{fulfillment_id}")
def delete_fulfillment(lot_id: int, fulfillment_id: int) -> dict[str, Any]:
    with _engine.begin() as conn:
        current = conn.execute(
            text(
                """
                SELECT * FROM ck_fulfillments
                WHERE id = :id AND inventory_lot_id = :lot_id
                FOR UPDATE
                """
            ),
            {"id": fulfillment_id, "lot_id": lot_id},
        ).mappings().first()
        if not current:
            raise HTTPException(status_code=404, detail="Fulfillment not found")

        if _fulfillment_decrements_inventory(current["status"]):
            _apply_fulfillment_qty_change(
                conn, lot_id, current["status"], "cancelled", int(current["qty"]), 0
            )

        row = conn.execute(
            text(
                """
                DELETE FROM ck_fulfillments
                WHERE id = :id AND inventory_lot_id = :lot_id
                RETURNING id
                """
            ),
            {"id": fulfillment_id, "lot_id": lot_id},
        ).mappings().first()

    return {"deleted": True, "id": row["id"]}
