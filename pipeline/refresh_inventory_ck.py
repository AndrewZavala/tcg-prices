#!/usr/bin/env python3
"""Refresh CK cash prices on inventory lots from the latest buylist snapshot."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import create_engine, text

from config import DATABASE_URL, MIGRATIONS_DIR
from tcg_condition import condition_multiplier, effective_profit_qty

# Match web/inventory_api.py display-name multipliers.
CONDITION_MULT: dict[str, float] = {
    "Near Mint": 1.0,
    "Lightly Played": 0.75,
    "Moderately Played": 0.5,
    "Heavily Played": 0.25,
    "Damaged": 0.0,
}


@dataclass(frozen=True)
class BuylistPrice:
    cash_price: float
    max_qty: int | None
    finish: str


def _normalize_finish(value: str | None) -> str:
    finish = (value or "normal").strip().lower()
    if finish in {"nonfoil", "non-foil"}:
        return "normal"
    return finish or "normal"


def _clean_tcg_pid(value: str | None) -> str | None:
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


def _parse_tcg_product_id(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"/product/(\d+)", url, re.I)
    return match.group(1) if match else None


def _lot_tcg_product_id(lot: dict[str, Any]) -> str | None:
    return (
        _clean_tcg_pid(lot.get("tcg_product_id"))
        or _clean_tcg_pid(lot.get("product_id"))
        or _parse_tcg_product_id(lot.get("tcg_url"))
    )


def _condition_mult(condition_display: str | None, condition_raw: str | None) -> float:
    for cond in (condition_display, condition_raw):
        if cond and cond in CONDITION_MULT:
            return CONDITION_MULT[cond]
    for cond in (condition_display, condition_raw):
        mult = condition_multiplier(cond)
        if mult is not None:
            return mult
    return 1.0


def _recalc_fields(lot: dict[str, Any], ck_cash: float, ck_max_qty: int | None) -> dict[str, Any]:
    qty_original = max(int(lot.get("qty_original") or 1), 1)
    qty_on_hand = int(lot.get("qty_on_hand") or 0)
    qty_held = qty_on_hand if qty_on_hand > 0 else qty_original
    expected_ck_qty = int(effective_profit_qty(qty_held, ck_max_qty))

    mult = _condition_mult(lot.get("condition_display"), lot.get("condition_raw"))
    ck_adj = round(float(ck_cash) * mult, 2)

    seller_price = float(lot["seller_price"]) if lot.get("seller_price") is not None else None
    shipping = float(lot["shipping_price"] or 0)
    # Cost only the copies we expect to sell to CK; remainder is inventory, not a loss.
    ship_share = shipping * (expected_ck_qty / qty_original) if shipping and qty_original else 0.0

    profit_per_copy = None
    expected_profit = None
    expected_roi = None
    if seller_price is not None:
        profit_per_copy = round(ck_adj - seller_price, 2)
        order_cost = seller_price * expected_ck_qty + ship_share
        expected_profit = round(ck_adj * expected_ck_qty - order_cost, 2)
        expected_roi = round(expected_profit / order_cost * 100, 2) if order_cost > 0 else None

    return {
        "ck_cash": round(float(ck_cash), 2),
        "ck_adj": ck_adj,
        "ck_max_qty": ck_max_qty,
        "expected_ck_qty": expected_ck_qty,
        "profit_per_copy": profit_per_copy,
        "expected_profit": expected_profit,
        "expected_roi": expected_roi,
    }


def _clear_current_ck_fields(lot: dict[str, Any], ck_expected: float | None, snapshot: date) -> dict[str, Any]:
    """CK not buying this finish on the latest buylist — clear live price, keep buy baseline."""
    return {
        "ck_cash": None,
        "ck_adj": None,
        "ck_max_qty": None,
        "ck_cash_expected": ck_expected,
        "ck_cash_delta": None,
        "ck_price_snapshot": snapshot,
        "expected_ck_qty": int(lot.get("expected_ck_qty") or lot.get("qty_on_hand") or lot.get("qty_original") or 0) or None,
        "profit_per_copy": None,
        "expected_profit": None,
        "expected_roi": None,
    }


def _row_to_price(row: dict[str, Any]) -> BuylistPrice | None:
    cash = row.get("cash_price")
    if cash is None:
        return None
    try:
        cash_f = float(cash)
    except (TypeError, ValueError):
        return None
    if cash_f <= 0:
        return None
    max_qty_raw = row.get("max_qty")
    max_qty = int(max_qty_raw) if max_qty_raw not in (None, "") else None
    return BuylistPrice(
        cash_price=cash_f,
        max_qty=max_qty,
        finish=_normalize_finish(row.get("finish")),
    )


def _build_tcg_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], BuylistPrice]:
    tcg: dict[tuple[str, str], BuylistPrice] = {}

    for row in rows:
        price = _row_to_price(row)
        if price is None:
            continue

        tcg_ids: list[str] = []
        if price.finish == "etched":
            pid = _clean_tcg_pid(row.get("tcgplayer_etched_id"))
            if pid:
                tcg_ids.append(pid)
        base = _clean_tcg_pid(row.get("tcgplayer_id"))
        if base:
            tcg_ids.append(base)

        for pid in tcg_ids:
            tkey = (pid, price.finish)
            prev = tcg.get(tkey)
            if prev is None or price.cash_price > prev.cash_price:
                tcg[tkey] = price

    return tcg


def _lookup_tcg(index: dict[tuple[str, str], BuylistPrice], pid: str, finish: str) -> BuylistPrice | None:
    """Exact finish match only — never fall back foil→normal (wrong CK cash)."""
    return index.get((pid, finish))


def _resolve_lot_price(
    lot: dict[str, Any],
    latest: dict[tuple[str, str], BuylistPrice],
) -> tuple[BuylistPrice | None, str | None]:
    """Return (price, pid). Price is None when CK is not buying this finish on latest."""
    finish = _normalize_finish(lot.get("finish"))
    pid = _lot_tcg_product_id(lot)
    if not pid:
        return None, None
    return _lookup_tcg(latest, pid, finish), pid


def _load_tcg_index(conn, snapshot_date: str) -> dict[tuple[str, str], BuylistPrice]:
    rows = conn.execute(
        text(
            """
            SELECT finish, cash_price, max_qty, tcgplayer_id, tcgplayer_etched_id
            FROM buylist_cards
            WHERE snapshot_date = :snapshot_date
              AND cash_price IS NOT NULL AND cash_price > 0
            """
        ),
        {"snapshot_date": snapshot_date},
    ).mappings().all()
    return _build_tcg_index([dict(r) for r in rows])


def refresh_inventory_ck_prices(engine) -> dict[str, int]:
    with engine.connect() as conn:
        latest_snap = conn.execute(
            text(
                """
                SELECT snapshot_date::text
                FROM buylist_snapshots
                ORDER BY snapshot_date DESC
                LIMIT 1
                """
            )
        ).scalar()
        if not latest_snap:
            print("No buylist snapshot in Postgres — skip inventory CK refresh")
            return {"matched": 0, "updated": 0, "skipped": 0, "not_buying": 0, "unmatched": 0}

        latest = _load_tcg_index(conn, latest_snap)
        snap_date = date.fromisoformat(latest_snap)

        lots = conn.execute(
            text(
                """
                SELECT id, product_id, tcg_product_id, finish, tcg_url,
                       condition_display, condition_raw,
                       qty_original, qty_on_hand, seller_price, shipping_price,
                       ck_cash, ck_adj, ck_max_qty, ck_cash_expected, ck_cash_delta,
                       ck_price_snapshot, expected_ck_qty
                FROM inventory_lots
                WHERE status != 'cancelled'
                ORDER BY id
                """
            )
        ).mappings().all()

        stats = {"matched": 0, "updated": 0, "skipped": 0, "not_buying": 0, "unmatched": 0}
        updates: list[tuple[int, dict[str, Any], float | None, float | None]] = []

        for lot in lots:
            lot_d = dict(lot)
            latest_hit, resolved_pid = _resolve_lot_price(lot_d, latest)
            if not resolved_pid:
                stats["unmatched"] += 1
                continue

            old_cash = float(lot_d["ck_cash"]) if lot_d.get("ck_cash") is not None else None
            ck_expected = (
                round(float(lot_d["ck_cash_expected"]), 2)
                if lot_d.get("ck_cash_expected") is not None
                else None
            )
            # Preserve buy-time CK cash; if missing (legacy), freeze current as baseline once.
            if ck_expected is None and old_cash is not None:
                ck_expected = round(old_cash, 2)

            if latest_hit is None:
                # Identified card, but CK is not buying this finish on the latest pull.
                stats["not_buying"] += 1
                fields = _clear_current_ck_fields(lot_d, ck_expected, snap_date)
            else:
                stats["matched"] += 1
                if latest_hit.max_qty is not None and latest_hit.max_qty <= 0:
                    stats["not_buying"] += 1
                fields = _recalc_fields(lot_d, latest_hit.cash_price, latest_hit.max_qty)
                fields["ck_cash_expected"] = ck_expected
                fields["ck_cash_delta"] = (
                    round(fields["ck_cash"] - ck_expected, 2) if ck_expected is not None else None
                )
                fields["ck_price_snapshot"] = snap_date

            stored_pid = _clean_tcg_pid(lot_d.get("tcg_product_id"))
            if resolved_pid and stored_pid != resolved_pid:
                fields["tcg_product_id"] = resolved_pid
            display_pid = fields.get("tcg_product_id") or stored_pid or resolved_pid

            prior_snap_val = lot_d.get("ck_price_snapshot")
            if prior_snap_val is not None and not isinstance(prior_snap_val, date):
                prior_snap_val = date.fromisoformat(str(prior_snap_val))

            existing_expected = (
                round(float(lot_d["ck_cash_expected"]), 2)
                if lot_d.get("ck_cash_expected") is not None
                else None
            )
            same_cash = (
                (old_cash is None and fields["ck_cash"] is None)
                or (
                    old_cash is not None
                    and fields["ck_cash"] is not None
                    and abs(old_cash - fields["ck_cash"]) < 0.005
                )
            )
            if (
                same_cash
                and existing_expected == ck_expected
                and lot_d.get("ck_cash_delta") == fields.get("ck_cash_delta")
                and prior_snap_val == fields["ck_price_snapshot"]
                and lot_d.get("ck_max_qty") == fields["ck_max_qty"]
                and lot_d.get("expected_ck_qty") == fields["expected_ck_qty"]
                and lot_d.get("expected_profit") == fields["expected_profit"]
                and lot_d.get("expected_roi") == fields["expected_roi"]
                and lot_d.get("ck_adj") == fields["ck_adj"]
                and lot_d.get("profit_per_copy") == fields["profit_per_copy"]
                and "tcg_product_id" not in fields
            ):
                stats["skipped"] += 1
                continue

            updates.append(
                (int(lot_d["id"]), fields, old_cash, fields.get("ck_cash_delta"), display_pid)
            )

    if updates:
        with engine.begin() as conn:
            for lot_id, fields, old_cash, ck_delta, display_pid in updates:
                tcg_sql = ""
                params = {"id": lot_id, **fields}
                if "tcg_product_id" in fields:
                    tcg_sql = ", tcg_product_id = :tcg_product_id"
                conn.execute(
                    text(
                        f"""
                        UPDATE inventory_lots
                        SET ck_cash = :ck_cash,
                            ck_adj = :ck_adj,
                            ck_max_qty = :ck_max_qty,
                            ck_cash_expected = COALESCE(ck_cash_expected, :ck_cash_expected),
                            ck_cash_delta = :ck_cash_delta,
                            ck_price_snapshot = :ck_price_snapshot,
                            expected_ck_qty = :expected_ck_qty,
                            profit_per_copy = :profit_per_copy,
                            expected_profit = :expected_profit,
                            expected_roi = :expected_roi{tcg_sql},
                            updated_at = NOW()
                        WHERE id = :id
                        """
                    ),
                    params,
                )
                if fields.get("ck_adj") is not None:
                    conn.execute(
                        text(
                            """
                            UPDATE ck_fulfillments
                            SET ck_adj = :ck_adj, updated_at = NOW()
                            WHERE inventory_lot_id = :id AND status IN ('planned', 'packed')
                            """
                        ),
                        {"id": lot_id, "ck_adj": fields["ck_adj"]},
                    )
                stats["updated"] += 1
                if fields["ck_cash"] is None:
                    cash_note = "ck_cash — (CK not buying)"
                else:
                    cash_note = f"ck_cash ${fields['ck_cash']:.2f}"
                    if ck_delta is not None:
                        cash_note += f" Δ {ck_delta:+.2f} vs buy"
                    elif old_cash is not None and abs(old_cash - fields["ck_cash"]) >= 0.005:
                        cash_note += f" ({fields['ck_cash'] - old_cash:+.2f} vs lot)"
                print(
                    f"  lot {lot_id} (TCG #{display_pid or '?'}): "
                    f"{cash_note}"
                    f" · expected ${fields['expected_profit'] or 0:.2f}"
                )

    return stats


def _ensure_tcg_product_id_column(engine) -> None:
    migration = MIGRATIONS_DIR / "012_inventory_tcg_product_id.sql"
    if not migration.exists():
        return
    with engine.begin() as conn:
        conn.execute(text(migration.read_text(encoding="utf-8")))


def _ensure_ck_cash_expected_column(engine) -> None:
    migration = MIGRATIONS_DIR / "016_inventory_ck_cash_expected.sql"
    if not migration.exists():
        return
    with engine.begin() as conn:
        conn.execute(text(migration.read_text(encoding="utf-8")))


def main() -> int:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    _ensure_tcg_product_id_column(engine)
    _ensure_ck_cash_expected_column(engine)
    print("Refreshing inventory CK prices from buylist snapshots…")
    stats = refresh_inventory_ck_prices(engine)
    print(
        "Inventory CK refresh: "
        f"{stats['updated']} updated, "
        f"{stats['skipped']} unchanged, "
        f"{stats['unmatched']} unmatched (no TCG product id), "
        f"{stats['not_buying']} CK not buying this finish, "
        f"{stats['matched']} matched on latest"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
