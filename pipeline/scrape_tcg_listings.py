#!/usr/bin/env python3
"""Fetch TCGplayer product listings (by condition) via mp-search-api for buylist products."""

from __future__ import annotations

import os
import sys
import time
import json
from datetime import date

import pandas as pd
import requests

from config import (
    BUYLIST_MASTER_DIR,
    HELPER_DIR,
    SCRYFALL_CARDS_LOOKUP,
    TCG_LISTINGS_LOOKUP,
    ensure_dirs,
)
from tcg_condition import parse_listing_items
from sku_resolve import apply_sku_tcgplayer_resolution

LISTINGS_URL = "https://mp-search-api.tcgplayer.com/v1/product/{product_id}/listings"
USER_AGENT = "ManifestBread/1.0 (https://github.com/AndrewZavala/tcg-prices)"


def _env_float(key: str, default: str) -> float:
    raw = os.environ.get(key, default)
    if raw is None or str(raw).strip() == "":
        raw = default
    return float(raw)


def _env_int(key: str, default: str) -> int:
    raw = os.environ.get(key, default)
    if raw is None or str(raw).strip() == "":
        raw = default
    return int(raw)


REQUEST_DELAY_SEC = _env_float("TCG_LISTINGS_DELAY_SEC", "0.25")
MAX_PRODUCTS = _env_int("TCG_LISTINGS_MAX_PRODUCTS", "5000")
MAX_CASH_PRICE = _env_float("TCG_LISTINGS_MAX_CASH_PRICE", "0")
LISTING_PAGE_SIZE = _env_int("TCG_LISTINGS_PAGE_SIZE", "120")
LISTINGS_CSV_COLUMNS = [
    "product_id",
    "card_name",
    "edition",
    "set_name",
    "set_code",
    "collector_number",
    "variation",
    "finish",
    "condition",
    "price",
    "shipping_price",
    "seller_shipping_price",
    "ranked_shipping_price",
    "quantity_available",
    "seller",
    "seller_key",
    "listing_id",
    "scraped_date",
]
LISTING_META_COLUMNS = [
    "card_name",
    "edition",
    "set_name",
    "set_code",
    "collector_number",
    "variation",
]


def format_listings_df(listings: pd.DataFrame) -> pd.DataFrame:
    if listings.empty:
        return pd.DataFrame(columns=LISTINGS_CSV_COLUMNS)
    listings = listings.copy()
    for col in LISTINGS_CSV_COLUMNS:
        if col not in listings.columns:
            listings[col] = ""
    return listings.reindex(columns=LISTINGS_CSV_COLUMNS)


def target_listing_meta(row) -> dict[str, str]:
    """CK product context copied onto each listing row."""
    return {
        col: str(getattr(row, col, "") or "").strip()
        for col in LISTING_META_COLUMNS
    }


def latest_listings_only(listings: pd.DataFrame) -> pd.DataFrame:
    """Drop rows from older scrapes when a lookup file spans multiple dates."""
    listings = format_listings_df(listings)
    if listings.empty or "scraped_date" not in listings.columns:
        return listings
    dates = listings["scraped_date"].astype(str).str.strip()
    dates = dates[(dates != "") & ~dates.str.lower().isin({"nan", "none"})]
    if dates.empty:
        return listings
    latest = dates.max()
    filtered = listings[dates.eq(latest)].copy()
    dropped = len(listings) - len(filtered)
    if dropped:
        print(f"Ignored {dropped:,} listing rows from scrapes before {latest}")
    return filtered


def read_listings_lookup() -> pd.DataFrame:
    """Load listings CSV, keeping only the most recent scrape."""
    if not TCG_LISTINGS_LOOKUP.exists() or TCG_LISTINGS_LOOKUP.stat().st_size == 0:
        return format_listings_df(pd.DataFrame())
    try:
        listings = pd.read_csv(TCG_LISTINGS_LOOKUP, low_memory=False)
    except pd.errors.EmptyDataError:
        return format_listings_df(pd.DataFrame())
    return latest_listings_only(listings)


def merge_listings_lookup(new: pd.DataFrame) -> pd.DataFrame:
    """Replace the lookup with this scrape only (no carry-over from prior runs)."""
    return format_listings_df(new)


def write_listings_lookup(listings: pd.DataFrame) -> int:
    listings = merge_listings_lookup(listings)
    ensure_dirs()
    tmp = TCG_LISTINGS_LOOKUP.with_suffix(".tmp")
    listings.to_csv(tmp, index=False)
    try:
        tmp.replace(TCG_LISTINGS_LOOKUP)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise OSError(
            f"Could not write {TCG_LISTINGS_LOOKUP} ({exc}). "
            "Close Excel or other apps using the file and retry."
        ) from exc
    return len(listings)


def print_targets_summary(targets: pd.DataFrame) -> None:
    if targets.empty:
        print("No listing targets matched filters.")
        return
    cap = f" <= ${MAX_CASH_PRICE:g}" if MAX_CASH_PRICE > 0 else ""
    print(
        f"Selected {len(targets):,} targets "
        f"(top {MAX_PRODUCTS if MAX_PRODUCTS > 0 else 'all'} CK cash{cap}):"
    )
    for row in targets.itertuples(index=False):
        cash = getattr(row, "cash_price", "")
        parts = [
            str(getattr(row, "card_name", "") or "?"),
            str(getattr(row, "variation", "") or ""),
            str(getattr(row, "edition", "") or ""),
            str(getattr(row, "collector_number", "") or ""),
        ]
        label = " · ".join(p for p in parts if p and p.lower() not in {"nan", "none", "?"})
        print(f"  ${cash} · {label} · product {row.product_id} ({row.finish})")


def _latest_master_path():
    files = sorted(BUYLIST_MASTER_DIR.glob("cardkingdom_buylist_master_*.csv"))
    if not files:
        raise FileNotFoundError(f"No master files in {BUYLIST_MASTER_DIR}")
    return files[-1]


def _normalize_finish(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "finish" not in out.columns:
        out["finish"] = "normal"
    raw = out["finish"].astype(str).str.strip().str.lower()
    out["finish"] = raw.replace({"nonfoil": "normal", "": "normal", "nan": "normal"})
    set_col = out.get("set", pd.Series("", index=out.index)).astype(str)
    out.loc[set_col.str.contains(r"\bFOIL\b", case=False, na=False), "finish"] = "foil"
    return out


def _clean_pid(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(".0", "")
    if not text or text.lower() in {"nan", "none"}:
        return None
    try:
        return str(int(float(text)))
    except (ValueError, TypeError):
        return text


def _build_scrape_targets(master: pd.DataFrame, scryfall: pd.DataFrame) -> pd.DataFrame:
    """Build scrape target list (screened candidates or legacy top-N by CK cash)."""
    from screen_candidates import USE_SCREENING, build_scrape_targets_from_master

    if USE_SCREENING:
        return build_scrape_targets_from_master(master)

    return _build_scrape_targets_legacy(master, scryfall)


def _build_scrape_targets_legacy(master: pd.DataFrame, scryfall: pd.DataFrame) -> pd.DataFrame:
    ck = _normalize_finish(master)
    if "scryfall_id_api" in ck.columns:
        if "scryfall_id" in ck.columns:
            ck["scryfall_id"] = ck["scryfall_id"].fillna(ck["scryfall_id_api"])
        else:
            ck["scryfall_id"] = ck["scryfall_id_api"]

    meta = scryfall[
        ["scryfall_id", "set_code", "tcgplayer_id", "tcgplayer_etched_id"]
    ].drop_duplicates(subset=["scryfall_id"])
    ck = ck.merge(meta, on="scryfall_id", how="left", suffixes=("", "_sf"))
    for col in ("tcgplayer_id", "tcgplayer_etched_id"):
        sf_col = f"{col}_sf"
        if sf_col in ck.columns:
            ck[col] = ck[col].fillna(ck[sf_col])
            ck = ck.drop(columns=[sf_col], errors="ignore")

    ck = apply_sku_tcgplayer_resolution(ck, scryfall)

    finish = ck["finish"].astype(str).str.lower()
    pid = ck["tcgplayer_id"].map(_clean_pid)
    etched = ck["tcgplayer_etched_id"].map(_clean_pid)
    ck["product_id"] = pid
    ck.loc[finish.eq("etched") & etched.notna(), "product_id"] = etched.loc[
        finish.eq("etched") & etched.notna()
    ]

    if "name" in ck.columns:
        ck["card_name"] = ck["name"].astype(str).str.strip()
    else:
        ck["card_name"] = ""
    ck["edition"] = (
        ck["edition"].astype(str).str.strip()
        if "edition" in ck.columns
        else ""
    )
    ck["set_name"] = (
        ck["set"].astype(str).str.strip() if "set" in ck.columns else ""
    )
    ck["variation"] = (
        ck["variation"].fillna("").astype(str).str.strip()
        if "variation" in ck.columns
        else ""
    )
    if "sku" in ck.columns:
        sku = ck["sku"].fillna("").astype(str).str.strip()
    else:
        sku = pd.Series("", index=ck.index)
    if "collector_number" in ck.columns:
        cn = ck["collector_number"].fillna("").astype(str).str.strip()
    else:
        cn = pd.Series("", index=ck.index)
    ck["collector_number"] = sku.where(
        sku.notna() & ~sku.str.lower().isin({"", "api", "nan", "none"}),
        cn,
    )
    if "set_code" in ck.columns:
        ck["set_code"] = ck["set_code"].fillna("").astype(str).str.strip().str.lower()
    else:
        ck["set_code"] = ""

    ck["cash_price"] = pd.to_numeric(ck["cash_price"], errors="coerce")

    targets = (
        ck[
            [
                "product_id",
                "card_name",
                "edition",
                "set_name",
                "set_code",
                "collector_number",
                "variation",
                "finish",
                "cash_price",
            ]
        ]
        .dropna(subset=["product_id", "cash_price"])
        .sort_values("cash_price", ascending=False)
        .drop_duplicates(subset=["product_id", "finish"], keep="first")
    )
    if MAX_CASH_PRICE > 0:
        targets = targets[targets["cash_price"] <= MAX_CASH_PRICE]
    if MAX_PRODUCTS > 0 and len(targets) > MAX_PRODUCTS:
        targets = targets.head(MAX_PRODUCTS)
    return targets.reset_index(drop=True)


def _fetch_listings(session: requests.Session, product_id: str) -> dict | list | None:
    url = LISTINGS_URL.format(product_id=product_id)
    listing_search = {
        "from": 0,
        "size": LISTING_PAGE_SIZE,
        "sort": [{"field": "price", "order": "asc"}],
        "context": {"cart": {}, "shippingCountry": "US"},
        "filters": {
            "term": {
                "sellerStatus": "Live",
                "channelId": 0,
                "listingType": "standard",
                "language": ["English"],
            },
            "range": {"quantity": {"gte": 1}},
            "exclude": {
                "channelExclusion": 0,
                "listingType": "custom",
            },
        },
    }
    body = {"listingSearch": json.dumps(listing_search, separators=(",", ":"))}
    resp = session.post(
        url,
        json=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Origin": "https://www.tcgplayer.com",
            "Referer": f"https://www.tcgplayer.com/product/{product_id}",
        },
        timeout=60,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def scrape_targets(targets: pd.DataFrame) -> pd.DataFrame:
    session = requests.Session()
    rows: list[dict] = []
    total = len(targets)

    for idx, row in enumerate(targets.itertuples(index=False), start=1):
        product_id = row.product_id
        finish = str(row.finish).lower()
        meta = target_listing_meta(row)
        try:
            payload = _fetch_listings(session, product_id)
            for listing in parse_listing_items(payload, product_id, finish):
                listing.update(meta)
                rows.append(listing)
        except requests.RequestException as exc:
            print(f"  warn: product {product_id} ({finish}): {exc}", file=sys.stderr)

        if idx % 100 == 0 or idx == total:
            print(f"  {idx}/{total} products · {len(rows):,} listing rows")
        time.sleep(REQUEST_DELAY_SEC)

    return pd.DataFrame(rows)


def main() -> int:
    ensure_dirs()
    if not SCRYFALL_CARDS_LOOKUP.exists():
        raise FileNotFoundError(
            f"Missing {SCRYFALL_CARDS_LOOKUP}. Run pipeline/refresh_scryfall.py first."
        )

    master = _latest_master_path()
    print(f"Building scrape targets from {master}...")
    master_df = pd.read_csv(master, low_memory=False)
    scryfall_df = pd.read_csv(SCRYFALL_CARDS_LOOKUP, low_memory=False)
    targets = _build_scrape_targets(master_df, scryfall_df)
    print_targets_summary(targets)
    print(f"Scraping listings for {len(targets):,} product/finish pairs...")

    listings = scrape_targets(targets)
    listings["scraped_date"] = date.today().isoformat()
    if listings.empty:
        print(
            "WARNING: No listing rows returned (TCGplayer may block server IPs with 403). "
            "Enrich will have no TCG buy prices until live mp-search API data is available.",
            file=sys.stderr,
        )
        if TCG_LISTINGS_LOOKUP.exists() and TCG_LISTINGS_LOOKUP.stat().st_size > 0:
            try:
                existing = pd.read_csv(TCG_LISTINGS_LOOKUP, nrows=1)
            except pd.errors.EmptyDataError:
                existing = pd.DataFrame()
            if not existing.empty:
                print(
                    f"Keeping existing non-empty listings lookup at {TCG_LISTINGS_LOOKUP}",
                    file=sys.stderr,
                )
                return 0
    listings = format_listings_df(listings)
    row_count = write_listings_lookup(listings)
    print(f"Wrote {row_count:,} rows to {TCG_LISTINGS_LOOKUP}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
