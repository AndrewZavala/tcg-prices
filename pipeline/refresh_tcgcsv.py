#!/usr/bin/env python3
"""Download Magic (TCGplayer category 1) prices from tcgcsv.com into a lookup CSV."""

from __future__ import annotations

import sys
import time

import pandas as pd
import requests

from config import HELPER_DIR, TCGCSV_PRICES_LOOKUP, ensure_dirs

MAGIC_CATEGORY_ID = 1
TCGCSV_BASE = "https://tcgcsv.com/tcgplayer"
USER_AGENT = "ManifestBread/1.0 (https://github.com/AndrewZavala/tcg-prices)"
REQUEST_DELAY_SEC = 0.15


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _fetch_json(session: requests.Session, url: str) -> dict | list | None:
    resp = session.get(url, timeout=120)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def fetch_magic_prices() -> pd.DataFrame:
    session = _session()
    groups_payload = _fetch_json(session, f"{TCGCSV_BASE}/{MAGIC_CATEGORY_ID}/groups")
    if not groups_payload or "results" not in groups_payload:
        raise RuntimeError("Unexpected tcgcsv groups response")

    groups = groups_payload["results"]
    rows: list[dict] = []
    total = len(groups)

    for idx, group in enumerate(groups, start=1):
        group_id = group["groupId"]
        prices_payload = _fetch_json(
            session, f"{TCGCSV_BASE}/{MAGIC_CATEGORY_ID}/{group_id}/prices"
        )
        if prices_payload and prices_payload.get("results"):
            for item in prices_payload["results"]:
                rows.append(
                    {
                        "product_id": item.get("productId"),
                        "sub_type_name": item.get("subTypeName") or "",
                        "market_price": item.get("marketPrice"),
                        "low_price": item.get("lowPrice"),
                        "mid_price": item.get("midPrice"),
                        "high_price": item.get("highPrice"),
                    }
                )

        if idx % 25 == 0 or idx == total:
            print(f"  {idx}/{total} groups · {len(rows):,} price rows so far")
        time.sleep(REQUEST_DELAY_SEC)

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No price rows returned from tcgcsv")

    for col in ("market_price", "low_price", "mid_price", "high_price"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["product_id"] = df["product_id"].astype("Int64").astype(str)
    df["sub_type_name"] = df["sub_type_name"].astype(str).str.strip()
    df = df.drop_duplicates(subset=["product_id", "sub_type_name"], keep="last")
    return df


def main() -> int:
    ensure_dirs()
    print(f"Fetching Magic prices from {TCGCSV_BASE}/{MAGIC_CATEGORY_ID}/…")
    df = fetch_magic_prices()
    df.to_csv(TCGCSV_PRICES_LOOKUP, index=False)
    print(f"Wrote {len(df):,} rows to {TCGCSV_PRICES_LOOKUP}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
