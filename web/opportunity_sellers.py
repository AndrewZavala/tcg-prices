"""Aggregate per-seller batched orders from opportunity rows (matches HTML report)."""

from __future__ import annotations

import os
from typing import Any

MIN_REPORT_PROFIT = float(
    os.environ.get(
        "OPPORTUNITY_MIN_REPORT_PROFIT",
        os.environ.get("OPPORTUNITY_SELLER_MIN_PROFIT", "0.50"),
    )
)
SELLER_TOP_N = int(os.environ.get("OPPORTUNITY_SELLER_TOP_N", "50"))


def passes_report_filter(row: dict[str, Any], min_profit: float = MIN_REPORT_PROFIT) -> bool:
    order_profit = row.get("order_profit")
    order_roi = row.get("order_roi")
    if order_profit is None or order_roi is None:
        return False
    if float(order_profit) < min_profit:
        return False
    if float(order_roi) < 0:
        return False
    return True


def build_seller_summary(
    rows: list[dict[str, Any]],
    *,
    top_n: int | None = None,
    q: str = "",
) -> list[dict[str, Any]]:
    """Group positive opportunities by seller; shipping counted once per seller."""
    sellers: dict[str, dict[str, Any]] = {}
    needle = q.strip().lower()

    for r in rows:
        seller = str(r.get("seller") or "").strip()
        order_profit = r.get("order_profit")
        order_qty = r.get("order_qty")
        if not seller or not passes_report_filter(r):
            continue

        buy_qty = float(order_qty or 0)
        bucket = sellers.setdefault(
            seller,
            {
                "seller": seller,
                "seller_key": str(r.get("seller_key") or ""),
                "cards": 0,
                "order_qty": 0.0,
                "ck_total": 0.0,
                "merch_cost": 0.0,
                "shipping_price": 0.0,
                "buy_list": [],
            },
        )
        bucket["cards"] += 1
        bucket["order_qty"] += buy_qty
        bucket["ck_total"] += float(r.get("ck_adj") or 0) * buy_qty
        bucket["merch_cost"] += float(r.get("seller_price") or 0) * buy_qty
        bucket["shipping_price"] = max(
            float(bucket["shipping_price"]),
            float(r.get("shipping_price") or 0),
        )
        bucket["buy_list"].append(
            {
                "opportunity_id": r.get("id"),
                "name": r["name"],
                "set_name": r.get("set_name") or "",
                "variant": r.get("variant") or "",
                "condition_display": r.get("condition_display") or "—",
                "finish": r.get("finish") or "",
                "order_qty": buy_qty,
                "lowest_price": r.get("lowest_price"),
                "seller_price": r.get("seller_price"),
                "shipping_price": r.get("shipping_price"),
                "ck_adj": r.get("ck_adj"),
                "order_profit": float(order_profit or 0),
                "ck_url": r.get("ck_url") or "",
                "tcg_url": r.get("tcg_url") or "",
            }
        )

    out: list[dict[str, Any]] = []
    for seller in sellers.values():
        cost = seller["merch_cost"] + seller["shipping_price"]
        profit = seller["ck_total"] - cost
        if profit <= 0:
            continue
        seller["shipping_price"] = round(float(seller["shipping_price"]), 2)
        seller["ck_total"] = round(float(seller["ck_total"]), 2)
        seller["merch_cost"] = round(float(seller["merch_cost"]), 2)
        seller["order_profit"] = round(profit, 2)
        seller["order_cost"] = round(cost, 2)
        seller["order_qty"] = round(float(seller["order_qty"]), 2)
        seller["order_roi"] = (
            round(seller["order_profit"] / cost * 100, 2) if cost > 0 else None
        )
        seller["buy_list"].sort(key=lambda item: item["order_profit"], reverse=True)
        out.append(seller)

    if needle:
        filtered: list[dict[str, Any]] = []
        for seller in out:
            seller_match = needle in seller["seller"].lower()
            card_match = any(
                needle in str(item.get("name") or "").lower() for item in seller["buy_list"]
            )
            if seller_match or card_match:
                filtered.append(seller)
        out = filtered

    out.sort(key=lambda r: (-(r["order_profit"] or 0), -(r["order_roi"] or 0)))
    if top_n is not None:
        out = out[:top_n]
    return out


SELLER_SORT_KEYS = {
    "profit_desc": lambda r: (-(r["order_profit"] or 0), -(r["order_roi"] or 0), r["seller"]),
    "profit_asc": lambda r: ((r["order_profit"] or 0), (r["order_roi"] or 0), r["seller"]),
    "roi_desc": lambda r: (-(r["order_roi"] or -1e9), -(r["order_profit"] or 0), r["seller"]),
    "roi_asc": lambda r: ((r["order_roi"] or 1e9), (r["order_profit"] or 0), r["seller"]),
    "name": lambda r: (r["seller"].lower(),),
    "cards_desc": lambda r: (-r["cards"], -(r["order_profit"] or 0)),
    "cost_desc": lambda r: (-(r["order_cost"] or 0), -(r["order_profit"] or 0)),
}
