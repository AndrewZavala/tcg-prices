#!/usr/bin/env python3
"""Download Scryfall default_cards bulk and build card lookup CSV."""

from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

import pandas as pd
import requests

from config import HELPER_DIR, SCRYFALL_BULK_JSON, SCRYFALL_CARDS_LOOKUP, ensure_dirs

BULK_META_URL = "https://api.scryfall.com/bulk-data"
SCRYFALL_HEADERS = {
    "User-Agent": os.environ.get(
        "SCRYFALL_USER_AGENT",
        "TCGCardbitrage/1.0 (https://github.com/andre/tcg-buylist)",
    ),
    "Accept": "application/json",
}
DOWNLOAD_HEADERS = {
    "User-Agent": SCRYFALL_HEADERS["User-Agent"],
    "Accept": "*/*",
}


def _bulk_download_uri(default: dict) -> tuple[str, bool]:
    """Return (uri, is_jsonl_gz). Prefer jsonl_download_uri (current Scryfall format)."""
    jsonl = default.get("jsonl_download_uri")
    if jsonl:
        return jsonl, True
    legacy = default.get("download_uri")
    if legacy:
        return legacy, legacy.endswith(".jsonl.gz") or "jsonl" in legacy
    raise KeyError(
        "Scryfall bulk object missing jsonl_download_uri/download_uri; "
        f"keys={sorted(default.keys())}"
    )


def _iter_cards(path: Path, is_jsonl_gz: bool):
    if is_jsonl_gz:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
        return
    with open(path, encoding="utf-8") as f:
        cards = json.load(f)
    yield from cards


def main() -> int:
    ensure_dirs()
    print("Fetching Scryfall bulk metadata...")
    meta = requests.get(BULK_META_URL, headers=SCRYFALL_HEADERS, timeout=60).json()
    default = next(x for x in meta["data"] if x["type"] == "default_cards")
    download_uri, is_jsonl_gz = _bulk_download_uri(default)
    dest = (
        HELPER_DIR / "scryfall_default_cards.jsonl.gz"
        if is_jsonl_gz
        else SCRYFALL_BULK_JSON
    )
    print(f"Downloading {download_uri} (this may take several minutes)...")

    resp = requests.get(download_uri, headers=DOWNLOAD_HEADERS, timeout=600, stream=True)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)

    print("Parsing bulk cards...")
    rows = []
    for c in _iter_cards(dest, is_jsonl_gz):
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
