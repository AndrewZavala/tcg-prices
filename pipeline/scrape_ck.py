#!/usr/bin/env python3
"""Fetch Card Kingdom buylist from public pricelist API."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from config import (
    CK_CREDIT_MULTIPLIER,
    CK_PRICELIST_URL,
    ensure_dirs,
    raw_dir_for_date,
)

SEGMENT_FILENAME = "cardkingdom_buylist_api.csv"


def _parse_collector_number(sku: str) -> str:
    if not sku or "-" not in sku:
        return ""
    return sku.split("-", 1)[1]


def _edition_display(edition: str, is_foil: bool) -> str:
    ed = (edition or "").strip()
    if is_foil and ed and not re.search(r"\bFOIL\b", ed, re.I):
        return f"{ed} FOIL"
    return ed


def fetch_pricelist() -> dict:
    resp = requests.get(CK_PRICELIST_URL, timeout=300)
    resp.raise_for_status()
    return resp.json()


def transform_buylist(payload: dict) -> pd.DataFrame:
    rows = payload.get("data") or []
    records = []
    for item in rows:
        qty = int(item.get("qty_buying") or 0)
        cash = float(item.get("price_buy") or 0)
        if qty <= 0 or cash <= 0:
            continue

        is_foil = str(item.get("is_foil", "")).lower() in ("true", "1", "yes")
        edition = item.get("edition") or ""
        name = item.get("name") or ""
        sku = item.get("sku") or ""
        url = item.get("url") or ""
        slug = url.split("/")[-1] if url else ""

        records.append(
            {
                "finish": "foil" if is_foil else "nonfoil",
                "rarity_bucket": "api",
                "page": 1,
                "name": name,
                "edition": edition,
                "set": _edition_display(edition, is_foil),
                "type": "api",
                "collector_number": _parse_collector_number(sku),
                "cash_price": cash,
                "credit_price": round(cash * CK_CREDIT_MULTIPLIER, 2),
                "max_qty": qty,
                "slug": slug,
                "product_id": str(item.get("id", "")),
                "scryfall_id_api": item.get("scryfall_id") or "",
                "sku": sku,
                "variation": item.get("variation") or "",
            }
        )

    return pd.DataFrame(records)


def main() -> int:
    ensure_dirs()
    today = date.today().isoformat()
    out_dir = raw_dir_for_date(today)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching {CK_PRICELIST_URL}...")
    payload = fetch_pricelist()
    meta = payload.get("meta") or {}
    print(f"API created_at: {meta.get('created_at', 'unknown')}")

    raw_json = out_dir / "pricelist.json"
    with open(raw_json, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    df = transform_buylist(payload)
    if df.empty:
        print("No buylist rows after filter (qty_buying > 0, price_buy > 0).", file=sys.stderr)
        return 1

    out_csv = out_dir / SEGMENT_FILENAME
    df.to_csv(out_csv, index=False)
    print(f"Wrote {len(df)} rows to {out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
