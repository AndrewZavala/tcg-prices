#!/usr/bin/env python3
"""Merge segment CSVs into daily cardkingdom_buylist_master file."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from config import (
    BUYLIST_LEGACY_DIR,
    BUYLIST_MASTER_DIR,
    ensure_dirs,
    raw_dir_for_date,
)


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ("finish", "rarity_bucket", "name", "slug"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    if "set" in df.columns:
        df["set"] = (
            df["set"].astype(str).str.replace(r"[\r\n]+", " ", regex=True).str.strip()
        )
    if "type" in df.columns:
        df["type"] = (
            df["type"].astype(str).str.replace(r"[\r\n]+", " ", regex=True).str.strip()
        )

    if "collector_number" in df.columns:
        df["collector_number"] = (
            df["collector_number"]
            .astype(str)
            .str.replace(r"^Collector #:\s*", "", regex=True)
            .str.strip()
        )

    for col in ("cash_price", "credit_price"):
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(r"[$,]", "", regex=True),
                errors="coerce",
            )

    if "max_qty" in df.columns:
        df["max_qty"] = pd.to_numeric(df["max_qty"], errors="coerce").astype("Int64")

    if "product_id" in df.columns:
        df["product_id"] = df["product_id"].astype(str)

    return df


API_SEGMENT = "cardkingdom_buylist_api.csv"


def collect_csv_dirs(today: str) -> list[Path]:
    dated = raw_dir_for_date(today)
    api_csv = dated / API_SEGMENT
    if api_csv.is_file():
        print(f"Using API buylist only: {api_csv}")
        return [dated]

    dirs = []
    if dated.is_dir() and any(dated.glob("*.csv")):
        dirs.append(dated)
    if BUYLIST_LEGACY_DIR.is_dir() and any(BUYLIST_LEGACY_DIR.glob("*.csv")):
        dirs.append(BUYLIST_LEGACY_DIR)
    return dirs


def merge_buylist(today: str | None = None) -> Path:
    ensure_dirs()
    today = today or date.today().isoformat()
    dirs = collect_csv_dirs(today)
    if not dirs:
        raise FileNotFoundError(
            f"No buylist CSVs in {raw_dir_for_date(today)} or {BUYLIST_LEGACY_DIR}"
        )

    frames = []
    for folder in dirs:
        for path in sorted(folder.glob("*.csv")):
            df = pd.read_csv(path, dtype={"collector_number": str}, low_memory=False)
            df["source_file"] = path.name
            frames.append(_clean_frame(df))

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["product_id"], keep="first")

    out = BUYLIST_MASTER_DIR / f"cardkingdom_buylist_master_{today}.csv"
    combined.to_csv(out, index=False)
    print(f"Merged {len(combined)} rows -> {out}")
    return out


def main() -> int:
    try:
        merge_buylist()
        return 0
    except Exception as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
