#!/usr/bin/env python3
"""Match CK sealed buylist to TCGCSV prices and load sealed opportunities."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

from config import (
    SEALED_MASTER_DIR,
    SEALED_MIN_MATCH_SCORE,
    SEALED_MIN_PROFIT,
    SEALED_OPPORTUNITIES_DIR,
    SEALED_SHIPPING_ESTIMATE,
    TCGCSV_PRICES_LOOKUP,
    TCGCSV_SEALED_PRODUCTS_LOOKUP,
    ensure_dirs,
)
from load_sealed_opportunities import load_sealed_opportunities
from sealed_match import best_sealed_match, normalize_sealed_name, product_type


def _latest_master() -> Path:
    files = sorted(SEALED_MASTER_DIR.glob("cardkingdom_sealed_master_*.csv"))
    if not files:
        raise FileNotFoundError(
            f"No sealed master CSV in {SEALED_MASTER_DIR}. Run scrape_ck_sealed.py first."
        )
    return files[-1]


def _load_prices() -> pd.DataFrame:
    if not TCGCSV_PRICES_LOOKUP.exists():
        raise FileNotFoundError(
            f"Missing {TCGCSV_PRICES_LOOKUP}. Run refresh_tcgcsv.py first."
        )
    prices = pd.read_csv(TCGCSV_PRICES_LOOKUP, dtype={"product_id": str})
    prices["product_id"] = prices["product_id"].astype(str)
    prices["sub_type_name"] = prices["sub_type_name"].fillna("").astype(str).str.strip()
    # Sealed is almost always Normal / blank subtype.
    normal = prices[prices["sub_type_name"].isin(["", "Normal", "normal"])].copy()
    if normal.empty:
        normal = prices.copy()
    normal = normal.sort_values("low_price", na_position="last")
    return normal.drop_duplicates(subset=["product_id"], keep="first")


def _tcg_url(product_id: str) -> str:
    return f"https://www.tcgplayer.com/product/{product_id}" if product_id else ""


def build_sealed_rows(
    ck: pd.DataFrame,
    products: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    shipping: float,
    min_match: float,
    min_profit: float,
) -> tuple[list[dict], dict]:
    candidates = products.to_dict(orient="records")
    for cand in candidates:
        cand["_norm"] = normalize_sealed_name(cand.get("name") or "")
        cand["_type"] = product_type(cand.get("name") or "")
    price_by_id = {
        str(r["product_id"]): r
        for r in prices.to_dict(orient="records")
        if r.get("product_id")
    }

    rows: list[dict] = []
    matched = 0
    unmatched = 0
    no_price = 0

    for item in ck.to_dict(orient="records"):
        ck_name = str(item.get("name") or "")
        hit, score = best_sealed_match(ck_name, candidates, min_score=min_match)
        if not hit:
            unmatched += 1
            continue
        matched += 1
        pid = str(hit.get("product_id") or "")
        price = price_by_id.get(pid)
        if not price:
            no_price += 1
            continue

        low = price.get("low_price")
        market = price.get("market_price")
        tcg_buy = None
        for candidate in (low, market):
            try:
                v = float(candidate)
            except (TypeError, ValueError):
                continue
            if v > 0:
                tcg_buy = v
                break
        if tcg_buy is None:
            no_price += 1
            continue

        ck_cash = float(item.get("cash_price") or 0)
        ck_max = int(item.get("max_qty") or 1)
        order_qty = 1  # TCGCSV has no listing depth; score per single unit
        ship = float(shipping)
        landed = tcg_buy + ship
        profit = ck_cash - landed
        if profit < min_profit:
            continue
        cost = landed * order_qty
        roi = (profit / landed * 100.0) if landed > 0 else None

        rows.append(
            {
                "product_id": pid,
                "ck_product_id": str(item.get("ck_product_id") or ""),
                "name": ck_name,
                "set_name": item.get("edition") or hit.get("group_name") or "",
                "tcg_name": hit.get("name") or "",
                "match_score": round(score, 4),
                "ck_cash": round(ck_cash, 2),
                "ck_max_qty": ck_max,
                "lowest_price": round(landed, 2),
                "seller_price": round(tcg_buy, 2),
                "shipping_price": round(ship, 2),
                "seller": "TCGCSV low (+ ship est.)",
                "seller_key": "tcgcsv",
                "order_qty": order_qty,
                "profit_per_copy": round(profit, 2),
                "order_profit": round(profit * order_qty, 2),
                "order_roi": round(roi, 2) if roi is not None else None,
                "order_cost": round(cost, 2),
                "roi": round(roi, 2) if roi is not None else None,
                "ck_url": item.get("ck_url") or "",
                "tcg_url": _tcg_url(pid),
            }
        )

    rows.sort(key=lambda r: (-(r.get("order_profit") or 0), -(r.get("ck_cash") or 0)))
    stats = {
        "ck_buy_count": len(ck),
        "matched_count": matched,
        "unmatched": unmatched,
        "no_price": no_price,
        "opportunity_count": len(rows),
    }
    return rows, stats


def main() -> int:
    ensure_dirs()
    if not TCGCSV_SEALED_PRODUCTS_LOOKUP.exists():
        raise FileNotFoundError(
            f"Missing {TCGCSV_SEALED_PRODUCTS_LOOKUP}. Run refresh_tcgcsv_sealed.py first."
        )

    master_path = _latest_master()
    print(f"CK sealed master: {master_path}")
    ck = pd.read_csv(master_path, dtype={"ck_product_id": str})
    products = pd.read_csv(TCGCSV_SEALED_PRODUCTS_LOOKUP, dtype={"product_id": str})
    prices = _load_prices()
    print(f"CK buying {len(ck)} sealed · TCG sealed catalog {len(products)} · prices {len(prices)}")

    rows, stats = build_sealed_rows(
        ck,
        products,
        prices,
        shipping=SEALED_SHIPPING_ESTIMATE,
        min_match=SEALED_MIN_MATCH_SCORE,
        min_profit=SEALED_MIN_PROFIT,
    )
    print(
        f"Matched {stats['matched_count']}/{stats['ck_buy_count']} · "
        f"unmatched {stats['unmatched']} · no price {stats['no_price']} · "
        f"{stats['opportunity_count']} opportunities (min profit ${SEALED_MIN_PROFIT:.0f}, "
        f"ship est ${SEALED_SHIPPING_ESTIMATE:.0f})"
    )

    today = date.today()
    out_csv = SEALED_OPPORTUNITIES_DIR / f"sealed_cardbitrage_{today.isoformat()}.csv"
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"Wrote {out_csv}")

    loaded = load_sealed_opportunities(
        rows,
        snapshot_date=today,
        matched_count=stats["matched_count"],
        ck_buy_count=stats["ck_buy_count"],
    )
    print(f"Loaded {loaded} rows into Postgres sealed_opportunities ({today.isoformat()})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
