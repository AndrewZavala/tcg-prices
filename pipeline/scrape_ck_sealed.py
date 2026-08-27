#!/usr/bin/env python3
"""Fetch Card Kingdom sealed buylist from public sealed_pricelist API."""

from __future__ import annotations

import json
import sys
from datetime import date

import pandas as pd
import requests

from config import (
    CK_CREDIT_MULTIPLIER,
    CK_SEALED_PRICELIST_URL,
    SEALED_MASTER_DIR,
    SEALED_RAW_DIR,
    ensure_dirs,
)

SEGMENT_FILENAME = "cardkingdom_sealed_buylist_api.csv"


def fetch_sealed_pricelist() -> dict:
    resp = requests.get(CK_SEALED_PRICELIST_URL, timeout=300)
    resp.raise_for_status()
    return resp.json()


def transform_sealed(payload: dict) -> pd.DataFrame:
    rows = payload.get("data") or []
    records = []
    for item in rows:
        qty = int(item.get("qty_buying") or 0)
        cash = float(item.get("price_buy") or 0)
        if qty <= 0 or cash <= 0:
            continue

        url = (item.get("url") or "").strip()
        records.append(
            {
                "ck_product_id": str(item.get("id", "")),
                "name": item.get("name") or "",
                "edition": item.get("edition") or "",
                "cash_price": cash,
                "credit_price": round(cash * CK_CREDIT_MULTIPLIER, 2),
                "max_qty": qty,
                "price_retail": float(item.get("price_retail") or 0) or None,
                "qty_retail": int(item.get("qty_retail") or 0),
                "ships_internationally": item.get("ships_internationally"),
                "url": url,
                "ck_url": f"https://www.cardkingdom.com/{url}" if url else "",
            }
        )
    return pd.DataFrame(records)


def main() -> int:
    ensure_dirs()
    today = date.today().isoformat()
    out_dir = SEALED_RAW_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching {CK_SEALED_PRICELIST_URL}...")
    payload = fetch_sealed_pricelist()
    meta = payload.get("meta") or {}
    print(f"API created_at: {meta.get('created_at', 'unknown')}")

    raw_json = out_dir / "sealed_pricelist.json"
    with open(raw_json, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    df = transform_sealed(payload)
    if df.empty:
        print("No sealed buylist rows after filter (qty_buying > 0, price_buy > 0).", file=sys.stderr)
        return 1

    out_csv = out_dir / SEGMENT_FILENAME
    df.to_csv(out_csv, index=False)

    master = SEALED_MASTER_DIR / f"cardkingdom_sealed_master_{today}.csv"
    df.to_csv(master, index=False)
    print(f"Wrote {len(df)} rows to {out_csv}")
    print(f"Wrote master {master}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
