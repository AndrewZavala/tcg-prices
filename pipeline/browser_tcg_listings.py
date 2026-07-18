#!/usr/bin/env python3
"""Fetch TCGplayer listings through a real browser session.

This keeps the fast mp-search-api JSON path, but executes requests from inside
TCGplayer's page context so browser cookies/session/fingerprint are present.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

from config import (
    HELPER_DIR,
    SCRYFALL_CARDS_LOOKUP,
    TCG_LISTINGS_LOOKUP,
    ensure_dirs,
)
from scrape_tcg_listings import (
    REQUEST_DELAY_SEC,
    _build_scrape_targets,
    _latest_master_path,
    format_listings_df,
    print_targets_summary,
    target_listing_meta,
    write_listings_lookup,
)
from tcg_condition import parse_listing_items

BROWSER_PROFILE_DIR = Path(
    os.environ.get("TCG_BROWSER_PROFILE_DIR", HELPER_DIR / "tcgplayer-browser-profile")
)
BROWSER_CHANNEL = os.environ.get("TCG_BROWSER_CHANNEL", "msedge")
BROWSER_CDP_URL = os.environ.get("TCG_BROWSER_CDP_URL", "")
BROWSER_HEADLESS = os.environ.get("TCG_BROWSER_HEADLESS", "0").lower() in {
    "1",
    "true",
    "yes",
}
BROWSER_LISTING_PAGE_SIZE = int(os.environ.get("TCG_BROWSER_LISTING_PAGE_SIZE", "20"))
BROWSER_RETRY_ATTEMPTS = int(os.environ.get("TCG_BROWSER_RETRY_ATTEMPTS", "3"))
BROWSER_RETRY_DELAY_SEC = float(os.environ.get("TCG_BROWSER_RETRY_DELAY_SEC", "2"))
MIN_LISTING_ROWS = int(os.environ.get("TCG_LISTINGS_MIN_ROWS", "1000"))
MIN_PRODUCT_SUCCESS_RATE = float(os.environ.get("TCG_LISTINGS_MIN_SUCCESS_RATE", "0.02"))
PREFLIGHT_COUNT = int(os.environ.get("TCG_LISTINGS_PREFLIGHT_COUNT", "5"))
PREFLIGHT_MIN_PRODUCTS = int(os.environ.get("TCG_LISTINGS_PREFLIGHT_MIN_PRODUCTS", "1"))
SKIP_PREFLIGHT = os.environ.get("TCG_LISTINGS_SKIP_PREFLIGHT", "").lower() in {
    "1",
    "true",
    "yes",
}
BROWSER_NAVIGATE_EACH = os.environ.get("TCG_BROWSER_NAVIGATE_EACH", "0").lower() in {
    "1",
    "true",
    "yes",
}
BROWSER_START_URL = "https://www.tcgplayer.com/product/{product_id}"
PRODUCT_ID_FILTER = {
    pid.strip()
    for pid in os.environ.get("TCG_LISTINGS_PRODUCT_IDS", "").split(",")
    if pid.strip()
}


def _printing_filter(finish: str) -> list[str]:
    finish_l = str(finish or "normal").lower()
    if finish_l == "foil":
        return ["Foil"]
    if finish_l == "etched":
        return ["Etched"]
    return ["Normal"]


def _listing_search(finish: str) -> dict:
    term = {
        "sellerStatus": "Live",
        "channelId": 0,
        "language": ["English"],
        "printing": _printing_filter(finish),
    }

    return {
        "from": 0,
        "size": BROWSER_LISTING_PAGE_SIZE,
        "sort": {"field": "price+shipping", "order": "asc"},
        "context": {"shippingCountry": "US", "cart": {"packages": {}}},
        "aggregations": ["listingType"],
        "filters": {
            "term": term,
            "range": {"quantity": {"gte": 1}},
            "exclude": {"channelExclusion": 0},
        },
    }


async def _fetch_listings_in_browser(page, product_id: str, finish: str) -> dict | list | None:
    body = _listing_search(finish)
    url = f"https://mp-search-api.tcgplayer.com/v1/product/{product_id}/listings"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.tcgplayer.com",
        "Referer": f"https://www.tcgplayer.com/product/{product_id}",
    }
    last_error: Exception | None = None

    for attempt in range(1, BROWSER_RETRY_ATTEMPTS + 1):
        try:
            # context.request shares the browser cookie jar and avoids page CORS issues.
            res = await page.context.request.post(url, data=body, headers=headers)
            if res.status == 404:
                return None
            if res.status in {403, 429, 502, 503} and attempt < BROWSER_RETRY_ATTEMPTS:
                await page.goto(
                    BROWSER_START_URL.format(product_id=product_id),
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(int(BROWSER_RETRY_DELAY_SEC * 1000 * attempt))
                continue
            if not res.ok:
                raise RuntimeError(f"{res.status} {(await res.text())[:300]}")
            return json.loads(await res.text())
        except Exception as exc:
            last_error = exc
            if attempt >= BROWSER_RETRY_ATTEMPTS:
                break
            await page.wait_for_timeout(int(BROWSER_RETRY_DELAY_SEC * 1000 * attempt))

    # Last resort: in-page fetch (works for some non-CDP persistent profiles).
    try:
        response = await page.evaluate(
            """async ({ productId, body }) => {
                const res = await fetch(
                    `https://mp-search-api.tcgplayer.com/v1/product/${productId}/listings`,
                    {
                        method: "POST",
                        credentials: "include",
                        headers: {
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        },
                        body: JSON.stringify(body),
                    },
                );
                return {
                    status: res.status,
                    ok: res.ok,
                    text: await res.text(),
                };
            }""",
            {"productId": product_id, "body": body},
        )
        if response["status"] == 404:
            return None
        if not response["ok"]:
            raise RuntimeError(f"{response['status']} {response['text'][:300]}")
        return json.loads(response["text"])
    except Exception as exc:
        if last_error is not None:
            raise last_error from exc
        raise


async def scrape_targets_browser(targets: pd.DataFrame) -> pd.DataFrame:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Missing Playwright. Install with: pip install playwright"
        ) from exc

    rows: list[dict] = []
    total = len(targets)
    products_with_listings = 0
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = None
        if BROWSER_CDP_URL:
            browser = await pw.chromium.connect_over_cdp(BROWSER_CDP_URL)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
        else:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_PROFILE_DIR),
                channel=BROWSER_CHANNEL or None,
                headless=BROWSER_HEADLESS,
                viewport={"width": 1440, "height": 1000},
            )
        page = context.pages[0] if context.pages else await context.new_page()

        await page.goto("https://www.tcgplayer.com/", wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        first_product = str(targets.iloc[0].product_id)
        await page.goto(BROWSER_START_URL.format(product_id=first_product), wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)

        for idx, row in enumerate(targets.itertuples(index=False), start=1):
            product_id = str(row.product_id)
            finish = str(row.finish).lower()
            meta = target_listing_meta(row)
            product_rows_before = len(rows)
            try:
                if BROWSER_NAVIGATE_EACH:
                    await page.goto(
                        BROWSER_START_URL.format(product_id=product_id),
                        wait_until="domcontentloaded",
                    )
                payload = await _fetch_listings_in_browser(page, product_id, finish)
                for listing in parse_listing_items(payload, product_id, finish):
                    listing.update(meta)
                    rows.append(listing)
                if len(rows) > product_rows_before:
                    products_with_listings += 1
            except Exception as exc:
                print(f"  warn: product {product_id} ({finish}): {exc}", file=sys.stderr)

            if idx % 25 == 0 or idx == total:
                hit_rate = (products_with_listings / idx) if idx else 0.0
                print(
                    f"  {idx}/{total} products · {len(rows):,} listing rows · "
                    f"{products_with_listings:,} products with listings ({hit_rate:.1%})"
                )
            if REQUEST_DELAY_SEC > 0:
                await page.wait_for_timeout(int(REQUEST_DELAY_SEC * 1000))

        if browser is not None:
            await browser.close()
        else:
            await context.close()

    return pd.DataFrame(rows)


def _products_with_listings(listings: pd.DataFrame) -> int:
    if listings.empty or "product_id" not in listings.columns:
        return 0
    priced = listings.copy()
    if "price" in priced.columns:
        priced["price"] = pd.to_numeric(priced["price"], errors="coerce")
        priced = priced[priced["price"].notna() & (priced["price"] > 0)]
    if priced.empty:
        return 0
    return priced["product_id"].astype(str).nunique()


def _validate_preflight(listings: pd.DataFrame, sample: pd.DataFrame) -> tuple[bool, str]:
    """Return (ok, summary) for a small pre-run smoke test."""
    sample_n = len(sample)
    if sample_n == 0:
        return False, "no preflight targets"

    with_listings = _products_with_listings(listings)
    row_count = len(listings)
    min_products = max(1, min(PREFLIGHT_MIN_PRODUCTS, sample_n))

    if with_listings < min_products:
        return (
            False,
            f"only {with_listings}/{sample_n} products returned priced listings "
            f"(need {min_products}); mp-search API or CDP session may be blocked",
        )

    lines: list[str] = []
    for row in sample.itertuples(index=False):
        pid = str(row.product_id)
        subset = listings[listings["product_id"].astype(str) == pid] if not listings.empty else listings
        if subset.empty:
            lines.append(f"  {row.card_name or '?'} · product {pid} · no listings")
            continue
        prices = pd.to_numeric(subset["price"], errors="coerce").dropna()
        low = prices.min() if not prices.empty else None
        if low is not None:
            lines.append(
                f"  {row.card_name or '?'} · product {pid} · "
                f"{len(subset)} rows · low ${low:.2f}"
            )
        else:
            lines.append(
                f"  {row.card_name or '?'} · product {pid} · {len(subset)} rows"
            )

    summary = (
        f"{with_listings}/{sample_n} products with listings, {row_count:,} rows\n"
        + "\n".join(lines)
    )
    return True, summary


async def run_preflight(targets: pd.DataFrame) -> bool:
    """Smoke-test mp-search on a few products before the full buylist scrape."""
    if SKIP_PREFLIGHT or PREFLIGHT_COUNT <= 0 or PRODUCT_ID_FILTER:
        return True
    if len(targets) <= PREFLIGHT_COUNT:
        return True

    sample = targets.head(PREFLIGHT_COUNT).copy()
    print(
        f"Preflight: testing mp-search API on {len(sample)} products "
        f"before fetching {len(targets):,}..."
    )
    print_targets_summary(sample)

    listings = await scrape_targets_browser(sample)
    ok, summary = _validate_preflight(listings, sample)
    if not ok:
        print(f"ERROR: Preflight failed — {summary}", file=sys.stderr)
        print(
            "Check Edge CDP on :9222, browse tcgplayer.com in that profile, then retry.",
            file=sys.stderr,
        )
        return False

    print(f"Preflight OK — {summary}")
    return True


async def async_main() -> int:
    ensure_dirs()
    if not SCRYFALL_CARDS_LOOKUP.exists():
        raise FileNotFoundError(
            f"Missing {SCRYFALL_CARDS_LOOKUP}. Run pipeline/refresh_scryfall.py first."
        )

    master = _latest_master_path()
    print(f"Building browser scrape targets from {master}...")
    master_df = pd.read_csv(master, low_memory=False)
    scryfall_df = pd.read_csv(SCRYFALL_CARDS_LOOKUP, low_memory=False)
    targets = _build_scrape_targets(master_df, scryfall_df)
    if PRODUCT_ID_FILTER:
        targets = targets[targets["product_id"].astype(str).isin(PRODUCT_ID_FILTER)]
        if targets.empty:
            targets = pd.DataFrame(
                {
                    "product_id": sorted(PRODUCT_ID_FILTER),
                    "card_name": "",
                    "edition": "",
                    "set_name": "",
                    "set_code": "",
                    "collector_number": "",
                    "variation": "",
                    "finish": "normal",
                    "cash_price": 0,
                }
            )
    print_targets_summary(targets)
    print(
        f"Fetching listings for {len(targets):,} product/finish pairs "
        f"using browser profile {BROWSER_PROFILE_DIR}..."
    )

    if not await run_preflight(targets):
        return 1

    started = time.time()
    listings = await scrape_targets_browser(targets)
    listings["scraped_date"] = date.today().isoformat()
    if listings.empty:
        print(
            "ERROR: mp-search API returned no listing rows. "
            "Check Edge CDP session and retry.",
            file=sys.stderr,
        )
        return 1

    if len(listings) < MIN_LISTING_ROWS:
        print(
            f"ERROR: Only {len(listings):,} listing rows (minimum {MIN_LISTING_ROWS:,}).",
            file=sys.stderr,
        )
        return 1

    unique_products = listings["product_id"].nunique() if "product_id" in listings.columns else 0
    success_rate = unique_products / len(targets) if len(targets) else 0.0
    if success_rate < MIN_PRODUCT_SUCCESS_RATE:
        print(
            f"ERROR: Listings for {unique_products:,}/{len(targets):,} products "
            f"({success_rate:.1%}); need {MIN_PRODUCT_SUCCESS_RATE:.1%}.",
            file=sys.stderr,
        )
        return 1

    listings = format_listings_df(listings)
    row_count = write_listings_lookup(listings)
    elapsed = time.time() - started
    print(f"Wrote {row_count:,} rows to {TCG_LISTINGS_LOOKUP} in {elapsed:.1f}s (replaced prior scrape)")
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
