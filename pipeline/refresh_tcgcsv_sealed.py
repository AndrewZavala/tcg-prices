#!/usr/bin/env python3
"""Build a TCGCSV sealed-product catalog (Magic category) for CK matching."""

from __future__ import annotations

import re
import sys
import time

import pandas as pd
import requests

from config import HELPER_DIR, TCGCSV_SEALED_PRODUCTS_LOOKUP, ensure_dirs

MAGIC_CATEGORY_ID = 1
TCGCSV_BASE = "https://tcgcsv.com/tcgplayer"
USER_AGENT = "ManifestBread/1.0 (https://github.com/AndrewZavala/tcg-prices)"
REQUEST_DELAY_SEC = 0.12

# Avoid bare "case" (matches Showcase). Prefer sealed product phrases.
SEALED_RE = re.compile(
    r"""
    \bbooster\s+(?:box|display|pack|case)\b
    | \bcollector\s+booster\b
    | \bplay\s+booster\b
    | \bset\s+booster\b
    | \bdraft\s+booster\b
    | \bgift\s+bundle\b
    | \bfat\s+pack\b
    | \bbundle\b
    | \bcommander\s+deck\b
    | \bstarter\s+kit\b
    | \bscene\s+box\b
    | \bdisplay\s+case\b
    | \bmaster\s+case\b
    | \bchocobo\s+bundle\b
    | \bvip\b
    """,
    re.I | re.VERBOSE,
)


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


def is_sealed_product_name(name: str) -> bool:
    return bool(SEALED_RE.search(name or ""))


def fetch_sealed_products() -> pd.DataFrame:
    session = _session()
    groups_payload = _fetch_json(session, f"{TCGCSV_BASE}/{MAGIC_CATEGORY_ID}/groups")
    if not groups_payload or "results" not in groups_payload:
        raise RuntimeError("Unexpected tcgcsv groups response")

    groups = groups_payload["results"]
    rows: list[dict] = []
    total = len(groups)

    for idx, group in enumerate(groups, start=1):
        group_id = group["groupId"]
        products_payload = _fetch_json(
            session, f"{TCGCSV_BASE}/{MAGIC_CATEGORY_ID}/{group_id}/products"
        )
        for item in (products_payload or {}).get("results") or []:
            name = item.get("name") or ""
            if not is_sealed_product_name(name):
                continue
            rows.append(
                {
                    "product_id": item.get("productId"),
                    "name": name,
                    "clean_name": item.get("cleanName") or "",
                    "group_id": group_id,
                    "group_name": group.get("name") or "",
                    "group_abbr": group.get("abbreviation") or "",
                    "url": item.get("url") or "",
                }
            )

        if idx % 25 == 0 or idx == total:
            print(f"  {idx}/{total} groups · {len(rows):,} sealed products so far")
        time.sleep(REQUEST_DELAY_SEC)

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No sealed products found in tcgcsv Magic catalog")
    df["product_id"] = df["product_id"].astype("Int64").astype(str)
    df = df.drop_duplicates(subset=["product_id"], keep="last")
    return df


def main() -> int:
    ensure_dirs()
    print(f"Fetching sealed Magic products from {TCGCSV_BASE}/{MAGIC_CATEGORY_ID}/…")
    df = fetch_sealed_products()
    df.to_csv(TCGCSV_SEALED_PRODUCTS_LOOKUP, index=False)
    print(f"Wrote {len(df):,} rows to {TCGCSV_SEALED_PRODUCTS_LOOKUP}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
