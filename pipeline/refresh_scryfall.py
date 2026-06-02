#!/usr/bin/env python3
"""Download Scryfall default_cards bulk and build card lookup CSV."""

from __future__ import annotations

import json
import sys

import pandas as pd
import requests

from config import HELPER_DIR, SCRYFALL_BULK_JSON, SCRYFALL_CARDS_LOOKUP, ensure_dirs

BULK_META_URL = "https://api.scryfall.com/bulk-data"


def main() -> int:
    ensure_dirs()
    print("Fetching Scryfall bulk metadata...")
    meta = requests.get(BULK_META_URL, timeout=60).json()
    default = next(x for x in meta["data"] if x["type"] == "default_cards")
    download_uri = default["download_uri"]
    print(f"Downloading {download_uri} (this may take several minutes)...")

    resp = requests.get(download_uri, timeout=600, stream=True)
    resp.raise_for_status()
    with open(SCRYFALL_BULK_JSON, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)

    print("Parsing JSON...")
    with open(SCRYFALL_BULK_JSON, encoding="utf-8") as f:
        cards = json.load(f)

    rows = []
    for c in cards:
        prices = c.get("prices") or {}
        rows.append(
            {
                "scryfall_id": c.get("id"),
                "set_code": str(c.get("set", "")).lower(),
                "collector_number": str(c.get("collector_number", "")),
                "tcgplayer_id": c.get("tcgplayer_id"),
                "tcgplayer_etched_id": c.get("tcgplayer_etched_id"),
                "usd": prices.get("usd"),
                "usd_foil": prices.get("usd_foil"),
                "usd_etched": prices.get("usd_etched"),
            }
        )

    df = pd.DataFrame(rows)
    df.to_csv(SCRYFALL_CARDS_LOOKUP, index=False)
    print(f"Wrote {len(df)} rows to {SCRYFALL_CARDS_LOOKUP}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
